"""Advanced MLB statistics and ABS challenge data."""
import asyncio
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
    """Get ABS challenge win percentage for Nationals vs league average."""
    cache_key = f"abs_stats_{date.today()}"
    cached = _get_cached(cache_key, _TTL_STATS)
    if cached is not None:
        return cached
    
    try:
        # Get current season
        current_year = date.today().year
        if date.today().month < 3:  # Before March, use previous year
            current_year -= 1
            
        # Get team stats data from MLB API
        base_url = "https://statsapi.mlb.com/api/v1"
        
        # Get team season stats for challenges
        params = {
            "season": current_year,
            "group": "hitting",
            "gameType": "R",  # Regular season
            "fields": "teamStats,stat,team,name,challengeWinPct,challengeAttempts,challengeWins"
        }
        
        resp = await asyncio.to_thread(
            requests.get, f"{base_url}/teams/stats", params=params, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        
        # Parse team stats
        team_stats = {}
        for team_data in data.get('stats', []):
            for team in team_data.get('splits', []):
                team_info = team.get('team', {})
                team_name = team_info.get('name', '')
                team_id = team_info.get('id', 0)
                stat = team.get('stat', {})
                
                if 'challengeWinPct' in stat and stat.get('challengeAttempts', 0) > 0:
                    team_stats[team_id] = {
                        'name': team_name,
                        'win_pct': float(stat['challengeWinPct']),
                        'attempts': stat['challengeAttempts'],
                        'wins': stat['challengeWins']
                    }
        
        if not team_stats:
            return "ABS challenge data not available for current season."
        
        # Calculate league average
        total_wins = sum(team['wins'] for team in team_stats.values())
        total_attempts = sum(team['attempts'] for team in team_stats.values())
        league_avg = (total_wins / total_attempts * 100) if total_attempts > 0 else 0
        
        # Get Nationals stats
        nationals_stats = team_stats.get(NATIONALS_TEAM_ID)
        if not nationals_stats:
            return "Washington Nationals ABS challenge data not available."
        
        nationals_pct = nationals_stats['win_pct']
        diff_from_league = nationals_pct - league_avg
        
        # Format message
        better_worse = "better" if diff_from_league > 0 else "worse"
        emoji = "📈" if diff_from_league > 0 else "📉"
        
        message = f"""
<b>{emoji} ABS Challenge Stats - {current_year} Season</b>

<b>Washington Nationals:</b>
• Success Rate: <b>{nationals_pct:.1f}%</b>
• Challenges: {nationals_stats['attempts']} ({nationals_stats['wins']} wins)

<b>League Average:</b>
• Success Rate: <b>{league_avg:.1f}%</b>
• Total Challenges: {total_attempts} ({total_wins} wins)

<b>Comparison:</b>
• Nationals are <b>{abs(diff_from_league):.1f}% {better_worse}</b> than league average
• Rank: {sum(1 for t in team_stats.values() if t['win_pct'] > nationals_pct) + 1} of {len(team_stats)} teams
"""
        
        _set_cached(cache_key, message)
        return message
        
    except Exception as e:
        logger.error(f"Error fetching ABS stats: {e}")
        return "Sorry, couldn't fetch ABS challenge data right now. Please try again later."
