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
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from loguru import logger
from curl_cffi import requests as c_requests
from curl_cffi.requests import AsyncSession

# ==========================================
# 1. LOGGING & SERVER SETUP
# ==========================================
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

stream_cache = {
    "nopixel": {"count": 0, "streams": [], "status": "Initializing..."},
    "prodigy": {"count": 0, "streams": [], "status": "Initializing..."}
}

SERVERS = [
    {"id": "nopixel", "url": "https://lofi-nopixel.com/multipov"},
    {"id": "prodigy", "url": "https://lofi-prodigy.com/multipov"}
]


# ==========================================
# 3. DATABASE & HELPER FUNCTIONS
# ==========================================
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
        pass 
        
    try:
        cursor.execute("ALTER TABLE metrics ADD COLUMN server TEXT DEFAULT 'nopixel'")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

init_metrics_db()

def get_streamers_from_db():
    try:
        db_path = os.path.join(base_path, "streamers.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT username, server FROM streamers")
            data = {row[0].lower(): row[1] for row in cursor.fetchall()}
        except sqlite3.OperationalError:
            cursor.execute("SELECT username FROM streamers")
            data = {row[0].lower(): "nopixel" for row in cursor.fetchall()}
        conn.close()
        return data
    except sqlite3.Error as e:
        logger.error(f"DB Error: {e}")
        return {}

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

def get_color_for_group(group_name):
    colors = ["#ff4a4a", "#53fc18", "#00a8ff", "#9146FF", "#ffcc00", "#ff00ff", "#00ffff", "#ff8800"]
    hash_val = sum(ord(c) for c in group_name)
    return colors[hash_val % len(colors)]

def chunk_list(data_list, chunk_size):
    for i in range(0, len(data_list), chunk_size):
        yield data_list[i:i + chunk_size]


# ==========================================
# 4. DEDUPLICATION (FUZZY MATCHING)
# ==========================================
def clean_username_for_matching(name):
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
    url = f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
    async with aiohttp.ClientSession() as session:
        async with session.post(url) as response:
            data = await response.json()
            return data.get("access_token")

async def fetch_twitch_streams_by_name(token, valid_streamers, title_blacklist, dynamic_tags, channel_allowlist):
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
                            tags = dynamic_tags.get(channel_name.lower(), [])
                            
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

async def fetch_lofi_data(session, target_url, channel_blacklist, tag_overrides):
    try:
        resp = await session.get(target_url, timeout=15)
        
        if resp.status_code != 200:
            return None, {}, set()
            
        html = resp.text
        handle_to_tags = {}
        base_handles = set() 
        
        for block in html.split('displayName:"')[1:]:
            group_matches = re.findall(r'group:\{id:"[^"]+",name:"([^"]+)"', block)
            unique_groups = list(set(group_matches))
            
            raw_tags = []
            for g in unique_groups:
                if g.lower() == "other": continue
                
                override = tag_overrides.get(g.lower(), {})
                color = override.get("color", get_color_for_group(g))
                priority = override.get("priority", 99) 
                display_label = override.get("label", g)
                
                raw_tags.append({
                    "label": display_label,
                    "rank": g,
                    "color": color,
                    "priority": priority
                })
                
            raw_tags.sort(key=lambda x: x["priority"])
            clean_tags = [{"label": t["label"], "rank": t["rank"], "color": t["color"]} for t in raw_tags]
            
            for h in re.findall(r'platformHandle:"([^"]+)"', block):
                handle_lower = h.lower()
                handle_to_tags[handle_lower] = clean_tags
                base_handles.add(handle_lower) 
                
        kick_streams = []
        seen_handles = set()
        
        for block in html.split('platform:"kick"')[1:]:
            handle_m = re.search(r'platformHandle:"([^"]+)"', block)
            if not handle_m: continue
            handle = handle_m.group(1).lower()
            
            if handle in channel_blacklist or handle in seen_handles:
                continue
                
            game_m = re.search(r'gameId:"([^"]+)"', block)
            if not game_m or game_m.group(1) != "8":
                continue
                
            seen_handles.add(handle)
            title_m = re.search(r'streamTitle:(null|"(?:\\.|[^"\\])*")', block)
            title = "No Title"
            if title_m and title_m.group(1) != "null":
                title = title_m.group(1)[1:-1].replace('\\"', '"').replace('\\\\', '\\')
                
            viewer_m = re.search(r'viewerCount:(\d+)', block)
            viewers = int(viewer_m.group(1)) if viewer_m else 0
            
            thumb_m = re.search(r'thumbnailUrl:(null|"(?:\\.|[^"\\])*")', block)
            thumb = ""
            if thumb_m and thumb_m.group(1) != "null":
                thumb = thumb_m.group(1)[1:-1].replace('\\"', '"').replace('\\\\', '\\')
            
            kick_streams.append({
                "platform": "kick",
                "channel": handle,
                "title": title,
                "viewers": viewers,
                "kick_viewers": viewers,
                "twitch_viewers": 0,
                "thumbnail": thumb,
                "tags": handle_to_tags.get(handle, [])
            })
            
        return kick_streams, handle_to_tags, base_handles
    except Exception as e:
        logger.error(f"Lofi scrape error: {e}")
        return None, {}, set()

async def fetch_hasroot_prodigy(session, channel_blacklist, title_blacklist):
    try:
        logger.info("Fetching Prodigy streams via HasRoot...")
        resp = await session.get("https://prodigyrp.hasroot.com/", timeout=15)
        
        if resp.status_code != 200:
            return []
            
        match = re.search(r'var ourData = (\{.*?\});\s*var JSON_TAGLIST', resp.text, re.DOTALL)
        if not match:
            return []
            
        data = json.loads(match.group(1))
        streams = []
        
        for handle, info in data.get("streams", {}).items():
            if info.get("gameID") != 1: continue
            
            channel_name = info.get("name", "").lower()
            if channel_name in channel_blacklist:
                continue
                
            title = info.get("status", "No Title").lower()
            if any(term in title for term in title_blacklist):
                continue
            
            streams.append({
                "platform": "twitch",
                "channel": info.get("name"),
                "title": info.get("status", "No Title"),
                "viewers": info.get("viewers", 0),
                "twitch_viewers": info.get("viewers", 0),
                "kick_viewers": 0,
                "thumbnail": f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{info.get('name')}-640x360.jpg",
                "tags": [] 
            })
        return streams
    except Exception as e:
        logger.error(f"HasRoot scrape error: {e}")
        return []

# ==========================================
# 6. MASTER LOOP
# ==========================================
async def fetch_streams_loop():
    known_streamers_dict = get_streamers_from_db()
    logger.info(f"Loaded {len(known_streamers_dict)} streamers. Starting scraper...")
    
    # We added the `last_hasroot` property to safely track DNS failures
    server_state = {
        "nopixel": {"last_twitch": datetime.min.replace(tzinfo=timezone.utc), "last_kick": datetime.min.replace(tzinfo=timezone.utc), "last_hasroot": datetime.min.replace(tzinfo=timezone.utc), "kick_cache": [], "twitch_cache": [], "hasroot_cache": [], "dynamic_tags": {}, "base_handles": set()},
        "prodigy": {"last_twitch": datetime.min.replace(tzinfo=timezone.utc), "last_kick": datetime.min.replace(tzinfo=timezone.utc), "last_hasroot": datetime.min.replace(tzinfo=timezone.utc), "kick_cache": [], "twitch_cache": [], "hasroot_cache": [], "dynamic_tags": {}, "base_handles": set()}
    }

    async with AsyncSession(impersonate="chrome116") as session:
        while True:
            now = datetime.now(timezone.utc)
            
            # Load standard lists
            blacklist_data = load_json_safe("blacklist.json", {"titles": [], "channels": []})
            allowlist_data = load_json_safe("allowlist.json", {"channels": []})
            
            # Load tag overrides
            raw_overrides = load_json_safe("tag_overrides.json", {})
            tag_overrides = {k.lower(): v for k, v in raw_overrides.items()}
            
            # Load the new HARD SERVER OVERRIDES
            raw_server_overrides = load_json_safe("server_overrides.json", {})
            server_overrides = {k.lower(): str(v).lower() for k, v in raw_server_overrides.items()}
            
            title_blacklist = [str(t).lower() for t in blacklist_data.get("titles", [])]
            channel_blacklist = [str(c).lower() for c in blacklist_data.get("channels", [])]
            channel_allowlist = [str(c).lower() for c in allowlist_data.get("channels", [])]
            
            valid_twitch_streamers = [name for name in known_streamers_dict.keys() if name not in channel_blacklist]

            for server in SERVERS:
                server_id = server["id"]
                target_url = server["url"]
                state = server_state[server_id]

                # --- HASROOT, KICK & TAGS Refresh ---
                if server_id == "prodigy":
                    hasroot_streams = await fetch_hasroot_prodigy(session, channel_blacklist, title_blacklist)
                    
                    # Apply 10-Minute Grace Period logic to HasRoot
                    if hasroot_streams:
                        state["hasroot_cache"] = hasroot_streams
                        state["last_hasroot"] = now
                    else:
                        if (now - state["last_hasroot"]).total_seconds() > 600:
                            logger.warning(f"HasRoot API unreachable for 10 mins on {server_id}. Clearing stale cache.")
                            state["hasroot_cache"] = []
                        else:
                            logger.warning(f"HasRoot scrape failed on {server_id}. Falling back to cached data.")
                
                lofi_kick_results, dynamic_tags, base_handles = await fetch_lofi_data(session, target_url, channel_blacklist, tag_overrides)
                
                if lofi_kick_results is not None:
                    current_cycle_kick = []
                    for s in lofi_kick_results:
                        if not any(term in s["title"].lower() for term in title_blacklist):
                            current_cycle_kick.append(s)
                    
                    state["kick_cache"] = current_cycle_kick
                    state["dynamic_tags"] = dynamic_tags 
                    state["base_handles"] = base_handles 
                    state["last_kick"] = now
                else:
                    if (now - state["last_kick"]).total_seconds() > 600:
                        logger.warning(f"Kick API unreachable on {server_id}. Clearing stale Kick cache.")
                        state["kick_cache"] = []
                    current_cycle_kick = state["kick_cache"]

                # --- TWITCH Refresh ---
                if server_id == "nopixel": 
                    if (now - state["last_twitch"]).total_seconds() >= 300:
                        try:
                            logger.info("Running 5-min Twitch batch query...")
                            token = await get_twitch_token()
                            if token and valid_twitch_streamers:
                                
                                combined_tags = {**server_state["nopixel"].get("dynamic_tags", {}), **server_state["prodigy"].get("dynamic_tags", {})}
                                
                                fresh_twitch = await fetch_twitch_streams_by_name(
                                    token, valid_twitch_streamers, title_blacklist, combined_tags, channel_allowlist
                                )
                                
                                nopixel_twitch = []
                                prodigy_twitch = []
                                
                                np_keywords = ["nopixel", "nopixel rp", "nopixelrp", "nopixel 4.0", "nopixel rp 4.0"]
                                prod_keywords = ["prodigy", "prodigy rp", "prodigy rp 4.0", "prodigy 4.0", "prod 4.0", "prod rp"]
                                
                                prodigy_roster = server_state["prodigy"]["base_handles"]
                                
                                for stream in fresh_twitch:
                                    raw_title = stream["title"].lower()
                                    channel = stream["channel"].lower()
                                    
                                    clean_title = re.sub(r'[^a-z0-9\s]', ' ', raw_title)
                                    
                                    forced_server = server_overrides.get(channel)
                                    is_prodigy = any(kw in clean_title for kw in prod_keywords) or re.search(r'\bprod\b', clean_title)
                                    is_nopixel = any(kw in clean_title for kw in np_keywords)
                                    db_server = known_streamers_dict.get(channel, "nopixel")
                                    
                                    # PRIORITY 0: Hard Server Override
                                    if forced_server == "prodigy":
                                        prodigy_twitch.append(stream)
                                    elif forced_server == "nopixel":
                                        nopixel_twitch.append(stream)
                                    # Priority 1: Title Keywords
                                    elif is_prodigy:
                                        prodigy_twitch.append(stream)
                                    elif is_nopixel:
                                        nopixel_twitch.append(stream)
                                    # Priority 2: Roster Fallback 
                                    elif channel in prodigy_roster or db_server == "prodigy":
                                        prodigy_twitch.append(stream)
                                    else:
                                        # Priority 3: Default Catch-all 
                                        nopixel_twitch.append(stream)
                                        
                                logger.info(f"Twitch sorted: {len(nopixel_twitch)} NoPixel, {len(prodigy_twitch)} Prodigy.")
                                
                                server_state["nopixel"]["twitch_cache"] = nopixel_twitch
                                server_state["prodigy"]["twitch_cache"] = prodigy_twitch
                                
                            server_state["nopixel"]["last_twitch"] = now
                            server_state["prodigy"]["last_twitch"] = now
                        except Exception as e:
                            logger.error(f"Twitch Error: {e}")
                            if (now - state["last_twitch"]).total_seconds() > 600:
                                server_state["nopixel"]["twitch_cache"] = []
                                server_state["prodigy"]["twitch_cache"] = []

                # --- Merge, Deduplicate & Sort ---
                raw_merged = current_cycle_kick + state["twitch_cache"]
                
                # Strip out any Kick streamers that were forced to the other server
                raw_merged = [s for s in raw_merged if server_overrides.get(s["channel"].lower(), server_id) == server_id]
                
                if server_id == "prodigy":
                    for hr_stream in state.get("hasroot_cache", []):
                        chan = hr_stream["channel"].lower()
                        # Apply forced override filtering to HasRoot too
                        if server_overrides.get(chan, "prodigy") != "prodigy":
                            continue
                        hr_stream["tags"] = state["dynamic_tags"].get(chan, [])
                        raw_merged.append(hr_stream)

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
                        
                        if not matched_existing.get("tags") and stream.get("tags"):
                            matched_existing["tags"] = stream.get("tags")
                    else:
                        deduped_streams.append(stream.copy())

                merged = deduped_streams
                merged.sort(key=lambda x: x["viewers"], reverse=True)
                
                stream_cache[server_id]["streams"] = merged
                stream_cache[server_id]["count"] = len(merged)
                stream_cache[server_id]["status"] = "Live"
                
                total_viewers = sum(s.get("viewers", 0) for s in merged)
                tw_viewers = sum(s.get("viewers", 0) for s in merged if s.get("platform") == "twitch")
                kk_viewers = sum(s.get("viewers", 0) for s in merged if s.get("platform") == "kick")
                
                try:
                    metrics_db_path = os.path.join(base_path, "metrics.db")
                    conn = sqlite3.connect(metrics_db_path)
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO metrics (server, total_viewers, total_streamers, twitch_viewers, kick_viewers) VALUES (?, ?, ?, ?, ?)", 
                        (server_id, total_viewers, len(merged), tw_viewers, kk_viewers)
                    )
                    conn.commit()
                    conn.close()
                except Exception as e:
                    pass
                
                seconds_since_twitch = (datetime.now(timezone.utc) - server_state["nopixel"]["last_twitch"]).total_seconds()
                mins_until_twitch = max(0, int((300 - seconds_since_twitch) // 60))
                
                logger.opt(colors=True).info(f"[{server_id.upper()}] Cache updated: <magenta>{len(merged)} streams</magenta> | <green>{total_viewers} viewers</green>. Next Twitch in <magenta>{mins_until_twitch} min(s).</magenta>")
            
            await asyncio.sleep(60)


# ==========================================
# 7. FASTAPI WEB SERVER
# ==========================================
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
async def get_nopixel_streams(server: str = "nopixel"):
    if server in stream_cache:
        return stream_cache[server]
    return stream_cache["nopixel"]

@app.get("/api/metrics")
def get_metrics(timeframe: str = "1h", server: str = "nopixel"):
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
        cursor.execute("SELECT timestamp, total_viewers, total_streamers, twitch_viewers, kick_viewers FROM metrics WHERE timestamp >= ? AND server = ? ORDER BY timestamp ASC", (delta.strftime('%Y-%m-%d %H:%M:%S'), server))
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

@app.get("/api/tags")
def get_tags():
    return load_json_safe("tag_overrides.json", {})

@app.post("/api/tags")
async def update_tags(request: Request):
    try:
        data = await request.json()
        filepath = os.path.join(base_path, "tag_overrides.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/overrides")
def get_overrides():
    return load_json_safe("server_overrides.json", {})

@app.post("/api/overrides")
async def update_overrides(request: Request):
    try:
        data = await request.json()
        filepath = os.path.join(base_path, "server_overrides.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/kick-playback/{username}")
def get_kick_playback(username: str):
    url = f"https://kick.com/api/v1/channels/{username}"
    try:
        response = c_requests.get(url, impersonate="chrome")
        if response.status_code == 200:
            data = response.json()
            return {"url": data.get("playback_url")}
        else:
            return {"error": f"Kick API blocked request."}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)