#!/usr/bin/env python3
"""
MLB Leave Early Calculator
==========================
Based on the FiveThirtyEight methodology:
https://fivethirtyeight.com/features/take-this-cheat-sheet-to-the-ballpark-to-decide-when-to-leave/

Uses 4 years of real MLB regular season data (2022-2025) to compute actual
comeback probabilities for every (inning, run-deficit) combination. Returns
True if a spectator should leave, False if they should stay.

Usage:
    python leave_calculator.py --team nationals       # live game lookup
    python leave_calculator.py --team "red sox"
    python leave_calculator.py --team NYY
    python leave_calculator.py --score 2 7 --inning 7  # manual entry
    python leave_calculator.py --thresholds            # print comparison table
    python leave_calculator.py --refresh               # re-fetch historical data
    python leave_calculator.py                         # interactive mode
"""

import json
import logging
import sys
import argparse
import requests
from datetime import date
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_FILE = Path(__file__).parent / "mlb_game_data_cache.json"
SEASONS = [2022, 2023, 2024, 2025]
BASE_URL = "https://statsapi.mlb.com/api/v1"

# 5% false-positive tolerance: accept a ≤5% chance of leaving and missing a comeback.
DEFAULT_FP_RATE = 0.05

# FiveThirtyEight lookup table (fallback when historical data is thin)
# Key: inning completed; Value: minimum run deficit to recommend leaving
FTE_THRESHOLDS = {1: 6, 2: 6, 3: 5, 4: 5, 5: 4, 6: 4, 7: 3, 8: 2}

# Minimum number of historical instances required to trust the data over FTE
MIN_SAMPLE = 20

# Common team name aliases -> canonical MLB API team name (case-insensitive keys)
TEAM_ALIASES: dict[str, str] = {
    # Washington
    "nationals": "Washington Nationals", "nats": "Washington Nationals",
    "wsh": "Washington Nationals", "wsn": "Washington Nationals",
    # Atlanta
    "braves": "Atlanta Braves", "atl": "Atlanta Braves",
    # New York Mets
    "mets": "New York Mets", "nym": "New York Mets",
    # New York Yankees
    "yankees": "New York Yankees", "yanks": "New York Yankees", "nyy": "New York Yankees",
    # Boston
    "red sox": "Boston Red Sox", "bos": "Boston Red Sox",
    # Chicago
    "white sox": "Chicago White Sox", "cws": "Chicago White Sox",
    "cubs": "Chicago Cubs", "chc": "Chicago Cubs",
    # Los Angeles
    "dodgers": "Los Angeles Dodgers", "lad": "Los Angeles Dodgers",
    "angels": "Los Angeles Angels", "laa": "Los Angeles Angels",
    # Houston
    "astros": "Houston Astros", "hou": "Houston Astros",
    # San Francisco
    "giants": "San Francisco Giants", "sfg": "San Francisco Giants",
    "sf": "San Francisco Giants", "san francisco": "San Francisco Giants",
    # San Diego
    "padres": "San Diego Padres", "sdp": "San Diego Padres", "sd": "San Diego Padres",
    # Seattle
    "mariners": "Seattle Mariners", "sea": "Seattle Mariners",
    # Texas
    "rangers": "Texas Rangers", "tex": "Texas Rangers",
    # St. Louis
    "cardinals": "St. Louis Cardinals", "cards": "St. Louis Cardinals", "stl": "St. Louis Cardinals", "st louis": "St. Louis Cardinals",
    # Milwaukee
    "brewers": "Milwaukee Brewers", "mil": "Milwaukee Brewers",
    # Philadelphia
    "phillies": "Philadelphia Phillies", "phi": "Philadelphia Phillies", "philly": "Philadelphia Phillies",
    # Pittsburgh
    "pirates": "Pittsburgh Pirates", "pit": "Pittsburgh Pirates",
    # Cincinnati
    "reds": "Cincinnati Reds", "cin": "Cincinnati Reds",
    # Colorado
    "rockies": "Colorado Rockies", "col": "Colorado Rockies",
    # Arizona
    "diamondbacks": "Arizona Diamondbacks", "d-backs": "Arizona Diamondbacks",
    "dbacks": "Arizona Diamondbacks", "ari": "Arizona Diamondbacks",
    # Minnesota
    "twins": "Minnesota Twins", "min": "Minnesota Twins",
    # Detroit
    "tigers": "Detroit Tigers", "det": "Detroit Tigers",
    # Kansas City
    "royals": "Kansas City Royals", "kc": "Kansas City Royals", "kcr": "Kansas City Royals",
    # Baltimore
    "orioles": "Baltimore Orioles", "bal": "Baltimore Orioles",
    # Toronto
    "blue jays": "Toronto Blue Jays", "jays": "Toronto Blue Jays", "tor": "Toronto Blue Jays",
    # Tampa Bay
    "rays": "Tampa Bay Rays", "tb": "Tampa Bay Rays", "tbr": "Tampa Bay Rays",
    # Oakland / Athletics (moved to Sacramento 2025)
    "athletics": "Athletics", "a's": "Athletics", "as": "Athletics", "oak": "Athletics", "sac": "Athletics",
    # Cleveland
    "guardians": "Cleveland Guardians", "cle": "Cleveland Guardians",
    # Miami
    "marlins": "Miami Marlins", "mia": "Miami Marlins",
}


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def build_stats() -> dict:
    """
    Fetch all historical seasons from the MLB API (no file I/O), compute
    comeback stats, discard the raw game data, and return only the stats dict.
    Intended for bot/module use where memory matters.
    """
    all_games: list[dict] = []
    for season in SEASONS:
        all_games.extend(_fetch_season(season))
    stats = compute_comeback_stats(all_games)
    logger.info(f"Leave calculator: analyzed {sum(v['total'] for v in stats.values()):,} game-situations")
    del all_games
    return stats



def _fetch_season(season: int) -> list[dict]:
    """Fetch all completed regular-season games with inning-by-inning scores."""
    logger.info(f"Fetching {season} season from MLB Stats API...")
    url = f"{BASE_URL}/schedule"
    params = {
        "sportId": 1,
        "season": season,
        "gameType": "R",
        "hydrate": "linescore",
        "fields": (
            "dates,date,games,gamePk,status,abstractGameState,"
            "teams,away,home,score,team,name,"
            "linescore,innings,num,runs"
        ),
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue

            teams = game.get("teams", {})
            final_away = teams.get("away", {}).get("score")
            final_home = teams.get("home", {}).get("score")
            if final_away is None or final_home is None:
                continue

            innings_raw = game.get("linescore", {}).get("innings", [])
            inning_snapshots = []
            away_cum = 0
            home_cum = 0
            for inn in innings_raw:
                away_cum += inn.get("away", {}).get("runs") or 0
                home_cum += inn.get("home", {}).get("runs") or 0
                inning_snapshots.append({
                    "inning": inn.get("num"),
                    "away_total": away_cum,
                    "home_total": home_cum,
                })

            games.append({
                "gamePk": game.get("gamePk"),
                "date": date_entry.get("date"),
                "away_team": teams.get("away", {}).get("team", {}).get("name"),
                "home_team": teams.get("home", {}).get("team", {}).get("name"),
                "final_away": final_away,
                "final_home": final_home,
                "innings": inning_snapshots,
            })

    logger.info(f"  -> {len(games)} completed games for {season}")
    return games


def load_games(refresh: bool = False) -> list[dict]:
    """Return cached game data, fetching from the API if needed."""
    if not refresh and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                cached = json.load(f)
            seasons_cached = cached.get("seasons", [])
            games = cached.get("games", [])
            logger.info(f"Loaded {len(games):,} games from cache (seasons: {seasons_cached})")
            return games
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Cache file corrupted or unreadable: {e}. Re-fetching...")

    if refresh and CACHE_FILE.exists():
        CACHE_FILE.unlink()
        logger.info("Cache cleared, re-fetching...")

    logger.info("Fetching MLB game data (this takes ~30s the first time)...")
    all_games: list[dict] = []
    for season in SEASONS:
        all_games.extend(_fetch_season(season))

    with open(CACHE_FILE, "w") as f:
        json.dump({"seasons": SEASONS, "games": all_games}, f)
    logger.info(f"Cached {len(all_games):,} total games -> {CACHE_FILE}")
    return all_games


# ---------------------------------------------------------------------------
# Live game lookup
# ---------------------------------------------------------------------------

def _team_matches(query: str, team_name: str) -> bool:
    """Return True if the query plausibly refers to team_name."""
    q = query.lower().strip()
    team_lower = team_name.lower()
    # Substring match first — catches "giants", "san francisco", city names, etc.
    if q in team_lower:
        return True
    # Alias lookup for abbreviations like "sf", "nyy", "wsh"
    if q in TEAM_ALIASES:
        alias_target = TEAM_ALIASES[q].lower()
        return alias_target == team_lower or alias_target in team_lower
    return False


def fetch_live_game(team_query: str) -> dict | None:
    """
    Look up today's schedule for a game involving the named team that is
    currently in progress (or recently final).

    Returns a dict with keys:
        away_team, home_team, away_score, home_score,
        inning, inning_half, status, game_pk
    or None if no matching live game is found.
    """
    from datetime import timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)
    url = f"{BASE_URL}/schedule"
    params = {
        "sportId": 1,
        "startDate": yesterday.strftime("%Y-%m-%d"),
        "endDate": today.strftime("%Y-%m-%d"),
        "gameType": "R",
        "hydrate": "linescore",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    candidates = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            teams = game.get("teams", {})
            away_name = teams.get("away", {}).get("team", {}).get("name", "")
            home_name = teams.get("home", {}).get("team", {}).get("name", "")

            if not (_team_matches(team_query, away_name) or _team_matches(team_query, home_name)):
                continue

            status = game.get("status", {})
            abstract = status.get("abstractGameState", "")   # Preview / Live / Final
            detailed = status.get("detailedState", "")

            linescore = game.get("linescore", {})
            away_score = linescore.get("teams", {}).get("away", {}).get("runs")
            home_score = linescore.get("teams", {}).get("home", {}).get("runs")
            current_inning = linescore.get("currentInning")
            inning_half = linescore.get("inningHalf", "")    # "Top" or "Bottom"

            # Fall back to schedule-level scores when linescore is absent
            if away_score is None:
                away_score = teams.get("away", {}).get("score", 0)
            if home_score is None:
                home_score = teams.get("home", {}).get("score", 0)

            candidates.append({
                "away_team": away_name,
                "home_team": home_name,
                "away_score": away_score or 0,
                "home_score": home_score or 0,
                "inning": current_inning,
                "inning_half": inning_half,
                "abstract": abstract,
                "status": detailed,
                "game_pk": game.get("gamePk"),
            })

    if not candidates:
        return None

    # Prefer live games; fall back to most recent final
    live = [g for g in candidates if g["abstract"] == "Live"]
    if live:
        return live[0]
    final = [g for g in candidates if g["abstract"] == "Final"]
    if final:
        return final[-1]
    return candidates[0]


def _completed_inning(inning: int, inning_half: str) -> int:
    """
    Convert a live inning + half into the number of fully completed innings
    suitable for the FTE model (which evaluates after each complete inning).

    Top of N  -> N-1 complete innings
    Bottom of N -> N-1 complete innings (top done, bottom in progress)
    """
    if not inning:
        return 0
    return max(1, inning - 1)


# ---------------------------------------------------------------------------
# Probability computation
# ---------------------------------------------------------------------------

def compute_comeback_stats(games: list[dict]) -> dict:
    """
    For every (inning_completed, run_deficit) pair, count:
        - total: how many times a team trailed by exactly that deficit after that inning
        - comebacks: how many times the trailing team went on to win

    Returns {(inning, deficit): {"total": int, "comebacks": int}}
    """
    stats: dict = defaultdict(lambda: {"total": 0, "comebacks": 0})

    for game in games:
        final_away = game["final_away"]
        final_home = game["final_home"]

        for snap in game["innings"]:
            inning = snap["inning"]
            if inning > 8:          # FTE table only covers innings 1-8
                break

            away = snap["away_total"]
            home = snap["home_total"]
            if away == home:        # tied - not a "leave" situation
                continue

            diff = abs(away - home)
            trailing_wins = (final_home > final_away) if away > home else (final_away > final_home)

            key = (inning, diff)
            stats[key]["total"] += 1
            if trailing_wins:
                stats[key]["comebacks"] += 1

    return dict(stats)


# ---------------------------------------------------------------------------
# Core decision logic
# ---------------------------------------------------------------------------

def should_leave(
    score_a: int,
    score_b: int,
    inning: int,
    stats: dict,
    fp_rate: float = DEFAULT_FP_RATE,
) -> dict:
    """
    Decide whether a spectator should leave the game.

    Args:
        score_a:  Score of the spectator's team (or home team).
        score_b:  Score of the opponent.
        inning:   Inning number just completed (1-indexed).
        stats:    Output of compute_comeback_stats().
        fp_rate:  Acceptable probability of leaving and missing a comeback.

    Returns a dict:
        {
            "leave":          bool,
            "comeback_prob":  float | None,
            "sample_size":    int,
            "source":         str,   # "historical" | "FTE table" | "N/A"
            "reason":         str,
        }
    """
    diff = abs(score_a - score_b)

    # --- Tied game ---
    if diff == 0:
        return {
            "leave": False,
            "comeback_prob": None,
            "sample_size": 0,
            "source": "N/A",
            "reason": f"Tied game after inning {inning}. Stay - this one isn't over!",
        }

    # --- Extra innings or 9th ---
    if inning >= 9:
        leave_9th = diff >= 2
        return {
            "leave": leave_9th,
            "comeback_prob": None,
            "sample_size": 0,
            "source": "N/A",
            "reason": (
                f"Inning {inning}, {diff}-run game. "
                + ("Safe to leave - extremely unlikely to flip now."
                   if leave_9th else "Only 1 run. Stay for the finish!")
            ),
        }

    # --- Normal innings 1-8 ---
    key = (inning, diff)
    entry = stats.get(key)

    if entry and entry["total"] >= MIN_SAMPLE:
        # Data-driven decision
        comeback_prob = entry["comebacks"] / entry["total"]
        leave = comeback_prob <= fp_rate
        source = "historical data"
        prob_str = f"{comeback_prob:.1%} comeback rate ({entry['total']:,} historical games)"
        reason = (
            f"After inning {inning} with a {diff}-run deficit: {prob_str}. "
            + ("Safe to leave." if leave else "Stay - there's still a real chance!")
        )
        return {
            "leave": leave,
            "comeback_prob": comeback_prob,
            "sample_size": entry["total"],
            "source": source,
            "reason": reason,
        }
    else:
        # Fall back to FTE lookup table
        threshold = FTE_THRESHOLDS.get(inning, 999)
        leave = diff >= threshold
        sample = entry["total"] if entry else 0
        reason = (
            f"After inning {inning} with a {diff}-run deficit: "
            f"using FiveThirtyEight table (threshold={threshold}, only {sample} historical samples). "
            + ("Safe to leave." if leave else "Stay!")
        )
        return {
            "leave": leave,
            "comeback_prob": None,
            "sample_size": sample,
            "source": "FTE table",
            "reason": reason,
        }


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_threshold_table(stats: dict, fp_rate: float = DEFAULT_FP_RATE) -> None:
    """Print FTE thresholds vs. data-driven thresholds side by side."""
    print(f"\n{'='*72}")
    print(f" Thresholds: leave when run deficit >= threshold  (FP rate = {fp_rate:.0%})")
    print(f"{'='*72}")
    print(f"  {'Inning':<8} {'FTE Table':<12} {'MLB Data':<12} {'Comeback % @ data threshold'}")
    print(f"  {'-'*65}")

    for inning in range(1, 9):
        fte = FTE_THRESHOLDS.get(inning, "N/A")

        # Find data-driven threshold: smallest diff where comeback_prob <= fp_rate
        data_thresh = "N/A"
        prob_str = ""
        for diff in range(1, 15):
            key = (inning, diff)
            entry = stats.get(key)
            if entry and entry["total"] >= MIN_SAMPLE:
                prob = entry["comebacks"] / entry["total"]
                if prob <= fp_rate:
                    data_thresh = diff
                    prob_str = f"{prob:.1%}  ({entry['total']:,} games)"
                    break

        print(f"  {inning:<8} {str(fte):<12} {str(data_thresh):<12} {prob_str}")

    print(f"{'='*72}\n")


def _banner(
    leave: bool,
    result: dict,
    score_a: int,
    score_b: int,
    inning: int,
    team_a: str = "Your Team",
    team_b: str = "Other Team",
    inning_half: str = "",
    status: str = "",
) -> None:
    width = 62
    half_str = f" ({inning_half})" if inning_half else ""
    print("\n" + "=" * width)
    print(f"  {team_a:<28} {score_a}  vs  {score_b}  {team_b}")
    print(f"  Inning: {inning}{half_str}   Status: {status or 'Live'}")
    print("=" * width)
    if leave:
        print("  VERDICT:  LEAVE NOW")
    else:
        print("  VERDICT:  STAY AND WATCH")
    print(f"\n  {result['reason']}")
    if result["comeback_prob"] is not None:
        print(f"  Tolerance: comeback prob {result['comeback_prob']:.1%} <= {DEFAULT_FP_RATE:.0%} threshold")
    print("=" * width + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_live_lookup(team_query: str, stats: dict, fp_rate: float) -> bool:
    """Fetch live game for team_query, evaluate, print banner. Returns leave bool."""
    print(f"Looking up live game for '{team_query}'...")
    game = fetch_live_game(team_query)

    if game is None:
        print(f"No game found today for '{team_query}'. Check the team name and try again.")
        return False

    away, home = game["away_team"], game["home_team"]
    away_score, home_score = game["away_score"], game["home_score"]
    raw_inning = game["inning"]
    inning_half = game["inning_half"]
    status = game["status"]
    abstract = game["abstract"]

    if abstract == "Preview" or raw_inning is None:
        print(f"  {away} vs {home} has not started yet.")
        return False

    completed = _completed_inning(raw_inning, inning_half)
    result = should_leave(away_score, home_score, completed, stats, fp_rate)

    _banner(
        result["leave"], result,
        away_score, home_score, raw_inning,
        team_a=away, team_b=home,
        inning_half=inning_half,
        status=status,
    )
    return result["leave"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Should you leave the baseball game?",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python leave_calculator.py --team nationals
  python leave_calculator.py --team "red sox"
  python leave_calculator.py --team NYY
  python leave_calculator.py --score 2 7 --inning 7
  python leave_calculator.py --thresholds
  python leave_calculator.py --refresh
        """,
    )
    parser.add_argument(
        "--team", type=str, metavar="NAME",
        help="Team name or abbreviation — looks up today's live game automatically",
    )
    parser.add_argument(
        "--score", type=int, nargs=2, metavar=("SCORE_A", "SCORE_B"),
        help="Manual scores (away then home, or your team then other team)",
    )
    parser.add_argument(
        "--inning", type=int,
        help="Inning number (used with --score)",
    )
    parser.add_argument(
        "--fp-rate", type=float, default=DEFAULT_FP_RATE, dest="fp_rate",
        help=f"Acceptable false-positive rate (default {DEFAULT_FP_RATE})",
    )
    parser.add_argument(
        "--thresholds", action="store_true",
        help="Print the FTE vs. data-driven threshold table and exit",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Clear the local cache and re-fetch historical game data from the MLB API",
    )
    args = parser.parse_args()

    games = load_games(refresh=args.refresh)

    print(f"Computing comeback probabilities from {len(games):,} games...")
    stats = compute_comeback_stats(games)
    situations = sum(v["total"] for v in stats.values())
    print(f"Analyzed {situations:,} game-situations across {len(stats)} (inning, deficit) combinations.\n")

    if args.thresholds:
        print_threshold_table(stats, args.fp_rate)
        return

    # --- Live lookup via team name ---
    if args.team:
        leave = _run_live_lookup(args.team, stats, args.fp_rate)
        sys.exit(0 if leave else 1)

    # --- Manual score entry ---
    if args.score and args.inning:
        score_a, score_b = args.score
        result = should_leave(score_a, score_b, args.inning, stats, args.fp_rate)
        _banner(result["leave"], result, score_a, score_b, args.inning)
        sys.exit(0 if result["leave"] else 1)

    # -------------------------------------------------------------------
    # Interactive mode
    # -------------------------------------------------------------------
    print("MLB Leave Early Calculator  (type 'quit' to exit)")
    print("Enter a team name for a live lookup, or 'm' to enter scores manually.\n")
    while True:
        try:
            raw = input("Team name (or 'm' for manual, 'quit' to exit): ").strip()
            if raw.lower() in ("quit", "q", "exit"):
                break

            if raw.lower() == "m":
                raw_a = input("  Score A: ").strip()
                raw_b = input("  Score B: ").strip()
                raw_i = input("  Inning completed: ").strip()
                score_a, score_b, inning = int(raw_a), int(raw_b), int(raw_i)
                result = should_leave(score_a, score_b, inning, stats, args.fp_rate)
                _banner(result["leave"], result, score_a, score_b, inning)
            else:
                _run_live_lookup(raw, stats, args.fp_rate)

        except (ValueError, TypeError):
            print("Please enter valid numbers.\n")
        except requests.RequestException as exc:
            print(f"Network error: {exc}\n")
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break


if __name__ == "__main__":
    main()
