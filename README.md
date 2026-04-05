# WSH Nationals Bot

A Telegram bot that provides Washington Nationals MLB information including schedules, standings, and recent game results.

## Features

- **Schedule** - Get upcoming Nationals games (`/sch`)
- **Past Games** - View last 3 Nationals game results (`/past`)
- **Standings** - All MLB division standings (`/standings`)
- **Statistics** - Advanced MLB statistics (`/stats`)
- **Highlights** - Recent Nationals video highlights (`/highlights`)
- **Live Scores** - All live MLB games (`/scores`)
- **Leave Calculator** - FiveThirtyEight-inspired "when to leave" calculator (`/leave [team]`)
- **Automated Daily Posting** - Posts yesterday's Nationals scores at configurable time

## Setup

### Prerequisites

- Python 3.10+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/wshnationalsbot.git
   cd wshnationalsbot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your bot token and other settings
   ```

4. **Run the bot**
   ```bash
   python run.py
   ```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather | **Required** |
| `CHAT_ID` | Chat ID for automated daily scores | `@natsdc` |
| `TIMEZONE` | Timezone for scheduling | `America/Chicago` |
| `DAILY_POST_TIME` | Daily post time (HH:MM format) | `10:00` |
| `LEAVE_FP_RATE` | Leave calculator false-positive tolerance | `0.05` |
| `HEALTHCHECK_PORT` | Health check server port | `8000` |
| `HEALTHCHECK_HOST` | Health check server host | `0.0.0.0` |

⚠️ **Important:** Never commit your `.env` file to version control!

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and getting started |
| `/sch` | Nationals upcoming schedule (next 4 days) |
| `/past` | Last 3 Nationals game results |
| `/standings` | MLB division standings (interactive menu) |
| `/stats` | Advanced MLB statistics (ABS challenges) |
| `/highlights` | Recent Nationals video highlights |
| `/scores` | Live MLB scores |
| `/leave [team]` | Leave game calculator (optional team argument, defaults to "nationals") |
| `/help` | Show this help message |

## Deployment

### Fly.io

See `fly.toml` for configuration. Deploy with:

```bash
fly deploy
```

### Local Development

```bash
# Install development dependencies
pip install -r requirements.txt

# Run locally
python main.py
```

## API Usage

This bot uses the [MLB Stats API](https://www.mlb.com/api-docs/) via the [MLB-StatsAPI](https://pypi.org/project/MLB-StatsAPI/) Python package.

## Project Structure

```
wshnationalsbot/
├── main.py              # Bot entry point and command handlers
├── run.py               # Production runner with healthcheck
├── mlbscores.py         # MLB API integration and command handlers
├── stats.py             # Advanced statistics (ABS challenges)
├── highlights.py        # MLB.com video highlights
├── leave_calculator.py  # FiveThirtyEight-inspired leave calculator
├── config.py            # Centralized configuration
├── logger.py            # Logging setup
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variables template
├── Dockerfile           # Docker build configuration
├── fly.toml             # Fly.io deployment config
└── README.md            # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is open source and available under the [MIT License](LICENSE).

## Security

- Never expose your bot token
- Use environment variables for sensitive data
- Regularly rotate your bot tokens
- Monitor your bot's activity

## Support

If you encounter issues:

1. Check the logs for error messages
2. Verify your bot token is correct
3. Ensure the MLB Stats API is accessible
4. Check your internet connection

## Changelog

### v1.0.0
- Initial release
- Nationals schedule and standings
- Automated daily posting
- Cross-platform date formatting
