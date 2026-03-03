import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urlparse

BASE_URL = "https://lofi-nopixel.com/groups/"

groups = [
    "Hydra",
    "Besties",
    "Manor",
    "New Babylon",
    "Ex Manor",
    "Lost MC: Diamond Chapter",
    "Cuban Federales",
    "The Crackheads",
    "The Faceless",
    "The Merchants",
    "3PAS",
    "Besties Associates",
    "Clowncil",
    "GSF",
    "Hounds MC",
    "Kaneshiro",
    "Ravens MC",
    "ADMC",
    "Chaos Crew",
    "Cypress",
    "Davis Cartel",
    "East Side Vagos",
    "HOA",
    "Habibis",
    "Halo",
    "Iconicz",
    "Kilo Tray Ballas",
    "League of Evil",
    "Mimes",
    "NoPixel Devs",
    "Raiders MC",
    "SYN",
    "Sewer Rats",
    "Skeleton Crew",
    "Smileys",
    "Strayz",
    "The Crayons",
    "The Guild",
    "The Italians",
    "The Neon Circus"
]

headers = {
    "User-Agent": "Mozilla/5.0"
}

def format_group_url(name):
    return BASE_URL + name.replace(" ", "%20")

def extract_channel_name(url):
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")
    if path_parts:
        return path_parts[-1]
    return None

def get_streamers_from_group(group_name):
    url = format_group_url(group_name)
    print(f"Fetching {group_name}...")

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch {group_name}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    streamers = []

    for link in soup.find_all("a", href=True):
        href = link["href"]

        if "twitch.tv" in href or "kick.com" in href:
            channel_name = extract_channel_name(href)
            if channel_name:
                streamers.append({
                    "platform": "twitch" if "twitch.tv" in href else "kick",
                    "channel": channel_name,
                    "url": href
                })

    # Remove duplicates
    unique_streamers = { (s["platform"], s["channel"]): s for s in streamers }
    return list(unique_streamers.values())


data = {}

for group in groups:
    try:
        streamers = get_streamers_from_group(group)
        data[group] = streamers
        time.sleep(1)  # polite delay
    except Exception as e:
        print(f"Error with {group}: {e}")
        data[group] = []

# Save results
with open("nopixel_streamers.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)

print("Done! Saved to nopixel_streamers.json")