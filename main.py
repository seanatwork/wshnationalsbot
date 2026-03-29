import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from mlbscores import (
    nats_schedule, mlb_scores,
    nlwest_standings, nleast_standings, nlcentral_standings,
    alwest_standings, aleast_standings, alcentral_standings,
    get_past_games
)
from leave_calculator import build_stats, fetch_live_game, should_leave, _completed_inning
import os
from datetime import time
import pytz
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Loaded once at startup in a background thread
_leave_stats: dict | None = None

def _load_leave_stats() -> None:
    global _leave_stats
    _leave_stats = build_stats()
    print("Leave calculator stats loaded.")

async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

def main():
    # Your bot token here
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Load leave-calculator stats in the background while the bot starts up
    threading.Thread(target=_load_leave_stats, daemon=True).start()

    # Add command handlers
    application.add_handler(CommandHandler("sch", nats_schedule))
    application.add_handler(CommandHandler("past", get_past_games))
    application.add_handler(CommandHandler("nlwest", nlwest_standings))
    application.add_handler(CommandHandler("nleast", nleast_standings))
    application.add_handler(CommandHandler("nlcentral", nlcentral_standings))
    application.add_handler(CommandHandler("alwest", alwest_standings))
    application.add_handler(CommandHandler("aleast", aleast_standings))
    application.add_handler(CommandHandler("alcentral", alcentral_standings))
    application.add_handler(CommandHandler("leave", leave_game))
    
    # Set up daily job for posting yesterday's scores at 10 AM Central Time
    job_queue = application.job_queue
    if job_queue:
        print("Job queue initialized successfully")
        job = job_queue.run_daily(mlb_scores, time=time(10, 0, tzinfo=pytz.timezone('America/Chicago')))
        print(f"Daily job scheduled: {job}")
    else:
        print("Failed to initialize job queue")
    
    # Start bot
    application.run_polling()

if __name__ == '__main__':
    main()


