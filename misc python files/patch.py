import os

# The exact path from your error traceback
file_path = r"C:\Users\Nassir\AppData\Roaming\Python\Python314\site-packages\nodriver\cdp\network.py"

try:
    # Read the file as raw bytes
    with open(file_path, 'rb') as f:
        content = f.read()
    
    # Replace the invalid byte (\xb1) with standard text ('+-')
    if b'\xb1' in content:
        content = content.replace(b'\xb1', b'+-')
        
        # Write the fixed bytes back to the file
        with open(file_path, 'wb') as f:
            f.write(content)
        print("Successfully patched nodriver! You can now run main.py")
    else:
        print("The file has already been patched or the byte was not found.")
        
except Exception as e:
    print(f"Error patching file: {e}")