import sqlite3
import os

# The name of the streamer you want to remove
target_name = "nicatude"

def delete_streamer(name):
    base_path = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_path, "streamers.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # We use the WHERE clause to target the specific username
        cursor.execute("DELETE FROM streamers WHERE username = ?", (name,))
        
        if cursor.rowcount > 0:
            conn.commit()
            print(f"[Success] '{name}' has been deleted from the database.")
        else:
            print(f"[Notice] No streamer found with the name '{name}'.")
            
        conn.close()
    except sqlite3.Error as e:
        print(f"[Error] {e}")

if __name__ == "__main__":
    delete_streamer(target_name)