import json
import os
import random

def add_user_to_group():
    print("--- Add Streamer to Faction ---")
    
    # 1. Gather the data via terminal prompts
    group_name = input("Enter the faction/group name (e.g., LSPD, Manor): ").strip()
    if not group_name:
        print("❌ Error: Group name cannot be blank.")
        return
        
    username = input("Enter the streamer's username: ").strip().lower()
    if not username:
        print("❌ Error: Username cannot be blank.")
        return
        
    twitch_url = input("Enter Twitch URL (leave blank if none): ").strip()
    kick_url = input("Enter Kick URL (leave blank if none): ").strip()

    if not twitch_url and not kick_url:
        print("❌ Error: You must provide at least one platform URL.")
        return

    # 2. Load the existing groups.json
    file_path = "groups.json"
    if not os.path.exists(file_path):
        print(f"❌ Error: {file_path} not found in the current directory.")
        return
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print("❌ Error: groups.json is corrupted or not formatted properly.")
        return

    # 3. Find the group (case-insensitive check)
    target_key = None
    for key in data.keys():
        if key.lower() == group_name.lower():
            target_key = key
            break
            
    # If the group doesn't exist, create it dynamically
    if not target_key:
        print(f"⚠️ Group '{group_name}' not found. Creating a new faction...")
        target_key = group_name
        random_color = f"#{random.randint(0, 0xFFFFFF):06x}"
        data[target_key] = {
            "full_name": group_name,
            "color": random_color,
            "members": {}
        }

    # 4. Inject the user safely
    if username not in data[target_key]["members"]:
        data[target_key]["members"][username] = {"platforms": {}}
    
    if twitch_url:
        data[target_key]["members"][username]["platforms"]["twitch"] = twitch_url
    if kick_url:
        data[target_key]["members"][username]["platforms"]["kick"] = kick_url

    # 5. Save the updated file
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\n✅ Successfully added/updated '{username}' in '{target_key}'!")

if __name__ == "__main__":
    add_user_to_group()