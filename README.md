# WSH Nationals Bot

A Telegram bot that provides Washington Nationals MLB information including schedules, standings, and recent game results.

## Features

- **Schedule** - Get upcoming Nationals games (`/sch`)
- **Past Games** - View last 3 Nationals game results (`/past`)
- **Standings** - All MLB division standings
  - `/nlwest` - NL West standings
  - `/nleast` - NL East standings
  - `/nlcentral` - NL Central standings
  - `/alwest` - AL West standings
  - `/aleast` - AL East standings
  - `/alcentral` - AL Central standings
- **Automated Daily Posting** - Posts yesterday's Nationals scores at 10 AM Central Time

## Setup

### Prerequisites

- Python 3.7+
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
   # Edit .env with your bot token
   ```

4. **Run the bot**
   ```bash
   python main.py
   ```

## Environment Variables

Create a `.env` file with:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

⚠️ **Important:** Never commit your `.env` file to version control!

## Commands

| Command | Description |
|---------|-------------|
| `/sch` | Nationals upcoming schedule (next 4 days) |
| `/past` | Last 3 Nationals game results |
| `/nlwest` | NL West standings |
| `/nleast` | NL East standings |
| `/nlcentral` | NL Central standings |
| `/alwest` | AL West standings |
| `/aleast` | AL East standings |
| `/alcentral` | AL Central standings |
| `/scores` | Live MLB scores |
| `/leave [team]` | Leave game calculator (optional team argument, defaults to "nationals") |
| `/help` | Show this help message |

## Deployment

### Railway

1. Connect your GitHub repository to Railway
2. Set environment variable in Railway dashboard:
   - `TELEGRAM_BOT_TOKEN=your_bot_token_here`
3. Deploy!

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
├── mlbscores.py         # MLB API integration and formatting
├── logger.py            # Logging configuration
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variables template
└── README.md           # This file
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
