import requests

def fetch_and_display_streams():
    # This points to your running FastAPI server
    url = "http://localhost:8000/api/streams"
    
    print("Fetching active NoPixel streams from local API...\n")
    
    try:
        response = requests.get(url)
        response.raise_for_status() # Check for HTTP errors
        
        data = response.json()
        streams = data.get("streams", [])
        total_count = data.get("count", 0)
        
        print(f"--- Found {total_count} Live Streams ---")
        
        for stream in streams:
            channel = stream.get("channel")
            viewers = stream.get("viewers")
            title = stream.get("title")
            
            # Formats output like: [1500 viewers] xQc: Bank Heist!
            print(f"[{viewers} viewers] {channel}: {title}")
            
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the server. Is main.py running?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    fetch_and_display_streams()