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
