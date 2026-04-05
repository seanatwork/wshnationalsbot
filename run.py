import threading
import time
import logging
from healthcheck import start_healthcheck
from logger import setup_logger
from config import HEALTHCHECK_PORT, validate_config

# Setup logging
setup_logger(logging.INFO)
logger = logging.getLogger(__name__)

# Validate configuration
validate_config()


def run_bot():
    """Run the main bot"""
    import main
    main.main()


if __name__ == '__main__':
    # Start healthcheck in background thread
    health_thread = threading.Thread(target=start_healthcheck, daemon=True)
    health_thread.start()

    # Give healthcheck time to start
    time.sleep(2)
    logger.info(f"Healthcheck started on port {HEALTHCHECK_PORT}")

    # Run bot in main thread
    run_bot()
