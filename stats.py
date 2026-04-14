"""Advanced MLB statistics and ABS challenge data."""
import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET
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

        # Append ABS challenge stats
        abs_section = await _get_abs_section()
        if abs_section:
            message += f"\n{abs_section}"

        _set_cached(cache_key, message)
        return message

    except Exception as e:
        logger.error(f"Error fetching team stats: {e}")
        return "Sorry, couldn't fetch team stats right now. Please try again later."


async def _get_abs_section() -> Optional[str]:
    """Return a formatted ABS stats block for embedding into /stats, or None on failure."""
    try:
        resp = await asyncio.to_thread(
            requests.get,
            "https://baseballsavant.mlb.com/abs",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.text

        # Page uses `const` (not `var`) as of 2026
        summary_match = re.search(r"(?:var|const|let)\s+absSummaryData\s*=\s*(\[.*?\]);", html, re.DOTALL)
        if not summary_match:
            return None

        summary = json.loads(summary_match.group(1))
        if not summary:
            return None

        total_challenges = sum(int(d.get("challenges", 0)) for d in summary)
        total_overturns = sum(int(d.get("overturns", 0)) for d in summary)
        if total_challenges == 0:
            return None

        overturn_rate = total_overturns / total_challenges * 100

        rolling_rate = None
        for d in reversed(summary):
            r = d.get("rolling_overturn_rate_week")
            if r is not None:
                rolling_rate = float(r) * 100
                break

        latest_date_raw = summary[-1].get("game_date", "")
        try:
            from datetime import datetime as _dt
            latest_date = _dt.fromisoformat(latest_date_raw.replace("Z", "")).strftime("%b %-d")
        except Exception:
            latest_date = latest_date_raw

        lines = [
            f"<b>ABS Challenge Stats</b>  <i>through {latest_date}</i>",
            f"• League: {total_challenges} challenges · {total_overturns} overturns · <b>{overturn_rate:.1f}%</b> rate",
        ]
        if rolling_rate is not None:
            lines.append(f"• 7-Day Rolling Rate: <b>{rolling_rate:.1f}%</b>")

        # Nationals-specific team data
        team_match = re.search(r"(?:var|const|let)\s+teamData\s*=\s*(\[[\s\S]*?\]);", html)
        if team_match:
            team_data = json.loads(team_match.group(1))
            nats = next((d for d in team_data if str(d.get("id")) == "120"), None)
            if nats:
                bat_for   = int(nats.get("bat_for", 0))
                fld_for   = int(nats.get("fld_for", 0))
                bat_against = int(nats.get("bat_against", 0))
                fld_against = int(nats.get("fld_against", 0))
                wins   = bat_for + fld_for
                losses = bat_against + fld_against
                total  = wins + losses
                nats_rate = wins / total * 100 if total > 0 else 0

                # Rank by wins among all 30 teams
                wins_by_team = sorted(
                    [int(d.get("bat_for", 0)) + int(d.get("fld_for", 0)) for d in team_data],
                    reverse=True,
                )
                nats_rank = wins_by_team.index(wins) + 1

                lines += [
                    "",
                    "<b>Nationals</b>",
                    f"• Batting: {bat_for} won · {bat_against} lost to opponents",
                    f"• Fielding: {fld_for} won · {fld_against} lost to opponents",
                    f"• Overall: {wins} wins · {losses} losses · <b>{nats_rate:.0f}%</b>  (#{nats_rank}/30 MLB)",
                ]

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error fetching ABS stats for /stats: {e}")
        return None


async def get_roster_moves() -> str:
    """Get the most recent Nationals roster transactions."""
    cache_key = f"roster_moves_{date.today()}"
    cached = _get_cached(cache_key, 300)  # 5-min cache
    if cached is not None:
        return cached

    try:
        current_year = date.today().year
        resp = await asyncio.to_thread(
            requests.get,
            f"https://statsapi.mlb.com/api/v1/transactions",
            params={
                "teamId": NATIONALS_TEAM_ID,
                "startDate": (date.today() - timedelta(days=14)).isoformat(),
                "endDate": date.today().isoformat(),
            },
            timeout=15,
        )
        resp.raise_for_status()
        transactions = resp.json().get("transactions", [])

        if not transactions:
            return "<b>⚾ Nationals Roster Moves</b>\n\nNo transactions in the last 14 days."

        # Sort newest first
        transactions.sort(key=lambda t: t.get("date", ""), reverse=True)

        lines = ["<b>⚾ Nationals Recent Roster Moves</b>\n"]
        shown = 0
        last_date = None
        for t in transactions:
            if shown >= 10:
                break
            raw_date = t.get("date", "")
            try:
                d = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%b %-d")
            except Exception:
                d = raw_date
            description = t.get("description", "").strip()
            if not description:
                continue
            if d != last_date:
                lines.append(f"\n<b>{d}</b>")
                last_date = d
            lines.append(f"• {description}")
            shown += 1

        result = "\n".join(lines)
        _set_cached(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Error fetching roster moves: {e}")
        return "Sorry, couldn't fetch roster moves right now. Please try again later."


# Track alerted transaction IDs — resets on restart, which is fine
_alerted_transaction_ids: set = set()
_alerted_date: date | None = None


def fetch_new_transactions() -> list[str]:
    """
    Return descriptions of any transactions posted today that haven't been alerted yet.
    Resets the seen-set daily so IDs don't accumulate across days.
    """
    global _alerted_transaction_ids, _alerted_date
    today = date.today()

    if _alerted_date != today:
        _alerted_transaction_ids = set()
        _alerted_date = today

    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/transactions",
            params={
                "teamId": NATIONALS_TEAM_ID,
                "startDate": today.isoformat(),
                "endDate": today.isoformat(),
            },
            timeout=15,
        )
        resp.raise_for_status()
        transactions = resp.json().get("transactions", [])

        new = []
        for t in transactions:
            tid  = t.get("id") or t.get("description", "")
            desc = t.get("description", "").strip()
            if not desc or tid in _alerted_transaction_ids:
                continue
            _alerted_transaction_ids.add(tid)
            new.append(desc)
        return new
    except Exception as e:
        logger.error(f"Error fetching transactions: {e}")
        return []


def _fetch_nationals_news() -> list[str]:
    """Return headline strings from the MLB.com Nationals RSS feed, last 7 days."""
    try:
        resp = requests.get(
            "https://www.mlb.com/nationals/feeds/news/rss.xml",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        cutoff = date.today() - timedelta(days=7)

        headlines = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            pub   = item.findtext("pubDate") or ""
            # pubDate format: "Mon, 07 Apr 2026 12:00:00 +0000"
            try:
                pub_date = datetime.strptime(pub[:16], "%a, %d %b %Y").date()
                if pub_date < cutoff:
                    continue
            except Exception:
                pass  # include if we can't parse the date
            if title:
                headlines.append(f"• {title}")
            if len(headlines) >= 8:
                break
        return headlines
    except Exception as e:
        logger.error(f"Error fetching Nationals RSS: {e}")
        return []


async def get_weekly_digest() -> str:
    """Build the Friday weekly digest: news headlines only (transactions posted same-day now)."""
    news = await asyncio.to_thread(_fetch_nationals_news)

    today = date.today()
    week_start = (today - timedelta(days=6)).strftime("%b %-d")
    week_end   = today.strftime("%b %-d")

    lines = [
        f"<b>⚾ Nationals Week in Review</b>",
        f"<i>{week_start} – {week_end}</i>",
        "",
        "<b>📰 News &amp; Notes</b>",
    ]

    if news:
        lines.extend(news)
    else:
        lines.append("No news items this week.")

    return "\n".join(lines)
