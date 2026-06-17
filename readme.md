# 🟢 GTA RP Stream Directory & Multi-Viewer (NoPixel & Prodigy)

A high-performance, dual-server local web dashboard designed to track, filter, and watch GTA V RP streams seamlessly across both Twitch and Kick. Built with a Python FastAPI backend, a dependency-free Vanilla JS frontend, and powered by a hybrid scraping engine. This project is intended for personal use, however, if anyone else wants to access it you're more than welcome to it.

## 🚀 Features

### 📺 Smart Dual-Server Directory

* **Multi-Server Tracking:** Instantly toggle between active directories for **NoPixel** and **Prodigy RP**.
* **Hybrid Scraping Engine:** Aggregates live data using the official Twitch API alongside advanced third-party scrapes (HasRoot for deep Twitch discovery, and Lofi for Kick streams + dynamic faction tags). Bypasses Cloudflare protections natively.
* **Strict Title Parsing & Fallbacks:** Intelligently sorts streamers into their correct server directory by scanning live titles for keywords, referencing a historic database, or relying on their source origin.
* **Custom Layouts:** Drag-and-drop stream cards to reorganize your grid. Layouts are automatically saved to your browser's `localStorage`.
* **Smart Thumbnail Caching:** Uses a 2-minute "Time Bucket" to natively refresh stream thumbnails smoothly without causing DOM thrashing, flickering, or broken placeholder images.

### 🛠️ Built-in Live Editors

* **Tag Customization Modal:** Edit faction tags, colors, display labels, and sorting priorities directly from the browser UI. Saves instantly to your backend.
* **Server Override Modal:** A "Priority 0" editor that allows you to permanently pin a streamer to a specific server directory, completely bypassing title scanners and database logic.
* **Historical Viewership Metrics:** A sleek, interactive `Chart.js` modal that visualizes total viewers, total streamers, and platform splits (Twitch vs. Kick) over 1H, 12H, 1D, 7D, or 1M timeframes, backed by an SQLite database.

### 🎭 Advanced Multi-Stream Viewer

* **Smart Input Detection:** Paste a full URL (`kick.com/user` or `twitch.tv/user`) or just type a username. The system automatically cross-references the live cache to determine the correct platform.
* **Dynamic Grid:** Add or remove streams on the fly. The CSS grid automatically mathematically recalculates to fill the screen perfectly (e.g., 1 stream, 2 side-by-side, 4 in a grid, etc.).
* **Active View "Quick Add":** Add new streamers directly into an active multi-view session without having to stop and rebuild the layout.
* **Hover Overlays:** Clean, hover-activated overlay controls on every video frame to instantly **Refresh** a frozen stream or **Close** a player.
* **Integrated Chat:** A side-panel chat system with tabs to easily switch between the chatrooms of the streamers you are currently watching.
* **Theater Mode:** A single button click hides the top navigation tabs, header, and search bar, expanding the video grid to 100% of the viewport.

### 📑 Fast Navigation

* Integrated iframes for external tools (Events, Recaps, Clips, Groups).
* Press the **`** (backtick) key to quickly cycle through all dashboard tabs without clicking.
* `CTRL+F` instantly brings you back to the Streams tab and focuses the search bar.

---

## 🛠️ Tech Stack

* **Frontend:** HTML5, CSS3, Vanilla JavaScript, Chart.js. (No React/Vue overhead).
* **Grid Library:** `SortableJS` (for drag-and-drop stream cards).
* **Backend:** Python 3, FastAPI, `aiohttp` (async requests), `curl_cffi` (impersonation requests for anti-bot bypass).
* **Database:** SQLite3 (`streamers.db`, `metrics.db`).
* **Logging:** `Loguru` for clean, colorized terminal output.

---

## 📁 Project Structure & Data Files

* **`index.html`**: The complete frontend dashboard. Contains all the UI, CSS, and Vanilla JavaScript logic for the grid, tabs, modals, and multi-viewer.
* **`main.py`**: The Python FastAPI backend. Handles scraping, API requests, data aggregation, database commits, and serves the formatted JSON to the frontend.
* **`streamers.db`**: The master SQLite database containing known streamer handles and their default designated server.
* **`metrics.db`**: The SQLite database tracking historical viewership data across both servers.
* **`tag_overrides.json`**: Dynamically updated by the UI to store custom faction colors and labels.
* **`server_overrides.json`**: Dynamically updated by the UI to force streamers into specific directories.
* **`blacklist.json` / `allowlist.json**`: Configuration files to filter out unwanted stream titles/channels or force-allow specific non-GTA categories.
* **`.env`**: The environment configuration file used by the Python backend to securely store private API keys.

---

## ⚙️ Installation & Usage

1. **Set Up Your Environment:**
Create a file named `.env` in the root directory of your project (in the same folder as `main.py`). Paste your API credentials inside.
**`.env` Template:**
```env
# Twitch API Credentials (Required for fetching live Twitch status)
TWITCH_CLIENT_ID="your_twitch_client_id_here"
TWITCH_CLIENT_SECRET="your_twitch_client_secret_here"

```


2. **Install Dependencies:**
Ensure you have Python installed. Install the required packages using pip:
```bash
pip install fastapi uvicorn aiohttp curl_cffi loguru python-dotenv

```


3. **Start the Backend:**
Run the following command in your terminal to start the background scrapers and API server:
```bash
python main.py

```


4. **Open the Dashboard:**
Simply double-click the `index.html` file to open it in your web browser. (No node server required for the frontend).

---

## 🛑 Known Limitations & Kick Player Nuances

**The Kick Volume Problem:**
Kick does not currently offer a developer API for their iframe embeds, and they aggressively enforce fullscreen requirements before rendering volume sliders. Furthermore, Kick's AWS IVS video endpoints utilize strict **CORS** policies that prevent third-party domains (like `localhost`) from extracting the raw `.m3u8` video feeds to build custom native players.

**The Workaround:**
To maintain 100% stability, this dashboard uses standard Kick iframes. To control Kick volume without going fullscreen, it is highly recommended to use a browser extension like **KickScroll** or inject a custom volume slider via **Tampermonkey**.

---

## 🗺️ Roadmap / To-Do

* [x] Build core UI and tab navigation.
* [x] Integrate SortableJS for custom directory layouts.
* [x] Build multi-stream setup with smart URL/username detection.
* [x] Implement Theater Mode and custom player overlays.
* [x] Add dynamic "Add/Remove" functionality to active multi-stream views.
* [x] Implement dual-server support (NoPixel / Prodigy).
* [x] Build Hybrid Scraper (HasRoot + Lofi + Twitch API).
* [x] Add live UI editors for Faction Tags and Server Overrides.
* [x] Implement historical SQLite viewership metrics graphing.