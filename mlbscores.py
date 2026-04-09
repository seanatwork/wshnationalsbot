"""MLB API integration and command handlers."""
import asyncio
import time
import statsapi
import pytz
import requests
from datetime import datetime, date, timedelta
from typing import Optional

from logger import get_logger
from config import CHAT_ID, NATIONALS_TEAM_ID, TIMEZONE, LINEUP_CHANNEL_ID

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Simple TTL cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}


def _get_cached(key: str, ttl: float):
    """Return cached value if still fresh, else None."""
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < ttl:
        return entry[1]
    return None


def _set_cached(key: str, value) -> None:
    _cache[key] = (time.monotonic(), value)


# Cache TTLs in seconds
_TTL_STANDINGS = 300   # 5 minutes
_TTL_SCHEDULE = 300    # 5 minutes
_TTL_PAST = 300        # 5 minutes
_TTL_LIVE = 30         # 30 seconds

# Division codes mapping
DIVISIONS = {
    'nlwest': ('nlw', 'NL West'),
    'nleast': ('nle', 'NL East'),
    'nlcentral': ('nlc', 'NL Central'),
    'alwest': ('alw', 'AL West'),
    'aleast': ('ale', 'AL East'),
    'alcentral': ('alc', 'AL Central'),
}


def game_summary(game: dict) -> str:
    """Format a completed game with full details."""
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


def game_summary_short(game: dict) -> str:
    """Format a completed game with short summary."""
    if game['status'] != 'Final':
        return f"{game['summary']}\n\n"
    return (
        f"<b>{game['winning_team']} win</b>\n"
        f"{game['summary']}\n"
        f"<i>Series: {game['series_status']}</i>\n\n"
    )


def get_yesterday_scores(team_id: int) -> Optional[str]:
    """Get yesterday's game scores for a team."""
    yesterday = date.today() - timedelta(days=1)
    cache_key = f"yesterday_{team_id}_{yesterday}"
    cached = _get_cached(cache_key, _TTL_PAST)
    if cached is not None:
        return cached
    sched = statsapi.schedule(team=team_id, date=yesterday)
    if len(sched) == 0:
        logger.info('No game yesterday')
        return None
    message = ""
    for game in sched:
        message += game_summary(game)
    _set_cached(cache_key, message)
    return message


def mlb_scores(context) -> None:
    """Daily job: post yesterday's Nationals scores to the main chat."""
    try:
        message = get_yesterday_scores(NATIONALS_TEAM_ID)
        if message is not None:
            context.bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode="HTML",
            )
        else:
            logger.info('No Nationals game yesterday to post')
    except Exception as e:
        logger.error(f"Error posting daily scores: {e}")


def _get_gameday_preview_text() -> Optional[str]:
    """Build a game day preview for today's Nationals game, or None if no game."""
    today = date.today().strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/schedule",
            params={
                "teamId": NATIONALS_TEAM_ID,
                "startDate": today,
                "endDate": today,
                "sportId": 1,
                "hydrate": "probablePitcher,broadcasts(all),linescore,team",
            },
            timeout=15,
        )
        resp.raise_for_status()
        dates = resp.json().get("dates", [])
        if not dates:
            return None

        game = dates[0]["games"][0]
        teams  = game.get("teams", {})
        away   = teams.get("away", {})
        home   = teams.get("home", {})
        away_name = away.get("team", {}).get("name", "Away")
        home_name = home.get("team", {}).get("name", "Home")
        is_home = home.get("team", {}).get("id") == NATIONALS_TEAM_ID
        opponent = away_name if is_home else home_name

        # First pitch time
        game_dt_str = game.get("gameDate", "")
        time_str = ""
        try:
            game_dt = datetime.strptime(game_dt_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            local   = game_dt.astimezone(pytz.timezone(TIMEZONE))
            hour    = local.hour % 12 or 12
            minute  = local.strftime("%M")
            am_pm   = local.strftime("%p")
            tz_abbr = local.tzname() or "CT"
            time_str = f"{hour}:{minute} {am_pm} {tz_abbr}"
        except Exception:
            pass

        # Probable pitchers
        away_pitcher = away.get("probablePitcher", {}).get("fullName", "TBD")
        home_pitcher = home.get("probablePitcher", {}).get("fullName", "TBD")

        # Broadcasts
        broadcasts = game.get("broadcasts", [])
        tv = [b["name"] for b in broadcasts if b.get("type") == "TV"]
        tv_str = " · ".join(tv) if tv else "Check local listings"

        home_away = "🏠 Home" if is_home else "✈️ Away"

        lines = [
            f"<b>⚾ Game Day — {home_away}</b>",
            f"<b>Nationals vs {opponent}</b>",
            f"<i>First pitch: {time_str}</i>",
            "",
            "<b>Probable Pitchers</b>",
            f"• {away_name}: {away_pitcher}",
            f"• {home_name}: {home_pitcher}",
            "",
            f"<b>📺</b> {tv_str}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error building game day preview: {e}")
        return None


async def post_gameday_preview(context) -> None:
    """Daily job: post game day preview to channel at 9 AM CT if there's a game."""
    if not LINEUP_CHANNEL_ID:
        return
    try:
        text = await asyncio.to_thread(_get_gameday_preview_text)
        if text:
            await context.bot.send_message(
                chat_id=LINEUP_CHANNEL_ID,
                text=text,
                parse_mode="HTML",
            )
            logger.info("Posted game day preview to channel")
        else:
            logger.info("No game today — skipping preview post")
    except Exception as e:
        logger.error(f"Error posting game day preview: {e}")


async def post_monday_standings(context) -> None:
    """Weekly job: post NL East standings to channel every Monday morning."""
    if not LINEUP_CHANNEL_ID:
        return
    try:
        text = await asyncio.to_thread(_format_standings, "nle")
        header = "<b>⚾ Monday Morning Standings</b>\n\n"
        await context.bot.send_message(
            chat_id=LINEUP_CHANNEL_ID,
            text=header + text,
            parse_mode="HTML",
        )
        logger.info("Posted Monday standings to channel")
    except Exception as e:
        logger.error(f"Error posting Monday standings: {e}")


async def post_yesterday_to_channel(context) -> None:
    """Daily job: post yesterday's Nationals result + condensed game link to the lineup channel at 9:30 AM CT."""
    if not LINEUP_CHANNEL_ID:
        return
    try:
        message = await asyncio.to_thread(get_yesterday_scores, NATIONALS_TEAM_ID)
        if message is not None:
            # Try to get condensed game link
            condensed_link = await asyncio.to_thread(_get_condensed_game_link)
            if condensed_link:
                message += f"\n\n📹 <a href=\"{condensed_link}\">Watch Condensed Game</a>"
            
            await context.bot.send_message(
                chat_id=LINEUP_CHANNEL_ID,
                text=message,
                parse_mode="HTML",
            )
            logger.info("Posted yesterday's scores to channel")
        else:
            logger.info("No Nationals game yesterday — skipping channel post")
    except Exception as e:
        logger.error(f"Error posting yesterday's scores to channel: {e}")


def _get_condensed_game_link() -> Optional[str]:
    """Get the condensed game MP4 link from yesterday's Nationals game."""
    yesterday = date.today() - timedelta(days=1)
    try:
        # Get yesterday's game
        sched = statsapi.schedule(team=NATIONALS_TEAM_ID, date=yesterday)
        if not sched:
            return None
        
        game = sched[0]
        game_pk = game.get('game_id') or game.get('gamePk')
        if not game_pk:
            return None
        
        # Fetch game content to find condensed game
        base_url = "https://statsapi.mlb.com/api/v1"
        content_url = f"{base_url}/game/{game_pk}/content"
        
        resp = requests.get(content_url, timeout=15)
        resp.raise_for_status()
        content_data = resp.json()
        
        # Look for condensed game in highlights or editorial content
        for section in ['highlights', 'editorial']:
            for category in content_data.get(section, {}).values():
                if isinstance(category, dict):
                    for item in category.get('items', []):
                        title = item.get('title', '').lower()
                        headline = item.get('headline', '').lower()
                        if 'condensed' in title or 'condensed' in headline:
                            # Find best quality MP4
                            for playback in item.get('playbacks', []):
                                if playback.get('name') in ['mp4Avc', 'flash1800k', 'flash1200k']:
                                    return playback.get('url')
                            # Fallback to first available URL
                            if item.get('playbacks'):
                                return item['playbacks'][0].get('url')
        
        return None
    except Exception as e:
        logger.error(f"Error fetching condensed game link: {e}")
        return None


def schedule(team_id: int, user_timezone: str) -> str:
    """Get upcoming schedule for a team."""
    start = date.today()
    cache_key = f"schedule_{team_id}_{start}"
    cached = _get_cached(cache_key, _TTL_SCHEDULE)
    if cached is not None:
        return cached
    end = start + timedelta(days=7)
    sched = statsapi.schedule(team=team_id, start_date=start, end_date=end)
    if not sched:
        return "No schedule found"
    message = ""
    for game in sched:
        message += format_upcoming_game(game, user_timezone)
    _set_cached(cache_key, message)
    return message


def format_upcoming_game(game: dict, user_timezone: str) -> str:
    """Format an upcoming game with local time."""
    game_time = datetime.strptime(game['game_datetime'], '%Y-%m-%dT%H:%M:%SZ') \
                        .replace(tzinfo=pytz.utc) \
                        .astimezone(pytz.timezone(user_timezone))

    tz_abbr = game_time.tzname() or 'UTC'
    hour = game_time.hour % 12 or 12
    minute = game_time.strftime('%M')
    am_pm = game_time.strftime('%p')
    time_str = f"{hour}:{minute} {am_pm}"

    if game_time.date() == date.today():
        game_time_str = f"Today, {time_str} ({tz_abbr})"
    elif game_time.date() == date.today() + timedelta(days=1):
        game_time_str = f"Tomorrow, {time_str} ({tz_abbr})"
    else:
        day_name = game_time.strftime('%a')
        month = game_time.month
        day = game_time.day
        game_time_str = f"{day_name} {month}/{day}, {time_str} ({tz_abbr})"

    return f"<b>{game_time_str}</b> - {game['away_name']} @ {game['home_name']}\n\n"


def get_past_games_scores(team_id: int) -> Optional[str]:
    """Get the last 3 completed games for a team."""
    cache_key = f"past_{team_id}_{date.today()}"
    cached = _get_cached(cache_key, _TTL_PAST)
    if cached is not None:
        return cached

    message = ""
    games_found = 0

    # Search up to 7 days back to find 3 games
    for days_ago in range(1, 8):
        if games_found >= 3:
            break
            
        game_date = date.today() - timedelta(days=days_ago)
        sched = statsapi.schedule(team=team_id, date=game_date)

        if sched:
            for game in sched:
                if games_found < 3:
                    date_str = game_date.strftime("%m/%d/%Y")
                    message += f"<b>{date_str}:</b>\n"
                    message += game_summary_short(game)
                    games_found += 1
                else:
                    break

    result = f"<b>Past {games_found} Nationals Games:</b>\n\n{message}" if message else None
    _set_cached(cache_key, result)
    return result


async def get_past_games(update, context) -> None:
    """Handle /past command - show last 3 Nationals games."""
    message = await asyncio.to_thread(get_past_games_scores, NATIONALS_TEAM_ID)
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
    logger.debug("User checked the past Nationals games")


async def nats_schedule(update, context) -> None:
    """Handle /sch command - show upcoming Nationals schedule."""
    message = await asyncio.to_thread(schedule, NATIONALS_TEAM_ID, TIMEZONE)
    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=message,
        parse_mode="HTML")
    logger.debug("User checked the Nationals schedule")


def _format_standings(division_code: str) -> str:
    """Fetch and format standings for a division."""
    cache_key = f"standings_{division_code}_{date.today()}"
    cached = _get_cached(cache_key, _TTL_STANDINGS)
    if cached is not None:
        return cached
    standings_data = statsapi.standings_data(division=division_code, include_wildcard=False)
    output_lines = []

    for div in standings_data.values():
        output_lines.append(f"<b>{div['div_name']}</b>")
        output_lines.append("")
        
        for i, team in enumerate(div['teams'], start=1):
            gb = team['gb'] if team['gb'] not in ('', '-', None) else '—'
            # Clean mobile format: position. Team Name (W-L) GB: X
            output_lines.append(
                f"{i}. {team['name']} ({team['w']}-{team['l']}) GB: {gb}"
            )
        output_lines.append("")

    result = "\n".join(output_lines).rstrip()
    _set_cached(cache_key, result)
    return result


async def _division_standings(
    update,
    context,
    division_code: str,
    division_name: str
) -> None:
    """Generic handler for division standings commands."""
    standings_text = await asyncio.to_thread(_format_standings, division_code)
    await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=standings_text,
        parse_mode="HTML")
    logger.debug(f"User checked the {division_name} standings")


# Division-specific handlers
async def nlwest_standings(update, context):
    await _division_standings(update, context, 'nlw', 'NL West')


async def nleast_standings(update, context):
    await _division_standings(update, context, 'nle', 'NL East')


async def nlcentral_standings(update, context):
    await _division_standings(update, context, 'nlc', 'NL Central')


async def alwest_standings(update, context):
    await _division_standings(update, context, 'alw', 'AL West')


async def aleast_standings(update, context):
    await _division_standings(update, context, 'ale', 'AL East')


async def alcentral_standings(update, context):
    await _division_standings(update, context, 'alc', 'AL Central')


def _get_live_scores_text() -> str:
    """Return formatted live MLB scores as an HTML string."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    base_url = "https://statsapi.mlb.com/api/v1"

    cache_key = f"live_scores_{today}"
    cached_msg = _get_cached(cache_key, _TTL_LIVE)
    if cached_msg is not None:
        return cached_msg

    resp = requests.get(
        f"{base_url}/schedule",
        params={
            "sportId": 1,
            "startDate": yesterday.strftime("%Y-%m-%d"),
            "endDate": today.strftime("%Y-%m-%d"),
            "gameType": "R",
            "hydrate": "linescore",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    live_games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {})
            if status.get("abstractGameState") != "Live":
                continue
            teams = game.get("teams", {})
            away_name = teams.get("away", {}).get("team", {}).get("name", "")
            home_name = teams.get("home", {}).get("team", {}).get("name", "")
            linescore = game.get("linescore", {})
            away_score = linescore.get("teams", {}).get("away", {}).get("runs", 0) or teams.get("away", {}).get("score", 0)
            home_score = linescore.get("teams", {}).get("home", {}).get("runs", 0) or teams.get("home", {}).get("score", 0)
            live_games.append({
                "away_team": away_name,
                "home_team": home_name,
                "away_score": away_score,
                "home_score": home_score,
                "inning": linescore.get("currentInning", 0),
                "inning_half": linescore.get("inningHalf", ""),
                "status": status.get("detailedState", ""),
            })

    if not live_games:
        return "No live MLB games currently in progress."

    message = "<b>📺 Live MLB Games:</b>\n\n"
    for game in live_games:
        half_str = f" ({game['inning_half']})" if game['inning_half'] else ""
        message += (
            f"<b>{game['away_team']} {game['away_score']} @ "
            f"{game['home_team']} {game['home_score']}</b>\n"
            f"Inning: {game['inning']}{half_str} | {game['status']}\n\n"
        )

    _set_cached(cache_key, message)
    return message


async def live_scores(update, context) -> None:
    """Handle /scores command - show all live MLB games."""
    try:
        message = await asyncio.to_thread(_get_live_scores_text)
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=message,
            parse_mode="HTML"
        )
        logger.debug("User checked live MLB scores")
    except Exception as e:
        logger.error(f"Error fetching live scores: {e}")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="Sorry, I couldn't fetch live scores right now. Please try again later.",
            parse_mode="HTML"
        )
