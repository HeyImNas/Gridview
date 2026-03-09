import json
import asyncio
import aiohttp
import sqlite3
import os
import sys
import logging
import difflib
import re
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from loguru import logger
from curl_cffi import requests as c_requests
from curl_cffi.requests import AsyncSession

# --- LOGGING SETUP ---
logger.remove()
logger.level("INFO", color="<yellow>")
logger.add(
    sys.stdout, 
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <2}</level> | {message}",
    level="INFO" 
)

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
        
        # Silence the harmless Windows 10054 socket error
        if "WinError 10054" in message or "An existing connection was forcibly closed" in message:
            return 

        if record.name == "uvicorn.access" and "/api/streams" in message and message.endswith(" 200"):
            message = message[:-4] + " <green>200</green>"

        logger.opt(depth=depth, exception=record.exc_info, colors=True).log(level, message)

logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)
for name in ["uvicorn", "uvicorn.error", "uvicorn.access", "asyncio"]:
    logger_instance = logging.getLogger(name)
    logger_instance.handlers = [InterceptHandler()]
    logger_instance.propagate = False


# --- CONFIGURATION ---
KICK_API_URL = "https://web.kick.com/api/v1/livestreams?limit=100&sort=viewer_count_desc&category_id=9818"
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

# --- DATABASE & HELPERS ---
def init_metrics_db():
    db_path = os.path.join(base_path, "metrics.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_viewers INTEGER,
            total_streamers INTEGER
        )
    """)
    try:
        cursor.execute("ALTER TABLE metrics ADD COLUMN twitch_viewers INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE metrics ADD COLUMN kick_viewers INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Columns already exist

    conn.commit()
    conn.close()

init_metrics_db()

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
    tags = []
    channel_lower = channel_name.lower()
    for tag_label, info in groups_data.items():
        members_dict = info.get("members", {})
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

# --- FUZZY MATCHING (DEDUPLICATION) ---
def clean_username_for_matching(name):
    name = name.lower()
    name = re.sub(r'[^a-z0-9]', '', name)
    if name.endswith('ttv') and len(name) > 3:
        name = name[:-3]
    elif name.endswith('tv') and len(name) > 2:
        name = name[:-2]
    return name

def is_similar_username(name1, name2, threshold=0.85):
    clean1 = clean_username_for_matching(name1)
    clean2 = clean_username_for_matching(name2)
    if clean1 == clean2:
        return True
    ratio = difflib.SequenceMatcher(None, clean1, clean2).ratio()
    return ratio >= threshold

# --- SCRAPERS ---
async def get_twitch_token():
    url = f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
    async with aiohttp.ClientSession() as session:
        async with session.post(url) as response:
            data = await response.json()
            return data.get("access_token")

async def fetch_twitch_streams_by_name(token, valid_streamers, title_blacklist, groups_data, channel_allowlist):
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
                        channel_name = stream.get("user_login")
                        
                        is_gta = stream.get("game_id") == "32982"
                        is_allowed = channel_name.lower() in channel_allowlist
                        
                        if is_gta or is_allowed: 
                            title = stream.get("title", "").lower()
                            if any(term in title for term in title_blacklist):
                                continue 
                                
                            thumb = stream.get("thumbnail_url", "").replace("{width}", "640").replace("{height}", "360")
                            tags = get_streamer_tags(channel_name, groups_data)
                            
                            twitch_streams.append({
                                "platform": "twitch",
                                "channel": channel_name,
                                "title": stream.get("title", "No Title"),
                                "viewers": stream.get("viewer_count", 0),
                                "twitch_viewers": stream.get("viewer_count", 0),
                                "kick_viewers": 0,
                                "thumbnail": thumb,
                                "tags": tags
                            })
                else:
                    logger.warning(f"Twitch Batch {i} failed: {response.status}")
                
            await asyncio.sleep(0.1) 
    return twitch_streams

async def fetch_streams_loop():
    known_streamers = get_streamers_from_db()
    logger.info(f"Loaded {len(known_streamers)} streamers. Starting silent scraper...")
    
    last_twitch_results = []
    twitch_counter = 5 

    while True:
        blacklist_data = load_json_safe("blacklist.json", {"titles": [], "channels": []})
        allowlist_data = load_json_safe("allowlist.json", {"channels": []})
        groups_data = load_json_safe("groups.json", {})
        
        title_blacklist = [str(t).lower() for t in blacklist_data.get("titles", [])]
        channel_blacklist = [str(c).lower() for c in blacklist_data.get("channels", [])]
        channel_allowlist = [str(c).lower() for c in allowlist_data.get("channels", [])]
        
        valid_twitch_streamers = [name for name in known_streamers if name.lower() not in channel_blacklist]

        current_cycle_kick = []
        
        # --- KICK Refresh (Using curl_cffi to bypass Cloudflare) ---
        try:
            logger.info("Refreshing Kick...")
            async with AsyncSession(impersonate="chrome") as session:
                
                # 1. Main Category Scrape
                live_kick_url = f"{KICK_API_URL}&_t={int(time.time())}"
                resp = await session.get(live_kick_url)
                
                if resp.status_code == 200:
                    data = resp.json()
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
                                "kick_viewers": s.get("viewer_count", 0),
                                "twitch_viewers": 0,
                                "thumbnail": s.get("thumbnail", {}).get("src", ""),
                                "tags": tags
                            })
                else:
                    logger.warning(f"Kick Category API blocked. Status: {resp.status_code}")

                # 2. Allowlist Check
                if channel_allowlist:
                    for allowed_user in channel_allowlist:
                        if any(s["channel"].lower() == allowed_user for s in current_cycle_kick):
                            continue
                        
                        try:
                            resp = await session.get(f"https://kick.com/api/v1/channels/{allowed_user}")
                            if resp.status_code == 200:
                                user_data = resp.json()
                                livestream = user_data.get("livestream")
                                
                                if livestream:
                                    title = livestream.get("session_title", "").lower()
                                    if any(term in title for term in title_blacklist):
                                        continue
                                    
                                    tags = get_streamer_tags(allowed_user, groups_data)
                                    current_cycle_kick.append({
                                        "platform": "kick",
                                        "channel": allowed_user,
                                        "title": livestream.get("session_title", "No Title"),
                                        "viewers": livestream.get("viewer_count", 0),
                                        "kick_viewers": livestream.get("viewer_count", 0),
                                        "twitch_viewers": 0,
                                        "thumbnail": livestream.get("thumbnail", {}).get("url", ""),
                                        "tags": tags
                                    })
                            await asyncio.sleep(0.5) 
                        except Exception:
                            pass 
        except Exception as e:
            logger.error(f"Kick Scrape Error: {e}")

        # --- TWITCH Refresh ---
        if twitch_counter >= 5:
            try:
                logger.info("Running 5-min Twitch batch query...")
                token = await get_twitch_token()
                if token and valid_twitch_streamers:
                    last_twitch_results = await fetch_twitch_streams_by_name(
                        token, valid_twitch_streamers, title_blacklist, groups_data, channel_allowlist
                    )
                    logger.info(f"Twitch updated: {len(last_twitch_results)} live.")
                twitch_counter = 0 
            except Exception as e:
                logger.error(f"Twitch Error: {e}")
        
        twitch_counter += 1

        # --- Merge, Deduplicate & Sort ---
        raw_merged = current_cycle_kick + last_twitch_results
        deduped_streams = []
        
        for stream in raw_merged:
            channel = stream["channel"]
            matched_existing = None
            
            for existing in deduped_streams:
                if is_similar_username(channel, existing["channel"]):
                    matched_existing = existing
                    break
            
            if matched_existing:
                matched_existing["viewers"] += stream.get("viewers", 0)
                matched_existing["twitch_viewers"] += stream.get("twitch_viewers", 0)
                matched_existing["kick_viewers"] += stream.get("kick_viewers", 0)
            else:
                deduped_streams.append(stream)

        merged = deduped_streams
        merged.sort(key=lambda x: x["viewers"], reverse=True)
        
        stream_cache["streams"] = merged
        stream_cache["count"] = len(merged)
        stream_cache["status"] = "Live"
        
        # --- LOG METRICS TO DB ---
        total_viewers = sum(s.get("viewers", 0) for s in merged)
        tw_viewers = sum(s.get("viewers", 0) for s in merged if s.get("platform") == "twitch")
        kk_viewers = sum(s.get("viewers", 0) for s in merged if s.get("platform") == "kick")
        
        try:
            metrics_db_path = os.path.join(base_path, "metrics.db")
            conn = sqlite3.connect(metrics_db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO metrics (total_viewers, total_streamers, twitch_viewers, kick_viewers) VALUES (?, ?, ?, ?)", 
                (total_viewers, len(merged), tw_viewers, kk_viewers)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Metrics DB Error: {e}")
        
        logger.opt(colors=True).info(f"Cache updated: <magenta>{len(merged)} streams</magenta> | <green>{total_viewers} viewers</green>. Next Twitch in <magenta>{5 - (twitch_counter % 6)} min(s).</magenta>")
        
        await asyncio.sleep(60)

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

@app.get("/api/metrics")
def get_metrics(timeframe: str = "1h"):
    db_path = os.path.join(base_path, "metrics.db")
    
    # Updated timezone implementation to remove deprecation warning
    now = datetime.now(timezone.utc)
    if timeframe == "1h": delta = now - timedelta(hours=1)
    elif timeframe == "12h": delta = now - timedelta(hours=12)
    elif timeframe == "1d": delta = now - timedelta(days=1)
    elif timeframe == "7d": delta = now - timedelta(days=7)
    elif timeframe == "1m": delta = now - timedelta(days=30)
    else: delta = now - timedelta(hours=1)
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, total_viewers, total_streamers, twitch_viewers, kick_viewers FROM metrics WHERE timestamp >= ? ORDER BY timestamp ASC", (delta.strftime('%Y-%m-%d %H:%M:%S'),))
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "timestamps": [row[0] for row in rows], 
            "viewers": [row[1] for row in rows], 
            "streamers": [row[2] for row in rows],
            "twitch_viewers": [row[3] for row in rows],
            "kick_viewers": [row[4] for row in rows]
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/kick-playback/{username}")
def get_kick_playback(username: str):
    url = f"https://kick.com/api/v1/channels/{username}"
    try:
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