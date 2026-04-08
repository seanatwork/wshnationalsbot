"""Player lookup, splits, and contract data."""
import asyncio
import re
import time
import requests
import statsapi
from datetime import date, timedelta
from typing import Optional

from logger import get_logger

logger = get_logger(__name__)

_BREF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

_cache: dict[str, tuple[float, object]] = {}

def _get_cached(key: str, ttl: float):
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < ttl:
        return entry[1]
    return None

def _set_cached(key: str, value) -> None:
    _cache[key] = (time.monotonic(), value)

_TTL_SPLITS = 1800    # 30 min
_TTL_CONTRACT = 3600  # 1 hour

BASE_URL = "https://statsapi.mlb.com/api/v1"

PITCHER_POSITIONS = {"P", "SP", "RP", "CL"}


# ---------------------------------------------------------------------------
# Player lookup
# ---------------------------------------------------------------------------

def _lookup_player(name: str) -> Optional[dict]:
    """Return the best-matching active player dict, or None."""
    results = statsapi.lookup_player(name)
    if not results:
        return None
    # Prefer active / most recently active players
    active = [p for p in results if p.get("active")]
    return (active or results)[0]


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------

def _current_season() -> int:
    today = date.today()
    return today.year if today.month >= 3 else today.year - 1


def _fetch_split(player_id: int, group: str, stat_type: str,
                 extra_params: dict | None = None) -> Optional[dict]:
    """Fetch a single stat split block from the MLB API. Returns the stat dict or None."""
    params = {
        "stats": stat_type,
        "group": group,
        "season": _current_season(),
        "sportId": 1,
    }
    if extra_params:
        params.update(extra_params)
    try:
        resp = requests.get(f"{BASE_URL}/people/{player_id}/stats", params=params, timeout=15)
        resp.raise_for_status()
        for stat_group in resp.json().get("stats", []):
            splits = stat_group.get("splits", [])
            if splits:
                return splits[0].get("stat", {})
    except Exception as e:
        logger.warning(f"Split fetch failed ({stat_type}): {e}")
    return None


def _fetch_date_range_stat(player_id: int, group: str, days: int) -> Optional[dict]:
    end = date.today()
    start = end - timedelta(days=days)
    return _fetch_split(player_id, group, "byDateRange", {
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d"),
    })


def _fetch_handedness_splits(player_id: int, group: str) -> tuple[Optional[dict], Optional[dict]]:
    """Return (vsLeft stats, vsRight stats)."""
    params = {
        "stats": "vsLeft,vsRight",
        "group": group,
        "season": _current_season(),
        "sportId": 1,
    }
    vs_left = vs_right = None
    try:
        resp = requests.get(f"{BASE_URL}/people/{player_id}/stats", params=params, timeout=15)
        resp.raise_for_status()
        for stat_group in resp.json().get("stats", []):
            split_type = stat_group.get("type", {}).get("displayName", "")
            splits = stat_group.get("splits", [])
            if not splits:
                continue
            stat = splits[0].get("stat", {})
            if "vsLeft" in split_type or split_type == "vsLeft":
                vs_left = stat
            elif "vsRight" in split_type or split_type == "vsRight":
                vs_right = stat
    except Exception as e:
        logger.warning(f"Handedness split fetch failed: {e}")
    return vs_left, vs_right


def _fetch_home_away(player_id: int, group: str) -> tuple[Optional[dict], Optional[dict]]:
    """Return (home stats, away stats)."""
    params = {
        "stats": "homeAndAway",
        "group": group,
        "season": _current_season(),
        "sportId": 1,
    }
    home = away = None
    try:
        resp = requests.get(f"{BASE_URL}/people/{player_id}/stats", params=params, timeout=15)
        resp.raise_for_status()
        for stat_group in resp.json().get("stats", []):
            for split in stat_group.get("splits", []):
                loc = split.get("isHome")
                stat = split.get("stat", {})
                if loc is True:
                    home = stat
                elif loc is False:
                    away = stat
    except Exception as e:
        logger.warning(f"Home/away split fetch failed: {e}")
    return home, away


def _fmt_hit(stat: Optional[dict], label: str) -> str:
    if not stat:
        return f"{label}: —"
    avg = stat.get("avg", ".---")
    obp = stat.get("obp", ".---")
    slg = stat.get("slg", ".---")
    pa  = stat.get("plateAppearances", stat.get("atBats", "?"))
    return f"{label}: <b>{avg}/{obp}/{slg}</b> ({pa} PA)"


def _fmt_pit(stat: Optional[dict], label: str) -> str:
    if not stat:
        return f"{label}: —"
    era  = stat.get("era", "-.--")
    whip = stat.get("whip", "-.--")
    ip   = stat.get("inningsPitched", "?.?")
    k    = stat.get("strikeOuts", "?")
    return f"{label}: <b>ERA {era}</b>  WHIP {whip}  {ip} IP  {k}K"


def _build_splits_message(player: dict) -> str:
    pid   = player["id"]
    name  = player["fullName"]
    pos   = player.get("primaryPosition", {}).get("abbreviation", "")
    season = _current_season()
    is_pitcher = pos in PITCHER_POSITIONS
    group = "pitching" if is_pitcher else "hitting"
    fmt   = _fmt_pit if is_pitcher else _fmt_hit

    vs_left, vs_right = _fetch_handedness_splits(pid, group)
    home, away        = _fetch_home_away(pid, group)
    last7  = _fetch_date_range_stat(pid, group, 7)
    last15 = _fetch_date_range_stat(pid, group, 15)
    last30 = _fetch_date_range_stat(pid, group, 30)

    lines = [
        f"<b>⚾ {name} — {season} Splits</b>",
        f"<i>{pos}</i>",
        "",
        "<b>vs. Handedness</b>",
        fmt(vs_left,  "vs LHP" if not is_pitcher else "vs LHB"),
        fmt(vs_right, "vs RHP" if not is_pitcher else "vs RHB"),
        "",
        "<b>Home / Away</b>",
        fmt(home, "🏠 Home"),
        fmt(away, "✈️ Away"),
        "",
        "<b>Recent</b>",
        fmt(last7,  "Last  7d"),
        fmt(last15, "Last 15d"),
        fmt(last30, "Last 30d"),
    ]
    return "\n".join(lines)


async def get_splits(name: str) -> str:
    cache_key = f"splits_{name.lower()}_{date.today()}"
    cached = _get_cached(cache_key, _TTL_SPLITS)
    if cached:
        return cached

    player = await asyncio.to_thread(_lookup_player, name)
    if not player:
        return f"Player not found: <b>{name}</b>\n\nTry using their full last name or full name."

    result = await asyncio.to_thread(_build_splits_message, player)
    _set_cached(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Contract / Salary — sourced from Baseball Reference
# ---------------------------------------------------------------------------

def _bref_id_candidates(full_name: str) -> list[str]:
    """
    Generate candidate Baseball Reference player IDs from a full name.
    Pattern: first 5 chars of last name + first 2 chars of first name + 01/02/03
    e.g. "CJ Abrams" → ["abramcj01", "abramcj02"]
    """
    parts = full_name.strip().split()
    if len(parts) < 2:
        return []
    first = re.sub(r"[^a-z]", "", parts[0].lower())
    last  = re.sub(r"[^a-z]", "", parts[-1].lower())
    stem  = (last[:5] + first[:2]).ljust(7, "a")
    return [f"{stem}0{n}" for n in range(1, 4)]


def _fetch_bref_salary(full_name: str) -> tuple[Optional[int], Optional[str]]:
    """
    Scrape Baseball Reference for current season salary and contract note.
    Returns (salary_int_or_None, contract_note_or_None).
    """
    season = str(_current_season())
    candidates = _bref_id_candidates(full_name)

    for bref_id in candidates:
        url = f"https://www.baseball-reference.com/players/{bref_id[0]}/{bref_id}.shtml"
        try:
            resp = requests.get(url, headers=_BREF_HEADERS, timeout=15)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"BBRef fetch failed for {bref_id}: {e}")
            continue

        html = resp.text

        # Verify we landed on the right player (name check)
        if full_name.split()[-1].lower() not in html.lower():
            continue

        # Extract salary for current season from the salary table
        # Rows look like: data-year="2026" ... data-amount="4200000"
        salary_pattern = re.compile(
            r'data-year="' + re.escape(season) + r'"[^>]*data-amount="([0-9.]+)"'
            r'|data-amount="([0-9.]+)"[^>]*data-year="' + re.escape(season) + r'"'
        )
        m = salary_pattern.search(html)
        salary = None
        if m:
            raw = m.group(1) or m.group(2)
            try:
                salary = int(float(raw))
            except ValueError:
                pass

        # Extract contract summary line e.g. "Signed thru 2028, 6 yr/$115M"
        contract_note = None
        note_m = re.search(
            r"(Signed thru[^<]{5,60}|Free Agent|Pre-Arb|Arbitration eligible[^<]{0,40})",
            html,
        )
        if note_m:
            contract_note = note_m.group(1).strip()

        return salary, contract_note

    # Fallback: try BBRef search redirect
    try:
        search_resp = requests.get(
            "https://www.baseball-reference.com/search/search.fcgi",
            params={"search": full_name},
            headers=_BREF_HEADERS,
            timeout=15,
            allow_redirects=True,
        )
        if search_resp.status_code == 200 and "/players/" in search_resp.url:
            html = search_resp.text
            salary_pattern = re.compile(
                r'data-year="' + re.escape(season) + r'"[^>]*data-amount="([0-9.]+)"'
                r'|data-amount="([0-9.]+)"[^>]*data-year="' + re.escape(season) + r'"'
            )
            m = salary_pattern.search(html)
            salary = None
            if m:
                raw = m.group(1) or m.group(2)
                try:
                    salary = int(float(raw))
                except ValueError:
                    pass
            note_m = re.search(
                r"(Signed thru[^<]{5,60}|Free Agent|Pre-Arb|Arbitration eligible[^<]{0,40})",
                html,
            )
            contract_note = note_m.group(1).strip() if note_m else None
            return salary, contract_note
    except Exception as e:
        logger.debug(f"BBRef search fallback failed: {e}")

    return None, None


def _fetch_season_stats(player_id: int, group: str) -> Optional[dict]:
    """Fetch season totals for fun-fact math."""
    try:
        resp = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={"stats": "season", "group": group,
                    "season": _current_season(), "sportId": 1},
            timeout=15,
        )
        resp.raise_for_status()
        for sg in resp.json().get("stats", []):
            splits = sg.get("splits", [])
            if splits:
                return splits[0].get("stat", {})
    except Exception as e:
        logger.debug(f"Season stats fetch failed: {e}")
    return None


def _per(salary: int, denom, unit: str) -> Optional[str]:
    """Format a $/unit fun fact. Returns None if denom is 0 or None."""
    try:
        d = float(denom)
        if d <= 0:
            return None
        return f"${salary / d:,.0f} per {unit}"
    except (TypeError, ValueError):
        return None


def _build_contract_message(player: dict) -> str:
    name   = player["fullName"]
    pos    = player.get("primaryPosition", {}).get("abbreviation", "")
    season = _current_season()
    is_pitcher = pos in PITCHER_POSITIONS
    group  = "pitching" if is_pitcher else "hitting"
    pid    = player["id"]

    salary, contract_note = _fetch_bref_salary(name)
    stats  = _fetch_season_stats(pid, group)

    lines = [f"<b>💰 {name} — {season} Contract</b>", f"<i>{pos}</i>", ""]

    if contract_note:
        lines.append(f"<i>{contract_note}</i>")
        lines.append("")

    if salary:
        lines.append(f"<b>{season} salary: ${salary:,}</b>")
        lines.append("")
        lines.append("<b>Did you know?</b>")

        facts = []
        if stats:
            if is_pitcher:
                facts.append(_per(salary, stats.get("inningsPitched"), "inning pitched"))
                facts.append(_per(salary, stats.get("strikeOuts"),     "strikeout"))
                facts.append(_per(salary, stats.get("gamesStarted") or stats.get("gamesPitched"), "game"))
            else:
                facts.append(_per(salary, stats.get("gamesPlayed"),  "game played"))
                facts.append(_per(salary, stats.get("hits"),         "hit"))
                hrs = stats.get("homeRuns", 0)
                if hrs and int(hrs) > 0:
                    facts.append(_per(salary, hrs, "home run"))
                facts.append(_per(salary, stats.get("atBats"),       "at-bat"))

        facts.append(f"${salary / 365:,.0f} per day (including off-season)")

        for f in facts:
            if f:
                lines.append(f"• {f}")

        if not any(facts):
            lines.append("• Season stats not yet available for per-stat breakdowns.")
    else:
        lines.append("Salary data not found on Baseball Reference for this player.")
        lines.append("")
        if stats:
            lines.append("<b>Season stats so far:</b>")
            if is_pitcher:
                lines.append(f"• {stats.get('inningsPitched', '?')} IP, "
                             f"{stats.get('strikeOuts', '?')}K, "
                             f"ERA {stats.get('era', '?')}")
            else:
                lines.append(f"• {stats.get('gamesPlayed', '?')} G, "
                             f"{stats.get('avg', '.000')} AVG, "
                             f"{stats.get('homeRuns', '?')} HR, "
                             f"{stats.get('rbi', '?')} RBI")

    lines.append("")
    lines.append("<i>Salary data via Baseball Reference</i>")
    return "\n".join(lines)


async def get_contract(name: str) -> str:
    cache_key = f"contract_{name.lower()}_{date.today()}"
    cached = _get_cached(cache_key, _TTL_CONTRACT)
    if cached:
        return cached

    player = await asyncio.to_thread(_lookup_player, name)
    if not player:
        return f"Player not found: <b>{name}</b>\n\nTry using their full last name or full name."

    result = await asyncio.to_thread(_build_contract_message, player)
    _set_cached(cache_key, result)
    return result
