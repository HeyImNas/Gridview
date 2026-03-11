import json

def populate_pd_group():
    print("Loading groups.json...")
    try:
        with open("groups.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error loading groups.json: {e}")
        return

    # Ensure the PD group exists
    if "PD" not in data:
        data["PD"] = {
            "full_name": "Police Department",
            "color": "#1e90ff",
            "members": {}
        }

    departments_to_merge = ["LSPD", "BCSO", "SASM"]
    pd_members = data["PD"]["members"]
    
    added_count = 0

    print("Merging departments into PD...")
    for dept in departments_to_merge:
        if dept in data:
            dept_members = data[dept]["members"]
            for member_name, member_info in dept_members.items():
                if member_name not in pd_members:
                    # Add them to the PD group
                    pd_members[member_name] = member_info
                    added_count += 1
                else:
                    # If they are already in PD, just ensure their platforms are up to date
                    pd_members[member_name]["platforms"].update(member_info.get("platforms", {}))

    # Save the updated file
    with open("groups.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"✅ Successfully copied {added_count} officers into the PD group!")

if __name__ == "__main__":
    populate_pd_group()