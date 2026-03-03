import sqlite3
import csv
import os

def build_database_from_csv(csv_filename):
    print("[DB] Initializing SQLite Database...")
    
    # 1. Setup the SQLite Database Connection
    conn = sqlite3.connect('streamers.db')
    cursor = conn.cursor()
    
    # Create the table with a UNIQUE constraint to prevent duplicate entries
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS streamers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE
        )
    ''')
    conn.commit()

    print(f"[CSV] Reading streamers from {csv_filename}...")
    streamers_added = 0
    
    # 2. Open and parse the CSV file
    if not os.path.exists(csv_filename):
        print(f"\n[Error] Could not find '{csv_filename}'. Please ensure it is in the same folder as this script.")
        return

    with open(csv_filename, mode='r', encoding='utf-8') as file:
        reader = csv.reader(file)
        
        for row in reader:
            # Skip empty rows
            if not row:
                continue 
            
            # Extract the username (assuming it's in the first column)
            name = row[0].strip()
            
            # Standardize the name (Twitch usernames are usually lowercase anyway)
            # and ignore header rows if your CSV has one like "StreamerName"
            if name and name.lower() not in ["streamername", "name", "username"]:
                try:
                    # INSERT OR IGNORE safely skips the name if it's already in the DB
                    cursor.execute("INSERT OR IGNORE INTO streamers (username) VALUES (?)", (name,))
                    if cursor.rowcount > 0:
                        streamers_added += 1
                except sqlite3.Error as e:
                    print(f"[DB Error] {e}")

    # 3. Save and close
    conn.commit()
    conn.close()
    
    print(f"\n[Success] Added {streamers_added} unique streamers to streamers.db!")

if __name__ == "__main__":
    # Ensure your CSV file is named this, or change the string below to match!
    build_database_from_csv('streamers.csv')