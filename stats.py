"""Advanced MLB statistics and ABS challenge data."""
import asyncio
import json
import re
import time
import statsapi
import requests
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Tuple

from logger import get_logger
from config import NATIONALS_TEAM_ID

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
_TTL_STATS = 3600  # 1 hour for stats

NL_EAST_IDS = {120, 121, 143, 144, 146}  # WSH, NYM, PHI, ATL, MIA

async def get_nationals_team_stats() -> Optional[str]:
    """Get Nationals hitting/pitching stats ranked vs NL East and all of MLB."""
    cache_key = f"team_stats_{date.today()}"
    cached = _get_cached(cache_key, _TTL_STATS)
    if cached is not None:
        return cached

    try:
        current_year = date.today().year
        if date.today().month < 3:
            current_year -= 1

        base_url = "https://statsapi.mlb.com/api/v1"
        params = {"season": current_year, "gameType": "R", "sportId": 1}

        hitting_resp, pitching_resp = await asyncio.gather(
            asyncio.to_thread(requests.get, f"{base_url}/teams/stats",
                              params={**params, "group": "hitting"}, timeout=15),
            asyncio.to_thread(requests.get, f"{base_url}/teams/stats",
                              params={**params, "group": "pitching"}, timeout=15),
        )
        hitting_resp.raise_for_status()
        pitching_resp.raise_for_status()

        def parse_splits(data):
            result = {}
            for group in data.get("stats", []):
                for split in group.get("splits", []):
                    tid = split.get("team", {}).get("id")
                    if tid:
                        result[tid] = split.get("stat", {})
            return result

        hitting = parse_splits(hitting_resp.json())
        pitching = parse_splits(pitching_resp.json())

        nats_hit = hitting.get(NATIONALS_TEAM_ID)
        nats_pit = pitching.get(NATIONALS_TEAM_ID)
        if not nats_hit or not nats_pit:
            return "Nationals stats not available yet for this season."

        games = int(nats_hit.get("gamesPlayed", 0))

        # Rank a stat among all teams (lower rank = better); higher_is_better controls direction
        def rank(stat_key, group, higher_is_better=True):
            teams = hitting if group == "hitting" else pitching
            val = float((nats_hit if group == "hitting" else nats_pit).get(stat_key, 0))
            all_vals = [float(s.get(stat_key, 0)) for s in teams.values()]
            mlb_rank = sorted(all_vals, reverse=higher_is_better).index(val) + 1

            div_vals = {tid: float(teams[tid].get(stat_key, 0))
                        for tid in NL_EAST_IDS if tid in teams}
            div_rank = sorted(div_vals.values(), reverse=higher_is_better).index(val) + 1

            return mlb_rank, div_rank, len(all_vals), len(div_vals)

        def fmt(stat_key, group, higher_is_better=True):
            mlb_r, div_r, mlb_total, div_total = rank(stat_key, group, higher_is_better)
            return f"#{mlb_r}/{mlb_total} MLB · #{div_r}/{div_total} NLE"

        avg  = nats_hit.get("avg", ".000")
        ops  = nats_hit.get("ops", ".000")
        hrs  = nats_hit.get("homeRuns", 0)
        sbs  = nats_hit.get("stolenBases", 0)
        kpct = int(nats_hit.get("strikeOuts", 0))

        era  = nats_pit.get("era", "0.00")
        whip = nats_pit.get("whip", "0.00")
        kp9  = float(nats_pit.get("strikeoutsPer9Inn", 0))
        hrall= nats_pit.get("homeRuns", 0)

        message = (
            f"<b>⚾ Washington Nationals — {current_year} Team Stats</b>\n"
            f"<i>{games} games played</i>\n\n"
            f"<b>Hitting</b>\n"
            f"• AVG: <b>{avg}</b>  {fmt('avg', 'hitting')}\n"
            f"• OPS: <b>{ops}</b>  {fmt('ops', 'hitting')}\n"
            f"• HR: <b>{hrs}</b>  {fmt('homeRuns', 'hitting')}\n"
            f"• SB: <b>{sbs}</b>  {fmt('stolenBases', 'hitting')}\n"
            f"• K's: <b>{kpct}</b>  {fmt('strikeOuts', 'hitting', higher_is_better=False)}\n\n"
            f"<b>Pitching</b>\n"
            f"• ERA: <b>{era}</b>  {fmt('era', 'pitching', higher_is_better=False)}\n"
            f"• WHIP: <b>{whip}</b>  {fmt('whip', 'pitching', higher_is_better=False)}\n"
            f"• K/9: <b>{kp9:.1f}</b>  {fmt('strikeoutsPer9Inn', 'pitching')}\n"
            f"• HR allowed: <b>{hrall}</b>  {fmt('homeRuns', 'pitching', higher_is_better=False)}\n"
        )

        _set_cached(cache_key, message)
        return message

    except Exception as e:
        logger.error(f"Error fetching team stats: {e}")
        return "Sorry, couldn't fetch team stats right now. Please try again later."


async def get_abs_challenge_stats() -> Optional[str]:
    """Get league-wide ABS challenge stats scraped from Baseball Savant."""
    cache_key = f"abs_stats_{date.today()}"
    cached = _get_cached(cache_key, _TTL_STATS)
    if cached is not None:
        return cached

    try:
        resp = await asyncio.to_thread(
            requests.get,
            "https://baseballsavant.mlb.com/abs",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.text

        # Extract the absSummaryData JS variable from the embedded script
        match = re.search(r"var absSummaryData\s*=\s*(\[.*?\]);", html, re.DOTALL)
        if not match:
            return "ABS challenge data not available right now."

        summary = json.loads(match.group(1))
        if not summary:
            return "ABS challenge data not available right now."

        total_challenges = sum(int(d.get("challenges", 0)) for d in summary)
        total_overturns = sum(int(d.get("overturns", 0)) for d in summary)
        if total_challenges == 0:
            return "No ABS challenge data yet for this season."

        overturn_rate = total_overturns / total_challenges * 100

        # Most recent rolling weekly rate (last entry that has it)
        rolling_rate = None
        for d in reversed(summary):
            r = d.get("rolling_overturn_rate_week")
            if r is not None:
                rolling_rate = float(r) * 100
                break

        current_year = date.today().year
        if date.today().month < 3:
            current_year -= 1

        latest_date = summary[-1].get("game_date", "")

        message = (
            f"<b>⚾ ABS Challenge Stats - {current_year} Season</b>\n"
            f"<i>Through {latest_date}</i>\n\n"
            f"<b>Season Totals:</b>\n"
            f"• Challenges: {total_challenges}\n"
            f"• Overturns: {total_overturns}\n"
            f"• Overturn Rate: <b>{overturn_rate:.1f}%</b>\n"
        )
        if rolling_rate is not None:
            message += f"• 7-Day Rolling Rate: <b>{rolling_rate:.1f}%</b>\n"

        _set_cached(cache_key, message)
        return message

    except Exception as e:
        logger.error(f"Error fetching ABS stats: {e}")
        return "Sorry, couldn't fetch ABS challenge data right now. Please try again later."
