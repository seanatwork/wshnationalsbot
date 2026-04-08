"""Centralized configuration for the bot."""
import os
from dotenv import load_dotenv

load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Nationals team ID (MLB API)
NATIONALS_TEAM_ID = 120

# Default chat ID for automated daily scores
CHAT_ID = os.getenv('CHAT_ID', '@natsdc')

# Timezone for scheduling
TIMEZONE = os.getenv('TIMEZONE', 'America/Chicago')

# Daily post time (hour:minute format)
DAILY_POST_TIME = os.getenv('DAILY_POST_TIME', '10:00')

# Leave calculator settings
LEAVE_FP_RATE = float(os.getenv('LEAVE_FP_RATE', '0.05'))

# Channel to auto-post daily lineups (set to None to disable)
LINEUP_CHANNEL_ID = os.getenv('LINEUP_CHANNEL_ID')

# Subscribers file path (use a Fly.io persistent volume mount in production)
SUBSCRIBERS_FILE = os.getenv('SUBSCRIBERS_FILE', '/data/subscribers.json')

# Health check configuration
HEALTHCHECK_PORT = int(os.getenv('HEALTHCHECK_PORT', '8000'))
HEALTHCHECK_HOST = os.getenv('HEALTHCHECK_HOST', '0.0.0.0')


def validate_config() -> None:
    """Validate required configuration values."""
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")
