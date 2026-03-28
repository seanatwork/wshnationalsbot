import statsapi
import pytz
import os
from datetime import datetime, date, timedelta

from logger import get_logger

logger = get_logger(__name__)


# team_id = 120  # Nationals


def game_summary(game):
    if game['status'] != 'Final':
        return f"{game['summary']}\n\n"
    try:
        wp_s = f"<b>WP:</b> {game['winning_pitcher']}\n"
    except KeyError:
        wp_s = ''
    try:
        lp_s = f"<b>LP:</b> {game['losing_pitcher']}\n"
    except KeyError:
        lp_s = ''
    try:
        sv_s = f"<b>SV:</b> {game['save_pitcher']}\n"
    except KeyError:
        sv_s = ''
    return (
        f"<b>{game['summary']}</b>\n\n"
        f"<code>{statsapi.linescore(game['game_id'])}</code>\n\n"
        f"{wp_s}{lp_s}{sv_s}<i>Series: {game['series_status']}</i>\n\n"
    )


def game_summary_short(game):
    if game['status'] != 'Final':
        return f"{game['summary']}\n\n"
    return (
        f"<b>{game['winning_team']} win</b>\n"
        f"{game['summary']}\n"
        f"<i>Series: {game['series_status']}</i>\n"
    )

def get_yesterday_scores(team_id):
    yesterday = date.today() - timedelta(days=1)

    sched = statsapi.schedule(team=team_id, date=yesterday)
    if len(sched) == 0:
        logger.info('No game yesterday')
        return None
    
    else:
        message = ""
        for game in sched:
            message += game_summary(game)
        return(message)


def mlb_scores(context):
    try:
        message = get_yesterday_scores(120)
        if message is not None:
            context.bot.send_message(
                chat_id='@natsdc',
                # chat_id=109750799,
                text=message,
                parse_mode="HTML",
            )
        else:
            logger.info('No Nationals game yesterday to post')
    except Exception as e:
        logger.error(f"Error posting daily scores: {e}")


def schedule(team_id, user_timezone):
    start = date.today()
    end = start + timedelta(days=4)
    sched = statsapi.schedule(team=team_id, start_date=start, end_date=end)
    if not sched:
        return "No schedule found"
    message = ""
    for game in sched:
        message += format_upcoming_game(game, user_timezone)
    return message


def format_upcoming_game(game, user_timezone):
    game_time = datetime.strptime(game['game_datetime'], '%Y-%m-%dT%H:%M:%SZ') \
                        .replace(tzinfo=pytz.utc) \
                        .astimezone(pytz.timezone(user_timezone))
    
    # Get timezone abbreviation
    tz_abbr = game_time.tzname() or 'UTC'
    
    # Format time in a cross-platform way
    hour = game_time.hour % 12 or 12  # Convert 24-hour to 12-hour format
    minute = game_time.strftime('%M')
    am_pm = game_time.strftime('%p')
    time_str = f"{hour}:{minute} {am_pm}"
    
    if game_time.date() == date.today():
        game_time = f"Today, {time_str} ({tz_abbr})"
    elif game_time.date() == date.today() + timedelta(days=1):
        game_time = f"Tomorrow, {time_str} ({tz_abbr})"
    else:
        day_name = game_time.strftime('%a')
        month = game_time.month
        day = game_time.day
        game_time = f"{day_name} {month}/{day}, {time_str} ({tz_abbr})"
    
    return f"<b>{game_time}</b> - {game['away_name']} @ {game['home_name']}\n\n"


async def get_past_games(update, context):
    message = get_past_games_scores(120)
    if message:
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=message,
            parse_mode="HTML")
    else:
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="No recent games found for the Nationals.",
            parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the past Nationals games")


def get_past_games_scores(team_id):
    message = ""
    games_found = 0
    
    # Check the past 3 days for games
    for days_ago in range(1, 4):
        game_date = date.today() - timedelta(days=days_ago)
        sched = statsapi.schedule(team=team_id, date=game_date)
        
        if sched:
            for game in sched:
                if games_found < 3:
                    # Add date header
                    date_str = game_date.strftime("%m/%d/%Y")
                    message += f"<b>{date_str}:</b>\n"
                    message += game_summary_short(game)
                    games_found += 1
    
    if not message:
        return None
    
    return f"<b>Past 3 Nationals Games:</b>\n\n{message}"


async def nats_schedule(update, context):
    message = schedule(120, 'America/Chicago')
    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the Nationals schedule")


async def nlwest_standings(update, context):
    standings_data = statsapi.standings_data(division='nlw', include_wildcard=False)
    output_lines = []

    for div in standings_data.values():
        output_lines.append(div['div_name'])
        output_lines.append(f"{'Team':<25} {'W':>3} {'L':>3} {'GB':>4}")
        for team in div['teams']:
            # Truncate team name to 25 characters for consistent alignment
            team_name = team['name'][:25]
            output_lines.append(f"{team_name:<25} {team['w']:>3} {team['l']:>3} {team['gb']:>4}")
        output_lines.append("")  # blank line between divisions

    message = "<code>" + "\n".join(output_lines) + "</code>"

    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the NL West standings")


async def nleast_standings(update, context):
    standings_data = statsapi.standings_data(division='nle', include_wildcard=False)
    output_lines = []

    for div in standings_data.values():
        output_lines.append(div['div_name'])
        output_lines.append(f"{'Team':<25} {'W':>3} {'L':>3} {'GB':>4}")
        for team in div['teams']:
            # Truncate team name to 25 characters for consistent alignment
            team_name = team['name'][:25]
            output_lines.append(f"{team_name:<25} {team['w']:>3} {team['l']:>3} {team['gb']:>4}")
        output_lines.append("")  # blank line between divisions

    message = "<code>" + "\n".join(output_lines) + "</code>"

    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the NL East standings")


async def nlcentral_standings(update, context):
    standings_data = statsapi.standings_data(division='nlc', include_wildcard=False)
    output_lines = []

    for div in standings_data.values():
        output_lines.append(div['div_name'])
        output_lines.append(f"{'Team':<25} {'W':>3} {'L':>3} {'GB':>4}")
        for team in div['teams']:
            # Truncate team name to 25 characters for consistent alignment
            team_name = team['name'][:25]
            output_lines.append(f"{team_name:<25} {team['w']:>3} {team['l']:>3} {team['gb']:>4}")
        output_lines.append("")  # blank line between divisions

    message = "<code>" + "\n".join(output_lines) + "</code>"

    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the NL Central standings")


async def alwest_standings(update, context):
    standings_data = statsapi.standings_data(division='alw', include_wildcard=False)
    output_lines = []

    for div in standings_data.values():
        output_lines.append(div['div_name'])
        output_lines.append(f"{'Team':<25} {'W':>3} {'L':>3} {'GB':>4}")
        for team in div['teams']:
            # Truncate team name to 25 characters for consistent alignment
            team_name = team['name'][:25]
            output_lines.append(f"{team_name:<25} {team['w']:>3} {team['l']:>3} {team['gb']:>4}")
        output_lines.append("")  # blank line between divisions

    message = "<code>" + "\n".join(output_lines) + "</code>"

    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the AL West standings")


async def aleast_standings(update, context):
    standings_data = statsapi.standings_data(division='ale', include_wildcard=False)
    output_lines = []

    for div in standings_data.values():
        output_lines.append(div['div_name'])
        output_lines.append(f"{'Team':<25} {'W':>3} {'L':>3} {'GB':>4}")
        for team in div['teams']:
            # Truncate team name to 25 characters for consistent alignment
            team_name = team['name'][:25]
            output_lines.append(f"{team_name:<25} {team['w']:>3} {team['l']:>3} {team['gb']:>4}")
        output_lines.append("")  # blank line between divisions

    message = "<code>" + "\n".join(output_lines) + "</code>"

    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the AL East standings")


async def alcentral_standings(update, context):
    standings_data = statsapi.standings_data(division='alc', include_wildcard=False)
    output_lines = []

    for div in standings_data.values():
        output_lines.append(div['div_name'])
        output_lines.append(f"{'Team':<25} {'W':>3} {'L':>3} {'GB':>4}")
        for team in div['teams']:
            # Truncate team name to 25 characters for consistent alignment
            team_name = team['name'][:25]
            output_lines.append(f"{team_name:<25} {team['w']:>3} {team['l']:>3} {team['gb']:>4}")
        output_lines.append("")  # blank line between divisions

    message = "<code>" + "\n".join(output_lines) + "</code>"

    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug(f"{update.message.chat_id} checked the AL Central standings")
