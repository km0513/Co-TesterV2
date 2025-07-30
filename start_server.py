import os
import sys
import subprocess
import time

def start_flask_server():
    print("Starting Flask server...")
    
    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Command to start the Flask server
    cmd = [sys.executable, "app.py"]
    
    # Start the server as a subprocess
    try:
        process = subprocess.Popen(cmd, cwd=current_dir)
        print(f"Server started with PID: {process.pid}")
        print("Waiting for server to initialize...")
        
        # Wait a bit for the server to start
        time.sleep(5)
        
        print("Server should be running now at http://localhost:5050")
        print("Press Ctrl+C in this terminal to stop the server")
        
        # Keep the script running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopping server...")
            process.terminate()
            process.wait()
            print("Server stopped")
    
    except Exception as e:
        print(f"Error starting server: {str(e)}")

if __name__ == "__main__":
    start_flask_server()
