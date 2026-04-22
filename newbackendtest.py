import re
import json
from curl_cffi import requests

def fetch_live_handles():
    """Fetches the raw list of live platform handles from Lofi-NoPixel."""
    session = requests.Session(impersonate="chrome116")
    try:
        response = session.get("https://lofi-nopixel.com/multipov")
        if response.status_code != 200:
            return set()
            
        # Extract all handles from the SvelteKit JSON block
        matches = re.findall(r'platformHandle:\s*"([^"]+)"', response.text)
        return set([match.lower() for match in matches])
        
    except Exception:
        return set()

def find_live_kick_streamers(live_handles):
    """Cross-references live handles against groups.json to isolate Kick streamers."""
    print("📂 Loading groups.json database...")
    try:
        with open("groups.json", "r", encoding="utf-8") as f:
            groups_data = json.load(f)
    except FileNotFoundError:
        print("❌ Could not find groups.json!")
        return []
        
    confirmed_kick_live = []
    seen_handles = set() # Prevent duplicates if someone is in multiple groups (like PD and LSPD)

    print("🔍 Cross-referencing live handles against faction data...")
    for group_name, group_info in groups_data.items():
        for member_key, member_data in group_info.get("members", {}).items():
            platforms = member_data.get("platforms", {})
            kick_url = platforms.get("kick")
            
            if kick_url:
                # Extract the exact Kick username from their URL
                kick_handle = kick_url.rstrip('/').split('/')[-1].lower()
                
                # Check if their JSON key OR their specific Kick handle is in the live list
                if member_key.lower() in live_handles or kick_handle in live_handles:
                    if kick_handle not in seen_handles:
                        seen_handles.add(kick_handle)
                        
                        confirmed_kick_live.append({
                            "handle": kick_handle,
                            "group_name": group_info.get("full_name", group_name),
                            "color": group_info.get("color", "#ffffff"),
                            "url": kick_url
                        })
                        
    return confirmed_kick_live

if __name__ == "__main__":
    print("🚀 Initiating Lightning Scrape...")
    live_handles = fetch_live_handles()
    print(f"✅ Extracted {len(live_handles)} total live streams across all platforms.")
    
    kick_streamers = find_live_kick_streamers(live_handles)
    
    print(f"\n🎉 Success! Found {len(kick_streamers)} confirmed Kick roleplayers currently live:")
    print("-" * 50)
    for streamer in kick_streamers:
        print(f"🎥 {streamer['handle']}  |  Faction: {streamer['group_name']}")
    print("-" * 50)