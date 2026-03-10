import json
import random
import time
from bs4 import BeautifulSoup
from curl_cffi import requests

def generate_random_color():
    """Generates a random hex color code for new factions."""
    return f"#{random.randint(0, 0xFFFFFF):06x}"

def expand_specific_groups():
    # NEW LIST OF GROUPS TO SCRAPE
    target_groups = [
        "The_Baas_Family", "The_Pingafrias", "The_D20s", 
        "The_Jones_Family", "The_Wolf_Family", "The_Foozes", 
        "The_Littlemans", "The_Marshalls", "Top_10", "DSL"
    ]
    
    factions_data = {}
    session = requests.Session(impersonate="chrome110")
    
    print("Starting targeted Cloudflare scrape for Families & Crews...\n")
    
    for group in target_groups:
        url = f"https://lofi-nopixel.com/groups/{group}"
        
        try:
            response = session.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all("a", href=True)
            
            members_dict = {}
            for link in links:
                href = link['href'].lower()
                clean_url = href.split('?')[0].rstrip('/')
                
                # Extract username and format it exactly like the existing groups.json
                if "twitch.tv/" in clean_url:
                    username = clean_url.split('/')[-1]
                    if username not in members_dict:
                        members_dict[username] = {"platforms": {}}
                    members_dict[username]["platforms"]["twitch"] = clean_url
                    
                elif "kick.com/" in clean_url:
                    username = clean_url.split('/')[-1]
                    if username not in members_dict:
                        members_dict[username] = {"platforms": {}}
                    members_dict[username]["platforms"]["kick"] = clean_url
            
            # Format the group name nicely
            display_name = group.replace("_", " ").title()
            
            # Keep DSL as an acronym
            if display_name.upper() in ["DSL"]:
                display_name = display_name.upper() 
            
            factions_data[display_name] = {
                "full_name": display_name,
                "color": generate_random_color(),
                "members": members_dict
            }
            
            print(f"✅ Found {len(members_dict)} unique members for {display_name}")
            time.sleep(1) 
            
        except Exception as e:
            print(f"❌ Error scraping {group}: {e}")
            
    print("\nMerging with existing groups.json...")
    
    # Load existing dictionary safely
    try:
        with open("groups.json", "r", encoding="utf-8") as f:
            existing_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No existing groups.json found. Creating a fresh one.")
        existing_data = {}
        
    # Proper Dictionary Merge
    for group_name, new_data in factions_data.items():
        if group_name in existing_data:
            # Group exists, let's merge new members into it without losing the existing ones
            for mem_name, mem_data in new_data["members"].items():
                if mem_name in existing_data[group_name]["members"]:
                    existing_data[group_name]["members"][mem_name]["platforms"].update(mem_data["platforms"])
                else:
                    existing_data[group_name]["members"][mem_name] = mem_data
        else:
            # Brand new group
            existing_data[group_name] = new_data
            
    # Save the final file formatted nicely
    with open("groups.json", "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2)
        
    print("🎉 Done! groups.json has been correctly updated.")

if __name__ == "__main__":
    expand_specific_groups()