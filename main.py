import threading
import asyncio
import logging
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InlineQueryResultsButton, InputTextMessageContent
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, InlineQueryHandler, ContextTypes
from mlbscores import (
    nats_schedule, mlb_scores, post_yesterday_to_channel,
    post_gameday_preview, post_monday_standings,
    nlwest_standings, nleast_standings, nlcentral_standings,
    alwest_standings, aleast_standings, alcentral_standings,
    get_past_games, live_scores, _format_standings, schedule,
    get_past_games_scores, _get_live_scores_text,
)
from stats import get_nationals_team_stats, get_roster_moves, get_weekly_digest, fetch_new_transactions
from lineup_notifier import add_subscriber, remove_subscriber, check_and_notify
from player import get_splits, get_contract
from highlights import get_nationals_highlights
from leave_calculator import build_stats, fetch_live_game, should_leave, _completed_inning
from logger import setup_logger, get_logger
from config import (
    BOT_TOKEN, CHAT_ID, TIMEZONE, DAILY_POST_TIME,
    NATIONALS_TEAM_ID, LEAVE_FP_RATE, LINEUP_CHANNEL_ID, validate_config
)
from datetime import time
import pytz

# Setup logging
setup_logger(logging.INFO)
logger = get_logger(__name__)

# Loaded once at startup in a background thread
_leave_stats: dict | None = None
_leave_stats_lock = threading.Lock()
_leave_stats_ready = threading.Event()


def _load_leave_stats() -> None:
    """Load leave calculator stats in background thread."""
    global _leave_stats
    try:
        _leave_stats = build_stats()
        logger.info("Leave calculator stats loaded.")
    finally:
        _leave_stats_ready.set()


def _wait_for_stats() -> bool:
    """Wait for stats to be loaded (timeout 30s)."""
    return _leave_stats_ready.wait(timeout=30)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - welcome message."""
    welcome_text = """<b>Welcome to WSH Nationals Bot! 🏟️</b>

Your Washington Nationals companion for Telegram.

<b>Commands:</b>
/sch - Upcoming schedule (next 4 days)
/past - Last 3 game results
/scores - Live MLB scores
/standings - All 6 division standings
/splits - Player splits (vs L/R, home/away, recent)
/contract - Contract &amp; fun salary facts
/lineup - Subscribe to gameday lineup notifications
/roster - Recent roster moves
/highlights - Recent Nationals video highlights
/stats - Team stats vs NL East &amp; MLB
/leave - Should you leave the game early?
/help - Show all commands

<a href="https://github.com/seanatwork/wshnationalsbot">Source on GitHub</a>

<i>Privacy: This bot does not collect or store any personal data. Game data is sourced from the public MLB Stats API.</i>"""
    await update.message.reply_text(welcome_text, parse_mode="HTML", disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = """
<b>WSH Nationals Bot Commands:</b>

/sch - Nationals upcoming schedule (next 4 days)
/past - Last 3 Nationals game results
/standings - All MLB division standings
/scores - Live MLB scores
/splits &lt;player&gt; - Splits vs L/R, home/away, last 7/15/30d
/contract &lt;player&gt; - Contract &amp; fun salary facts
/lineup on/off - Gameday lineup notifications
/roster - Recent Nationals roster moves
/leave [team] - Leave game calculator (optional team argument, defaults to "nationals")
/help - Show this help message

<i>Privacy: This bot does not store personal data. Game data is sourced from the public MLB Stats API. By using this bot you agree to <a href="https://telegram.org/privacy-tpa">Telegram's Privacy Policy for Third-Party Bots</a>.</i>
"""
    await update.message.reply_text(help_text, parse_mode="HTML", disable_web_page_preview=True)

async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /leave command - decide if user should leave the game."""
    # Wait for stats to load
    if not _wait_for_stats():
        await update.message.reply_text(
            "Stats are still loading. Please try again in a moment."
        )
        return

    team = " ".join(context.args) if context.args else "nationals"
    game = fetch_live_game(team)

    if game is None:
        await update.message.reply_text(f"No game found today for '{team}'.")
        return

    away, home = game["away_team"], game["home_team"]
    away_score, home_score = game["away_score"], game["home_score"]
    raw_inning = game["inning"]
    inning_half = game["inning_half"]
    status = game["status"]
    abstract = game["abstract"]

    if abstract == "Preview" or raw_inning is None:
        await update.message.reply_text(f"{away} vs {home} has not started yet.")
        return

    # Check for rain delays and postponements
    status_lower = status.lower() if status else ""
    if "postponed" in status_lower:
        await update.message.reply_text(
            f"<b>{away} vs {home}</b>\n\n"
            f"Game has been postponed.",
            parse_mode="HTML"
        )
        return
    
    if "delay" in status_lower or "suspended" in status_lower:
        await update.message.reply_text(
            f"<b>{away} {away_score} @ {home} {home_score}</b>\n"
            f"Inning: {raw_inning}{half_str} | {status}\n\n"
            f"Game is currently delayed. Check back later!",
            parse_mode="HTML"
        )
        return

    if status == "Game Over" or abstract == "Final":
        await update.message.reply_text(
            f"<b>{away} {away_score} @ {home} {home_score}</b>\n\n"
            f"You're too late, the game is over! =P",
            parse_mode="HTML"
        )
        return

    completed = _completed_inning(raw_inning, inning_half)
    result = should_leave(away_score, home_score, completed, _leave_stats)

    half_str = f" ({inning_half})" if inning_half else ""
    verdict = "LEAVE NOW" if result["leave"] else "STAY AND WATCH"

    msg = (
        f"<b>{away} {away_score} @ {home} {home_score}</b>\n"
        f"Inning: {raw_inning}{half_str} | {status}\n\n"
        f"<b>{verdict}</b>\n\n"
        f"{result['reason']}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def standings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /standings command - show division selection buttons."""
    keyboard = [
        [
            InlineKeyboardButton("NL West", callback_data="standings_nlwest"),
            InlineKeyboardButton("NL East", callback_data="standings_nleast"),
            InlineKeyboardButton("NL Central", callback_data="standings_nlcentral")
        ],
        [
            InlineKeyboardButton("AL West", callback_data="standings_alwest"),
            InlineKeyboardButton("AL East", callback_data="standings_aleast"),
            InlineKeyboardButton("AL Central", callback_data="standings_alcentral")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "<b>Select a division for standings:</b>",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def standings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle division selection from standings menu."""
    query = update.callback_query
    await query.answer()
    
    division_map = {
        "standings_nlwest": ("nlw", "NL West"),
        "standings_nleast": ("nle", "NL East"),
        "standings_nlcentral": ("nlc", "NL Central"),
        "standings_alwest": ("alw", "AL West"),
        "standings_aleast": ("ale", "AL East"),
        "standings_alcentral": ("alc", "AL Central")
    }
    
    division_code, division_name = division_map.get(query.data, ("", ""))
    if division_code:
        standings_text = await asyncio.to_thread(_format_standings, division_code)
        await query.edit_message_text(
            text=standings_text,
            parse_mode="HTML"
        )
        logger.debug(f"User checked the {division_name} standings")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command - show statistics menu."""
    stats_text = await get_nationals_team_stats()
    await update.message.reply_text(stats_text, parse_mode="HTML")

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle stats selection from menu."""
    query = update.callback_query
    await query.answer()

    if query.data == "stats_team":
        stats_text = await get_nationals_team_stats()
        await query.edit_message_text(text=stats_text, parse_mode="HTML")
        logger.debug("User checked Nationals team stats")

async def splits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /splits PlayerName — show hitting/pitching splits."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /splits <player name>\nExample: /splits Abrams",
            parse_mode="HTML",
        )
        return
    name = " ".join(context.args)
    text = await get_splits(name)
    await update.message.reply_text(text, parse_mode="HTML")
    logger.debug(f"User requested splits for {name}")

async def contract_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /contract PlayerName — show contract and fun salary facts."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /contract <player name>\nExample: /contract Abrams",
            parse_mode="HTML",
        )
        return
    name = " ".join(context.args)
    text = await get_contract(name)
    await update.message.reply_text(text, parse_mode="HTML")
    logger.debug(f"User requested contract for {name}")

async def lineup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /lineup command - subscribe or unsubscribe from lineup notifications."""
    arg = context.args[0].lower() if context.args else ""
    chat_id = update.effective_chat.id

    if arg == "on":
        added = await asyncio.to_thread(add_subscriber, chat_id)
        if added:
            await update.message.reply_text(
                "You're subscribed to Nationals lineup notifications!\n\n"
                "I'll message you here when today's lineup is posted (~60-90 min before first pitch).\n\n"
                "Use /lineup off to unsubscribe.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("You're already subscribed. Use /lineup off to unsubscribe.")
    elif arg == "off":
        removed = await asyncio.to_thread(remove_subscriber, chat_id)
        if removed:
            await update.message.reply_text("You've been unsubscribed from lineup notifications.")
        else:
            await update.message.reply_text("You weren't subscribed. Use /lineup on to subscribe.")
    else:
        await update.message.reply_text(
            "<b>Lineup Notifications</b>\n\n"
            "/lineup on — get notified when today's lineup is posted\n"
            "/lineup off — stop notifications",
            parse_mode="HTML",
        )

async def roster_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /roster command - show recent Nationals roster moves."""
    text = await get_roster_moves()
    await update.message.reply_text(text, parse_mode="HTML")
    logger.debug("User requested Nationals roster moves")

async def highlights_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /highlights command - show recent Nationals video highlights."""
    highlights_text = await get_nationals_highlights()
    await update.message.reply_text(
        highlights_text,
        parse_mode="HTML",
        disable_web_page_preview=False
    )
    logger.debug("User requested Nationals highlights")

_INLINE_HELP = (
    "Try: <b>scores</b>, <b>schedule</b>, <b>past</b>, <b>stats</b>, "
    "<b>nle</b> / <b>nlw</b> / <b>nlc</b> / <b>ale</b> / <b>alw</b> / <b>alc</b>"
)

_DIVISION_MAP = {
    "nle": "nle", "nleast": "nle",
    "nlw": "nlw", "nlwest": "nlw",
    "nlc": "nlc", "nlcentral": "nlc",
    "ale": "ale", "aleast": "ale",
    "alw": "alw", "alwest": "alw",
    "alc": "alc", "alcentral": "alc",
}

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries: @botname <query>"""
    query = update.inline_query.query.strip().lower()
    results = []

    if not query or query == "help":
        results.append(InlineQueryResultArticle(
            id="help",
            title="WSH Nationals Bot — inline commands",
            description="scores · schedule · past · stats · nle/nlw/nlc/ale/alw/alc",
            input_message_content=InputTextMessageContent(
                _INLINE_HELP, parse_mode="HTML"
            ),
        ))

    elif query in ("scores", "live", "livescores"):
        text = await asyncio.to_thread(_get_live_scores_text)
        results.append(InlineQueryResultArticle(
            id="scores",
            title="Live MLB Scores",
            description="Current scores for all games today",
            input_message_content=InputTextMessageContent(text, parse_mode="HTML"),
        ))

    elif query in ("schedule", "sch"):
        text = await asyncio.to_thread(schedule, NATIONALS_TEAM_ID, TIMEZONE)
        results.append(InlineQueryResultArticle(
            id="schedule",
            title="Nationals Upcoming Schedule",
            description="Next 4 days",
            input_message_content=InputTextMessageContent(text, parse_mode="HTML"),
        ))

    elif query == "past":
        text = await asyncio.to_thread(get_past_games_scores, NATIONALS_TEAM_ID)
        results.append(InlineQueryResultArticle(
            id="past",
            title="Last 3 Nationals Results",
            input_message_content=InputTextMessageContent(
                text or "No recent games found.", parse_mode="HTML"
            ),
        ))

    elif query == "stats":
        text = await get_nationals_team_stats()
        results.append(InlineQueryResultArticle(
            id="stats",
            title="Nationals Team Stats",
            description="Hitting & pitching vs NL East and MLB",
            input_message_content=InputTextMessageContent(text, parse_mode="HTML"),
        ))

    elif query in _DIVISION_MAP:
        div_code = _DIVISION_MAP[query]
        text = await asyncio.to_thread(_format_standings, div_code)
        results.append(InlineQueryResultArticle(
            id=f"standings_{div_code}",
            title=f"{query.upper()} Standings",
            input_message_content=InputTextMessageContent(text, parse_mode="HTML"),
        ))

    await update.inline_query.answer(
        results,
        cache_time=300,
        is_personal=False,
        button=InlineQueryResultsButton(
            text="scores · schedule · past · stats · nle/nlw/nlc/ale/alw/alc",
            start_parameter="inline_help",
        ) if not results else None,
    )


_BOT_COMMANDS = [
    BotCommand("start", "Welcome message and getting started"),
    BotCommand("sch", "Nationals upcoming schedule"),
    BotCommand("past", "Last 3 Nationals game results"),
    BotCommand("splits", "Player splits (vs L/R, home/away, last 7/15/30d)"),
    BotCommand("contract", "Player contract & fun salary facts"),
    BotCommand("lineup", "Subscribe to gameday lineup notifications"),
    BotCommand("roster", "Recent Nationals roster moves"),
    BotCommand("highlights", "Recent Nationals video highlights"),
    BotCommand("scores", "Live MLB scores"),
    BotCommand("leave", "Should you leave? (e.g. /leave nationals)"),
    BotCommand("standings", "MLB division standings"),
    BotCommand("stats", "Advanced statistics"),
    BotCommand("help", "Show all commands"),
]


async def _post_init(application: Application) -> None:
    """Register bot commands so Telegram shows the menu button."""
    await application.bot.set_my_commands(_BOT_COMMANDS)
    logger.info("Bot commands registered")


def main():
    """Initialize and run the bot."""
    # Validate configuration
    validate_config()
    logger.info("Configuration validated successfully")

    # Create application
    application = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # Load leave-calculator stats in the background while the bot starts up
    threading.Thread(target=_load_leave_stats, daemon=True).start()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("sch", nats_schedule))
    application.add_handler(CommandHandler("past", get_past_games))
    application.add_handler(CommandHandler("splits", splits_command))
    application.add_handler(CommandHandler("contract", contract_command))
    application.add_handler(CommandHandler("lineup", lineup_command))
    application.add_handler(CommandHandler("roster", roster_command))
    application.add_handler(CommandHandler("highlights", highlights_command))
    application.add_handler(CommandHandler("standings", standings_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("leave", leave_game))
    application.add_handler(CommandHandler("scores", live_scores))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(standings_callback, pattern="^standings_"))
    application.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats_"))

    # Inline query handler
    application.add_handler(InlineQueryHandler(inline_query))

    # Set up daily job for posting yesterday's scores
    job_queue = application.job_queue
    if job_queue:
        # Parse time from config (format: "HH:MM")
        hour, minute = map(int, DAILY_POST_TIME.split(':'))
        tz = pytz.timezone(TIMEZONE)
        logger.info("Job queue initialized successfully")
        job = job_queue.run_daily(
            mlb_scores,
            time=time(hour, minute, tzinfo=tz)
        )
        logger.info(f"Daily job scheduled: {job}")

        # 9:30 AM CT — yesterday's score + today's game preview (if applicable)
        async def post_morning_update(context) -> None:
            await post_yesterday_to_channel(context)
            await post_gameday_preview(context)

        morning_job = job_queue.run_daily(
            post_morning_update,
            time=time(9, 30, tzinfo=tz)
        )
        logger.info(f"Morning update job scheduled: {morning_job}")

        # Wednesday 12:30 PM EST (11:30 AM CT) — highlights
        async def post_weekly_highlights(context) -> None:
            if not LINEUP_CHANNEL_ID:
                return
            try:
                text = await get_nationals_highlights()
                await context.bot.send_message(
                    chat_id=LINEUP_CHANNEL_ID,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
                logger.info("Posted weekly highlights to channel")
            except Exception as e:
                logger.error(f"Error posting weekly highlights: {e}")

        highlights_job = job_queue.run_daily(
            post_weekly_highlights,
            time=time(11, 30, tzinfo=tz),  # 11:30 AM CT = 12:30 PM ET
            days=(3,),                      # Wednesday only (0=Sun … 3=Wed)
        )
        logger.info(f"Weekly highlights job scheduled: {highlights_job}")

        # Monday 9:00 AM CT — NL East standings
        monday_standings_job = job_queue.run_daily(
            post_monday_standings,
            time=time(9, 0, tzinfo=tz),
            days=(1,),  # Monday only (0=Sun … 1=Mon)
        )
        logger.info(f"Monday standings job scheduled: {monday_standings_job}")

        # Friday 6:00 PM CT — weekly news digest
        async def post_weekly_digest(context) -> None:
            if not LINEUP_CHANNEL_ID:
                return
            try:
                text = await get_weekly_digest()
                if not text:
                    logger.info("No news items this week — skipping weekly digest post")
                    return
                await context.bot.send_message(
                    chat_id=LINEUP_CHANNEL_ID,
                    text=text,
                    parse_mode="HTML",
                )
                logger.info("Posted weekly digest to channel")
            except Exception as e:
                logger.error(f"Error posting weekly digest: {e}")

        weekly_job = job_queue.run_daily(
            post_weekly_digest,
            time=time(18, 0, tzinfo=tz),
            days=(5,),  # Friday only (0=Sun … 5=Fri)
        )
        logger.info(f"Weekly digest job scheduled: {weekly_job}")

        # Every 30 min — transaction alerts
        async def check_transactions(context) -> None:
            if not LINEUP_CHANNEL_ID:
                return
            try:
                new = await asyncio.to_thread(fetch_new_transactions)
                if not new:
                    return
                lines = ["<b>🔔 Nationals Transaction Alert</b>", ""]
                lines.extend(f"• {desc}" for desc in new)
                await context.bot.send_message(
                    chat_id=LINEUP_CHANNEL_ID,
                    text="\n".join(lines),
                    parse_mode="HTML",
                )
                logger.info(f"Posted {len(new)} transaction alert(s) to channel")
            except Exception as e:
                logger.error(f"Error posting transaction alerts: {e}")

        transaction_job = job_queue.run_repeating(
            check_transactions,
            interval=1800,  # every 30 minutes
            first=90,
        )
        logger.info(f"Transaction alert job scheduled: {transaction_job}")

        # Every 10 min — lineup notifications
        lineup_job = job_queue.run_repeating(
            check_and_notify,
            interval=600,
            first=60,
        )
        logger.info(f"Lineup polling job scheduled: {lineup_job}")
    else:
        logger.error("Failed to initialize job queue")

    # Start bot
    logger.info("Starting bot polling...")
    application.run_polling()

if __name__ == '__main__':
    main()


