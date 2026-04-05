"""MLB.com video highlights using MLB Stats API."""
import asyncio
import time
import requests
from datetime import date, timedelta
from typing import Optional, List, Dict

from logger import get_logger
from config import NATIONALS_TEAM_ID

logger = get_logger(__name__)

# Cache
_cache: dict[str, tuple[float, object]] = {}
_TTL_HIGHLIGHTS = 300  # 5 minutes

def _get_cached(key: str, ttl: float):
    """Return cached value if still fresh, else None."""
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < ttl:
        return entry[1]
    return None

def _set_cached(key: str, value) -> None:
    _cache[key] = (time.monotonic(), value)

async def get_nationals_highlights() -> Optional[str]:
    """Get 3 most recent Washington Nationals highlights from MLB.com."""
    cache_key = f"highlights_{date.today()}"
    cached = _get_cached(cache_key, _TTL_HIGHLIGHTS)
    if cached is not None:
        return cached
    
    try:
        highlights = []
        
        # Try to get highlights from recent games
        base_url = "https://statsapi.mlb.com/api/v1"
        
        # First, get recent Nationals games
        today = date.today()
        last_week = today - timedelta(days=7)
        
        schedule_params = {
            "sportId": 1,
            "teamId": NATIONALS_TEAM_ID,
            "startDate": last_week.strftime("%Y-%m-%d"),
            "endDate": today.strftime("%Y-%m-%d"),
            "gameType": "R",
            "fields": "dates,games,gamePk,gameDate,status,abstractGameState,teams,home,away,team,name"
        }
        
        resp = await asyncio.to_thread(
            requests.get, f"{base_url}/schedule", params=schedule_params, timeout=15
        )
        resp.raise_for_status()
        schedule_data = resp.json()
        
        # Get game IDs for completed games
        game_ids = []
        for date_entry in schedule_data.get('dates', []):
            for game in date_entry.get('games', []):
                status = game.get('status', {})
                if status.get('abstractGameState') in ['Final', 'Live']:
                    game_ids.append(game.get('gamePk'))
        
        # Fetch highlights for each game
        for game_id in game_ids[:3]:
            if len(highlights) >= 3:
                break
                
            try:
                content_url = f"{base_url}/game/{game_id}/content"
                content_resp = await asyncio.to_thread(
                    requests.get, content_url, timeout=10
                )
                content_resp.raise_for_status()
                content_data = content_resp.json()
                
                # Get highlights from game content
                for highlight in content_data.get('highlights', {}).get('live', {}).get('items', [])[:3]:
                    title = highlight.get('headline', highlight.get('title', 'Highlight'))
                    video_urls = highlight.get('playbacks', [])
                    
                    # Find the best quality MP4 URL
                    video_url = None
                    for playback in video_urls:
                        if playback.get('name') == 'mp4Avc':
                            video_url = playback.get('url')
                            break
                    
                    if not video_url and video_urls:
                        video_url = video_urls[0].get('url')
                    
                    if title and video_url:
                        highlights.append({
                            'title': title,
                            'url': video_url
                        })
                        
                    if len(highlights) >= 3:
                        break
                        
            except Exception as e:
                logger.debug(f"Error fetching highlights for game {game_id}: {e}")
                continue
        
        if not highlights:
            return "No recent Washington Nationals highlights found."
        
        # Format message
        message_lines = ["<b>📺 Recent Washington Nationals Highlights</b>", ""]
        
        for i, highlight in enumerate(highlights[:3], start=1):
            title = highlight['title'][:70] + "..." if len(highlight['title']) > 70 else highlight['title']
            message_lines.append(f"{i}. <a href=\"{highlight['url']}\">{title}</a>")
        
        result = "\n\n".join(message_lines)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        logger.error(f"Error fetching highlights: {e}")
        return "Sorry, couldn't fetch highlights right now. Please try again later."
