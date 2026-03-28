from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from mlbscores import (
    nats_schedule, mlb_scores,
    nlwest_standings, nleast_standings, nlcentral_standings,
    alwest_standings, aleast_standings, alcentral_standings,
    get_past_games
)
import os
from datetime import time
import pytz
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    # Your bot token here
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("sch", nats_schedule))
    application.add_handler(CommandHandler("past", get_past_games))
    application.add_handler(CommandHandler("nlwest", nlwest_standings))
    application.add_handler(CommandHandler("nleast", nleast_standings))
    application.add_handler(CommandHandler("nlcentral", nlcentral_standings))
    application.add_handler(CommandHandler("alwest", alwest_standings))
    application.add_handler(CommandHandler("aleast", aleast_standings))
    application.add_handler(CommandHandler("alcentral", alcentral_standings))
    
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


