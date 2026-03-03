import json
import asyncio
import nodriver as uc
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

KICK_API_URL = "https://web.kick.com/api/v1/livestreams?limit=24&sort=viewer_count_desc&category_id=9818"

# Global variable to act as our ultra-fast memory cache
stream_cache = {
    "count": 0,
    "streams": [],
    "status": "Initializing... waiting for first data fetch."
}

async def fetch_streams_loop():
    """Background task that runs every 60 seconds to fetch fresh data."""
    while True:
        browser = None
        try:
            print("[Scraper] Spinning up browser to fetch fresh streams...")
            # Open headful to bypass WAF, but throw it off-screen so it doesn't annoy you
            browser = await uc.start(
                headless=False,
                browser_args=["--window-position=-32000,-32000"]
            )
            
            page = await browser.get(KICK_API_URL)
            await page.sleep(4) # Give Cloudflare Turnstile a moment
            
            content = await page.evaluate("document.body.innerText")
            data = json.loads(content)
            
            nested_data = data.get("data", {})
            streams = nested_data.get("livestreams", [])
            
            active_streams = []
            for stream in streams:
                channel_data = stream.get("channel", {})
                active_streams.append({
                    "channel": channel_data.get("slug", "Unknown"),
                    "title": stream.get("title", "No Title"),
                    "viewers": stream.get("viewer_count", 0),
                    "thumbnail": stream.get("thumbnail", {}).get("src", "")
                })
                
            active_streams.sort(key=lambda x: x["viewers"], reverse=True)
            
            # Update the global cache instantly
            stream_cache["count"] = len(active_streams)
            stream_cache["streams"] = active_streams
            stream_cache["status"] = "Live"
            print(f"[Scraper] Successfully updated cache with {len(active_streams)} streams. Sleeping for 60s.")
            
        except Exception as e:
            print(f"[Scraper] Error fetching streams: {e}")
            # We don't crash the server on error, we just try again in 60 seconds
            
        finally:
            if browser:
                browser.stop()
                
        # Wait exactly 60 seconds before looping again
        await asyncio.sleep(60)

# The lifespan context manager handles starting and stopping background tasks
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background loop when the server boots
    task = asyncio.create_task(fetch_streams_loop())
    yield
    # Cancel the loop when the server shuts down
    task.cancel()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Server is running! Go to /api/streams to see the live NoPixel channels."}

@app.get("/api/streams")
async def get_nopixel_streams():
    # The API endpoint now does ZERO scraping. It just returns the cache instantly.
    if stream_cache["status"] != "Live":
        raise HTTPException(status_code=503, detail="Data is currently initializing. Please try again in a few seconds.")
    return stream_cache

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)