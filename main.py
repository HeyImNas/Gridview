import json
import asyncio
import aiohttp
import sqlite3
import os
import sys
import logging
from dotenv import load_dotenv
import nodriver as uc
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from loguru import logger
import time
import requests
from curl_cffi import requests as c_requests

# --- LOGGING SETUP ---
# 1. Clear Loguru's default setup
logger.remove()

# 2. Change INFO color to yellow
logger.level("INFO", color="<yellow>")

# 3. Add our custom format and force it to only show INFO and above
logger.add(
    sys.stdout, 
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <2}</level> | {message}",
    level="INFO" 
)

# 4. Create an Interceptor for Uvicorn
class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        message = record.getMessage()
        
        # Colorize the 200 status code for the api/streams endpoint
        if record.name == "uvicorn.access" and "/api/streams" in message and message.endswith(" 200"):
            message = message[:-4] + " <green>200</green>"

        # Use colors=True so Loguru translates the <green> tag into actual terminal color
        logger.opt(depth=depth, exception=record.exc_info, colors=True).log(level, message)

# 5. Hijack Uvicorn's loggers and route them through the Interceptor
logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)
for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    logger_instance = logging.getLogger(name)
    logger_instance.handlers = [InterceptHandler()]
    logger_instance.propagate = False


# --- CONFIGURATION ---
KICK_API_URL = "https://web.kick.com/api/v1/livestreams?limit=100&sort=viewer_count_desc&category_id=9818"

# --- ENVIRONMENT SETUP ---
base_path = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base_path, ".env")
load_dotenv(dotenv_path=env_path)

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
    logger.critical(f"Credentials missing! Checked path: {env_path}")

stream_cache = {
    "count": 0,
    "streams": [],
    "status": "Initializing..."
}

def get_streamers_from_db():
    try:
        db_path = os.path.join(base_path, "streamers.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM streamers")
        names = [row[0] for row in cursor.fetchall()]
        conn.close()
        return names
    except sqlite3.Error as e:
        logger.error(f"DB Error: {e}")
        return []

def load_json_safe(filename, default_val):
    """Safely loads a JSON file without crashing the server if there's a typo."""
    filepath = os.path.join(base_path, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content: return default_val
            return json.loads(content)
    except Exception as e:
        logger.warning(f"Could not load {filename}: {e}")
        return default_val

def get_streamer_tags(channel_name, groups_data):
    """Matches a streamer to their groups based on the updated groups.json structure."""
    tags = []
    channel_lower = channel_name.lower()
    
    for tag_label, info in groups_data.items():
        # Get the members dictionary block safely
        members_dict = info.get("members", {})
        
        # Create a list of lowercased member names to check against
        members_lower = [k.lower() for k in members_dict.keys()]
        
        if channel_lower in members_lower:
            tags.append({
                "label": tag_label,
                "rank": info.get("full_name", tag_label),
                "color": info.get("color", "#888888")
            })
            
    return tags

def chunk_list(data_list, chunk_size):
    for i in range(0, len(data_list), chunk_size):
        yield data_list[i:i + chunk_size]

async def get_twitch_token():
    url = f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
    async with aiohttp.ClientSession() as session:
        async with session.post(url) as response:
            data = await response.json()
            return data.get("access_token")

async def fetch_twitch_streams_by_name(token, valid_streamers, title_blacklist, groups_data):
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    twitch_streams = []

    if not valid_streamers:
        return []

    async with aiohttp.ClientSession() as session:
        for i, chunk in enumerate(chunk_list(valid_streamers, 100)):
            params = [("user_login", name) for name in chunk]
            url = "https://api.twitch.tv/helix/streams"
            
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    for stream in data.get("data", []):
                        if stream.get("game_id") == "32982": # GTA V
                            title = stream.get("title", "").lower()
                            
                            # Title Filter
                            if any(term in title for term in title_blacklist):
                                continue 
                                
                            channel_name = stream.get("user_login")
                            thumb = stream.get("thumbnail_url", "").replace("{width}", "640").replace("{height}", "360")
                            
                            # Attach Tags
                            tags = get_streamer_tags(channel_name, groups_data)
                            
                            twitch_streams.append({
                                "platform": "twitch",
                                "channel": channel_name,
                                "title": stream.get("title", "No Title"),
                                "viewers": stream.get("viewer_count", 0),
                                "thumbnail": thumb,
                                "tags": tags
                            })
                else:
                    logger.warning(f"Twitch Batch {i} failed: {response.status}")
                    
            await asyncio.sleep(0.1) 
    return twitch_streams

async def fetch_streams_loop():
    known_streamers = get_streamers_from_db()
    logger.info(f"Loaded {len(known_streamers)} streamers. Initializing Browser...")
    
    app_data = os.getenv("LOCALAPPDATA") or base_path
    profile_path = os.path.join(app_data, "KickScraperProfile")
    
    browser = await uc.start(
        user_data_dir=profile_path,
        headless=False, 
        browser_args=["--window-position=-32000,-32000"]
    )
    
    last_twitch_results = []
    twitch_counter = 5 

    try:
        while True:
            blacklist_data = load_json_safe("blacklist.json", {"titles": [], "channels": []})
            groups_data = load_json_safe("groups.json", {})
            
            title_blacklist = [str(t).lower() for t in blacklist_data.get("titles", [])]
            channel_blacklist = [str(c).lower() for c in blacklist_data.get("channels", [])]
            
            valid_twitch_streamers = [name for name in known_streamers if name.lower() not in channel_blacklist]

            current_cycle_kick = []
            #--- KICK Refresh ---
            try:
                logger.info("Refreshing Kick...")
                # 1. Cache Buster: Force Chrome to fetch a brand new page
                live_kick_url = f"{KICK_API_URL}&_t={int(time.time())}"
                page = await browser.get(live_kick_url)
                
                await page.sleep(4) 
                content = await page.evaluate("document.body.innerText")
                
                # 2. Stale DOM Protection: Ensure we didn't just read an error page or old tab
                if not content or "livestreams" not in content:
                    raise ValueError("Kick returned empty or invalid data this cycle.")

                data = json.loads(content)
                
                for s in data.get("data", {}).get("livestreams", []):
                    channel_name = s.get("channel", {}).get("slug", "Unknown")
                    channel_lower = channel_name.lower()
                    
                    if channel_lower in channel_blacklist:
                        continue

                    if s.get("category", {}).get("id") == 9818:
                        title = s.get("title", "").lower()
                        if any(term in title for term in title_blacklist):
                            continue
                        
                        tags = get_streamer_tags(channel_name, groups_data)

                        current_cycle_kick.append({
                            "platform": "kick",
                            "channel": channel_name,
                            "title": s.get("title", "No Title"),
                            "viewers": s.get("viewer_count", 0),
                            "thumbnail": s.get("thumbnail", {}).get("src", ""),
                            "tags": tags
                        })
            except Exception as e:
                logger.error(f"Kick Error: {e}")

            if twitch_counter >= 5:
                try:
                    logger.info("Running 5-min Twitch batch query...")
                    token = await get_twitch_token()
                    if token and valid_twitch_streamers:
                        last_twitch_results = await fetch_twitch_streams_by_name(
                            token, valid_twitch_streamers, title_blacklist, groups_data
                        )
                        logger.info(f"Twitch updated: {len(last_twitch_results)} live.")
                    twitch_counter = 0 
                except Exception as e:
                    logger.error(f"Twitch Error: {e}")
            
            twitch_counter += 1

            merged = current_cycle_kick + last_twitch_results
            merged.sort(key=lambda x: x["viewers"], reverse=True)
            
            stream_cache["streams"] = merged
            stream_cache["count"] = len(merged)
            stream_cache["status"] = "Live"
            
            # Use colors=True and wrap the message in <magenta> for purple output
            logger.opt(colors=True).info(f"Cache updated with <magenta>{len(merged)} streams.</magenta> Next Twitch in <magenta>{5 - (twitch_counter % 6)} min(s).</magenta>")
            
            await asyncio.sleep(60)
    finally:
        if browser:
            browser.stop()

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(fetch_streams_loop())
    yield
    task.cancel()
    await asyncio.sleep(1)

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/streams")
async def get_nopixel_streams():
    return stream_cache

#api for kick stream player -- used for controls

@app.get("/api/kick-playback/{username}")
def get_kick_playback(username: str):
    url = f"https://kick.com/api/v1/channels/{username}"
    try:
        # impersonate="chrome" perfectly fakes a browser fingerprint to bypass Cloudflare
        response = c_requests.get(url, impersonate="chrome")

        if response.status_code == 200:
            data = response.json()
            playback_url = data.get("playback_url")
            return {"url": playback_url}
        else:
            return {"error": f"Kick API blocked request. Status: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)