# 🟢 Stream Directory & Multi-Viewer

A lightweight, high-performance local web dashboard designed to track, filter, and watch GTA V RP (NoPixel) streams seamlessly across both Twitch and Kick. Built with a Python FastAPI backend and a dependency-free Vanilla JS/HTML/CSS frontend. This project is intended for personal use however if anyone else wants to access it your more than welcome to it. Might explore a hosted version down the line.

## 🚀 Features

### 📺 Smart Stream Directory
* **Live Aggregation:** Pulls live NoPixel streamers from both Twitch and Kick via a custom Python backend.
* **Smart Filtering & Search:** Instantly filter by platform (Twitch/Kick) or search by streamer name, stream title, or faction tags.
* **Custom Layouts:** Drag-and-drop stream cards to reorganize your grid. Layouts are automatically saved to your browser's `localStorage`.

### 🎭 Advanced Multi-Stream Viewer
* **Smart Input Detection:** Paste a full URL (`kick.com/user` or `twitch.tv/user`) or just type a username. The system automatically cross-references the live cache to determine the correct platform.
* **Dynamic Grid:** Add or remove streams on the fly. The CSS grid automatically mathematically recalculates to fill the screen perfectly (e.g., 1 stream, 2 side-by-side, 4 in a grid, etc.).
* **Active View "Quick Add":** Add new streamers directly into an active multi-view session without having to stop and rebuild the layout.
* **Lofi-Style Overlays:** Clean, hover-activated overlay controls on every video frame to instantly **Refresh** a frozen stream or **Close** a player.
* **Integrated Chat:** A side-panel chat system with tabs to easily switch between the chatrooms of the streamers you are currently watching.
* **Theater Mode:** A single button click hides the top navigation tabs, header, and search bar, expanding the video grid to 100% of the viewport.
* **Error Handling:** Sleek, non-intrusive Toast Notifications alert you if a requested stream is offline or invalid without breaking the rest of the layout.

### 📑 Fast Navigation
* Integrated iframes for external tools (Events, Recaps, Clips, Groups).
* Press the **`** (backtick) key to quickly cycle through all dashboard tabs without clicking.

---

## 🛠️ Tech Stack
* **Frontend:** HTML5, CSS3, Vanilla JavaScript. (No React/Vue overhead).
* **Grid Library:** `SortableJS` (for drag-and-drop stream cards).
* **Backend:** Python 3, FastAPI, `requests` (Caches live streams to avoid rate limits).

---

## 📁 Project Structure & Misc Files

* **`index.html`**: The complete frontend dashboard. Contains all the UI, CSS, and Vanilla JavaScript logic for the grid, tabs, and multi-viewer.
* **`main.py`**: The Python FastAPI backend. Handles scraping, API requests, data aggregation, and serves the formatted JSON to the frontend.
* **`groups.json`** *(Misc/Upcoming)*: A local JSON database file used by the Python backend to map specific streamer usernames to their in-game NoPixel factions, groups, or businesses (e.g., LSPD, Manor, Besties) so tags can be generated dynamically.
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
   
   # Server Configuration
   HOST=127.0.0.1
   PORT=8000
   ```

2. **Start the Backend:**
   Ensure you have Python installed, along with `fastapi`, `uvicorn`, and `requests`. Run the following command in your terminal:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

3. **Open the Dashboard:**
   Simply double-click the `index.html` file to open it in your web browser. (No node server required for the frontend).

---

## 🛑 Known Limitations & Kick Player Nuances

**The Kick Volume Problem:**
Kick does not currently offer a developer API for their iframe embeds, and they aggressively enforce fullscreen requirements before rendering volume sliders. Furthermore, Kick's AWS IVS video endpoints utilize strict **CORS** policies that prevent third-party domains (like `localhost`) from extracting the raw `.m3u8` video feeds to build custom native players. 

**The Workaround:**
To maintain 100% stability, this dashboard uses standard Kick iframes. To control Kick volume without going fullscreen, it is highly recommended to use a browser extension like **KickScroll** or inject a custom volume slider via **Tampermonkey**.

---

## 🗺️ Roadmap / To-Do
- [x] Build core UI and tab navigation.
- [x] Integrate SortableJS for custom directory layouts.
- [x] Build multi-stream setup with smart URL/username detection.
- [x] Implement Theater Mode and custom player overlays.
- [x] Add dynamic "Add/Remove" functionality to active multi-stream views.
- [ ] **Backend:** Implement `groups.json` mapping to automatically assign NoPixel Faction/Group tags (e.g., LSPD, Manor, Besties) to streamer cards dynamically.
