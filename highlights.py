"""MLB.com video highlights scraper."""
import asyncio
import time
import requests
from datetime import date
from typing import Optional, List, Dict
from bs4 import BeautifulSoup

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
        # MLB.com video search URL for Nationals
        url = "https://www.mlb.com/video"
        params = {
            "q": "washington nationals",
            "sort": "date"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        resp = await asyncio.to_thread(
            requests.get, url, params=params, headers=headers, timeout=15
        )
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        highlights = []
        
        # Find video cards/containers
        video_elements = soup.find_all('a', href=True)
        
        for element in video_elements:
            href = element.get('href', '')
            # Look for video links
            if '/video/' in href or 'watch' in href:
                # Get title
                title_elem = element.find('h3') or element.find('h2') or element.find('span', class_='title')
                title = title_elem.get_text(strip=True) if title_elem else None
                
                # Get description from alt text or nearby elements
                if not title:
                    img = element.find('img')
                    if img:
                        title = img.get('alt', '')
                
                if title and 'nationals' in title.lower():
                    # Build full URL
                    video_url = href if href.startswith('http') else f"https://www.mlb.com{href}"
                    highlights.append({
                        'title': title,
                        'url': video_url
                    })
                    
                    if len(highlights) >= 3:
                        break
        
        if not highlights:
            # Try alternative approach with MLB Stats API video endpoint
            base_url = "https://statsapi.mlb.com/api/v1"
            video_params = {
                "sportId": 1,
                "teamId": NATIONALS_TEAM_ID,
                "limit": 3,
                "sortBy": "date"
            }
            
            resp = await asyncio.to_thread(
                requests.get, f"{base_url}/video", params=video_params, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            
            for video in data.get('videos', [])[:3]:
                highlights.append({
                    'title': video.get('title', 'Highlight'),
                    'url': video.get('url', f"https://www.mlb.com/video/{video.get('slug', '')}")
                })
        
        if not highlights:
            return "No recent Washington Nationals highlights found."
        
        # Format message
        message_lines = ["<b>📺 Recent Washington Nationals Highlights</b>", ""]
        
        for i, highlight in enumerate(highlights, start=1):
            title = highlight['title'][:60] + "..." if len(highlight['title']) > 60 else highlight['title']
            message_lines.append(f"{i}. <a href=\"{highlight['url']}\">{title}</a>")
        
        result = "\n\n".join(message_lines)
        _set_cached(cache_key, result)
        return result
        
    except Exception as e:
        logger.error(f"Error fetching highlights: {e}")
        return "Sorry, couldn't fetch highlights right now. Please try again later."
