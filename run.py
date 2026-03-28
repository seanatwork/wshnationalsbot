import subprocess
import threading
import time
from flask import Flask, jsonify
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Flask app for healthcheck
app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

def run_healthcheck():
    """Run Flask healthcheck in background"""
    app.run(host='0.0.0.0', port=8000, debug=False)

def run_bot():
    """Run the main bot"""
    import main
    main.main()

if __name__ == '__main__':
    # Start healthcheck in background thread
    health_thread = threading.Thread(target=run_healthcheck, daemon=True)
    health_thread.start()
    
    # Give healthcheck time to start
    time.sleep(2)
    
    # Run bot in main thread
    run_bot()
