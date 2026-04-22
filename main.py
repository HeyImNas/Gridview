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

# ==========================================
# 1. LOGGING & SERVER SETUP
# ==========================================
# We use Loguru for pretty terminal outputs and intercept standard Uvicorn logs
logger.remove()
logger.level("INFO", color="<yellow>")
logger.add(
    sys.stdout, 
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <2}</level> | {message}",
    level="INFO" 
)

class InterceptHandler(logging.Handler):
    """Intercepts standard Python logging and routes it to Loguru."""
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
        
        # Silence harmless socket disconnect errors from Windows
        if "WinError 10054" in message or "An existing connection was forcibly closed" in message:
            return 

        # Colorize the 200 OK status codes for easier reading
        if record.name == "uvicorn.access" and "/api/streams" in message and message.endswith(" 200"):
            message = message[:-4] + " <green>200</green>"

        logger.opt(depth=depth, exception=record.exc_info, colors=True).log(level, message)

# Apply the custom logger
logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)
for name in ["uvicorn", "uvicorn.error", "uvicorn.access", "asyncio"]:
    logger_instance = logging.getLogger(name)
    logger_instance.handlers = [InterceptHandler()]
    logger_instance.propagate = False


# ==========================================
# 2. CONFIGURATION & STATE
# ==========================================
base_path = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base_path, ".env")
load_dotenv(dotenv_path=env_path)

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
    logger.critical(f"Credentials missing! Checked path: {env_path}")

# This dictionary holds the live data in memory so FastAPI can serve it instantly
stream_cache = {
    "count": 0,
    "streams": [],
    "status": "Initializing..."
}


# ==========================================
# 3. DATABASE & HELPER FUNCTIONS
# ==========================================
def init_metrics_db():
    """Initializes the SQLite database used to track historical viewership metrics."""
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
    # Safely try to add new columns if upgrading from an older DB version
    try:
        cursor.execute("ALTER TABLE metrics ADD COLUMN twitch_viewers INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE metrics ADD COLUMN kick_viewers INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass 

    conn.commit()
    conn.close()

init_metrics_db()

def get_streamers_from_db():
    """Loads the master list of known NoPixel streamers to check on Twitch."""
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
    """Safely loads JSON config files (like groups.json), returning defaults if missing."""
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
    """Scans groups.json to see if a streamer belongs to any factions (e.g., LSPD, CG)."""
    tags = []
    channel_lower = channel_name.lower()
    for tag_label, info in groups_data.items():
        for member_key, member_data in info.get("members", {}).items():
            platforms = member_data.get("platforms", {})
            kick_handle = platforms.get("kick", "").rstrip('/').split('/')[-1].lower()
            twitch_handle = platforms.get("twitch", "").rstrip('/').split('/')[-1].lower()
            
            # Check if the channel name matches their JSON key or their platform URLs
            if channel_lower == member_key.lower() or channel_lower == kick_handle or channel_lower == twitch_handle:
                tags.append({
                    "label": tag_label,
                    "rank": info.get("full_name", tag_label),
                    "color": info.get("color", "#888888")
                })
                break 
    return tags

def chunk_list(data_list, chunk_size):
    """Splits a large list into smaller chunks (used for Twitch API limits)."""
    for i in range(0, len(data_list), chunk_size):
        yield data_list[i:i + chunk_size]


# ==========================================
# 4. DEDUPLICATION (FUZZY MATCHING)
# ==========================================
def clean_username_for_matching(name):
    """Strips special characters and common prefixes/suffixes (like 'ttv') for accurate comparisons."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9]', '', name)
    if name.endswith('ttv') and len(name) > 3:
        name = name[:-3]
    elif name.endswith('tv') and len(name) > 2:
        name = name[:-2]
    elif name.startswith('not'):
        name = name[3:] 
    return name

def is_similar_username(name1, name2, threshold=0.85):
    """Checks if two usernames are highly similar to merge multi-streamers into one card."""
    clean1 = clean_username_for_matching(name1)
    clean2 = clean_username_for_matching(name2)
    if clean1 == clean2:
        return True
    ratio = difflib.SequenceMatcher(None, clean1, clean2).ratio()
    return ratio >= threshold


# ==========================================
# 5. SCRAPING ENGINES
# ==========================================
async def get_twitch_token():
    """Generates an OAuth token for the Twitch API."""
    url = f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
    async with aiohttp.ClientSession() as session:
        async with session.post(url) as response:
            data = await response.json()
            return data.get("access_token")

async def fetch_twitch_streams_by_name(token, valid_streamers, title_blacklist, groups_data, channel_allowlist):
    """Queries the Twitch API in batches of 100 to find live streamers."""
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
                        
                        # Only accept GTA V streams (ID: 32982) OR manually whitelisted channels
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
                
            await asyncio.sleep(0.1) # Be polite to the API
    return twitch_streams

async def fetch_kick_streams_from_lofi(session, groups_data, channel_blacklist):
    """Extracts Kick streams directly from Lofi-Nopixel's internal SvelteKit JSON data."""
    try:
        logger.info("Fetching Kick streams via Lofi-Nopixel bypass...")
        resp = await session.get("https://lofi-nopixel.com/multipov", timeout=15)
        
        if resp.status_code != 200:
            logger.warning(f"Lofi-Nopixel blocked/failed. Status: {resp.status_code}")
            return None
            
        html = resp.text
        kick_streams = []
        seen_handles = set()
        
        # Split the raw HTML code by Kick platform tags to isolate streamer objects
        blocks = html.split('platform:"kick"')
        
        for block in blocks[1:]:
            # 1. Extract Handle
            handle_m = re.search(r'platformHandle:"([^"]+)"', block)
            if not handle_m: continue
            handle = handle_m.group(1).lower()
            
            if handle in channel_blacklist or handle in seen_handles:
                continue
                
            # 2. STRICT CATEGORY FILTER (Kick Game ID for GTA V is "8")
            game_m = re.search(r'gameId:"([^"]+)"', block)
            game_id = game_m.group(1) if game_m else ""
            
            # If they switched to Just Chatting or Slots, drop them from the directory
            if game_id != "8":
                continue
                
            seen_handles.add(handle)
            
            # 3. Extract Title (Handles escaped internal quotes)
            title_m = re.search(r'streamTitle:(null|"(?:\\.|[^"\\])*")', block)
            title = "No Title"
            if title_m and title_m.group(1) != "null":
                title = title_m.group(1)[1:-1].replace('\\"', '"').replace('\\\\', '\\')
                
            # 4. Extract Viewers
            viewer_m = re.search(r'viewerCount:(\d+)', block)
            viewers = int(viewer_m.group(1)) if viewer_m else 0
            
            # 5. Extract High-Res Thumbnail
            thumb_m = re.search(r'thumbnailUrl:(null|"(?:\\.|[^"\\])*")', block)
            thumb = ""
            if thumb_m and thumb_m.group(1) != "null":
                thumb = thumb_m.group(1)[1:-1].replace('\\"', '"').replace('\\\\', '\\')
                
            tags = get_streamer_tags(handle, groups_data)
            
            kick_streams.append({
                "platform": "kick",
                "channel": handle,
                "title": title,
                "viewers": viewers,
                "kick_viewers": viewers,
                "twitch_viewers": 0,
                "thumbnail": thumb,
                "tags": tags
            })
            
        return kick_streams
        
    except Exception as e:
        logger.error(f"Lofi-Nopixel scrape error: {e}")
        return None


# ==========================================
# 6. MASTER LOOP
# ==========================================
async def fetch_streams_loop():
    """Infinite background loop that continuously feeds the cache with fresh data."""
    known_streamers = get_streamers_from_db()
    logger.info(f"Loaded {len(known_streamers)} streamers. Starting scraper...")
    
    last_twitch_results = []
    last_kick_results = [] 
    twitch_counter = 5 # Start at 5 to trigger Twitch immediately on boot

    # We use an impersonating session to beat Cloudflare on scraping targets
    async with AsyncSession(impersonate="chrome116") as session:
        while True:
            # Reload JSON configs dynamically so you don't have to restart the server when updating groups
            blacklist_data = load_json_safe("blacklist.json", {"titles": [], "channels": []})
            allowlist_data = load_json_safe("allowlist.json", {"channels": []})
            groups_data = load_json_safe("groups.json", {})
            
            title_blacklist = [str(t).lower() for t in blacklist_data.get("titles", [])]
            channel_blacklist = [str(c).lower() for c in blacklist_data.get("channels", [])]
            channel_allowlist = [str(c).lower() for c in allowlist_data.get("channels", [])]
            
            valid_twitch_streamers = [name for name in known_streamers if name.lower() not in channel_blacklist]

            # --- KICK Refresh (Runs every 1 minute) ---
            lofi_kick_results = await fetch_kick_streams_from_lofi(session, groups_data, channel_blacklist)
            
            if lofi_kick_results is not None:
                current_cycle_kick = []
                for s in lofi_kick_results:
                    # Enforce title blacklist (e.g., blocking other RP servers)
                    if not any(term in s["title"].lower() for term in title_blacklist):
                        current_cycle_kick.append(s)
                
                last_kick_results = current_cycle_kick # Save to cache
            else:
                logger.warning("Kick scrape failed this cycle. Falling back to cached Kick data.")
                current_cycle_kick = last_kick_results

            # --- TWITCH Refresh (Runs every 5 minutes to save API quota) ---
            if twitch_counter >= 5:
                try:
                    logger.info("Running 5-min Twitch batch query...")
                    token = await get_twitch_token()
                    if token and valid_twitch_streamers:
                        last_twitch_results = await fetch_twitch_streams_by_name(
                            token, valid_twitch_streamers, title_blacklist, groups_data, channel_allowlist
                        )
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
                
                # Check if this streamer is already in the deduped list (Multi-streaming)
                for existing in deduped_streams:
                    if is_similar_username(channel, existing["channel"]):
                        matched_existing = existing
                        break
                
                if matched_existing:
                    # Combine viewer counts for multi-streamers
                    matched_existing["viewers"] += stream.get("viewers", 0)
                    matched_existing["twitch_viewers"] += stream.get("twitch_viewers", 0)
                    matched_existing["kick_viewers"] += stream.get("kick_viewers", 0)
                else:
                    # Append a copy to prevent mutating the cached arrays
                    deduped_streams.append(stream.copy())

            # Sort the final list by highest viewers first
            merged = deduped_streams
            merged.sort(key=lambda x: x["viewers"], reverse=True)
            
            # Commit to cache
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
            
            # Wait 60 seconds before looping again
            await asyncio.sleep(60)


# ==========================================
# 7. FASTAPI WEB SERVER
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the background loop's lifecycle so it starts/stops cleanly with the server."""
    task = asyncio.create_task(fetch_streams_loop())
    yield
    task.cancel()
    await asyncio.sleep(1)

app = FastAPI(lifespan=lifespan)

# Allow the frontend application to pull data from this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/streams")
async def get_nopixel_streams():
    """Endpoint: Returns the current live directory data."""
    return stream_cache

@app.get("/api/metrics")
def get_metrics(timeframe: str = "1h"):
    """Endpoint: Returns historical viewership data for charts."""
    db_path = os.path.join(base_path, "metrics.db")
    
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
    """Endpoint: Helper route to get the raw .m3u8 video URL for a Kick streamer."""
    url = f"https://kick.com/api/v1/channels/{username}"
    try:
        # Use curl_cffi to bypass Cloudflare on the Kick channel API
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
    # Start the local server
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)