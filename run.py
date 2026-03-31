import subprocess
import threading
import time
import logging
from flask import Flask, jsonify
from logger import setup_logger
from config import HEALTHCHECK_HOST, HEALTHCHECK_PORT, validate_config

# Setup logging
setup_logger(logging.INFO)
logger = logging.getLogger(__name__)

# Validate configuration
validate_config()

# Flask app for healthcheck
app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200


def run_healthcheck():
    """Run Flask healthcheck in background"""
    app.run(host=HEALTHCHECK_HOST, port=HEALTHCHECK_PORT, debug=False)

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
    logger.info("Healthcheck started on port 8000")

    # Run bot in main thread
    run_bot()
