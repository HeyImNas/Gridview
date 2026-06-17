import sqlite3
import os

def inject_new_streamers():
    base_path = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_path, "streamers.db")
    txt_path = os.path.join(base_path, "prodigy_twitch_streamers.txt")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Ensure the base table exists
    cursor.execute("CREATE TABLE IF NOT EXISTS streamers (username TEXT UNIQUE)")
    
    # 2. Add the new 'server' column. 
    # By setting DEFAULT to 'nopixel', SQLite instantly updates ALL existing rows!
    try:
        cursor.execute("ALTER TABLE streamers ADD COLUMN server TEXT DEFAULT 'nopixel'")
        print("Success: Added 'server' column and updated existing entries to 'nopixel'.")
    except sqlite3.OperationalError:
        # If the column already exists (you ran the script twice), just ignore the error
        pass 
    
    # 3. Read the raw text file
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except FileNotFoundError:
        print("Error: Could not find 'prodigy_twitch_streamers.txt'. Make sure it is in the same folder!")
        return

    months = ["Jan ", "Feb ", "Mar ", "Apr ", "May ", "Jun ", "Jul ", "Aug ", "Sep ", "Oct ", "Nov ", "Dec "]
    streamers_added = 0
    duplicates_skipped = 0

    # 4. Parse the data and inject
    for line in raw_lines:
        clean_line = line.strip()
        
        # Filter 1: Skip empty lines
        if not clean_line:
            continue
            
        # Filter 2: Skip single-character alphabetical headers (e.g., "A", "B", "#")
        if len(clean_line) == 1:
            continue
            
        # Filter 3: Skip lines that start with a month (the dates)
        if any(clean_line.startswith(month) for month in months):
            continue
            
        # --- THE FIX ---
        # Explicitly tag these newly injected users as 'prodigy'. 
        # If they are already in the DB as NoPixel, INSERT OR IGNORE skips them.
        cursor.execute("INSERT OR IGNORE INTO streamers (username, server) VALUES (?, 'prodigy')", (clean_line,))
        
        if cursor.rowcount > 0:
            streamers_added += 1
        else:
            duplicates_skipped += 1

    # Save changes and close
    conn.commit()
    conn.close()

    print("--- INJECTION COMPLETE ---")
    print(f"Successfully added: {streamers_added} NEW Prodigy streamers")
    print(f"Duplicates skipped: {duplicates_skipped}")

if __name__ == "__main__":
    inject_new_streamers()