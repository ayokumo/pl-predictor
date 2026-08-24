"""
Pulls Premier League fixtures, recent results, and standings from
football-data.org (free tier). Writes normalized JSON to /data.

Free tier limits: 10 requests/minute. This script paces itself accordingly.
"""

import json
import time
import requests
from datetime import datetime, timedelta, timezone

import config


def _headers():
    if not config.FOOTBALL_DATA_API_KEY:
        raise RuntimeError(
            "FOOTBALL_DATA_API_KEY is not set. Get a free key at "
            "https://www.football-data.org/client/register and set it as "
            "an environment variable / GitHub Actions secret."
        )
    return {"X-Auth-Token": config.FOOTBALL_DATA_API_KEY}


def _get(path, params=None):
    url = f"{config.FOOTBALL_DATA_BASE}{path}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=20)
    if resp.status_code == 429:
        # Rate limited — back off and retry once
        time.sleep(60)
        resp = requests.get(url, headers=_headers(), params=params, timeout=20)
    resp.raise_for_status()
    time.sleep(config.REQUEST_DELAY_SECONDS)
    return resp.json()


def fetch_upcoming_fixtures(days_ahead=10):
    """Fixtures in the next N days for the PL."""
    date_from = datetime.now(timezone.utc).date().isoformat()
    date_to = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).date().isoformat()
    data = _get(
        f"/competitions/{config.PL_COMPETITION_ID}/matches",
        params={"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"},
    )
    fixtures = []
    for m in data.get("matches", []):
        fixtures.append({
            "match_id": m["id"],
            "utc_kickoff": m["utcDate"],
            "matchday": m.get("matchday"),
            "home_team": m["homeTeam"]["name"],
            "home_team_id": m["homeTeam"]["id"],
            "away_team": m["awayTeam"]["name"],
            "away_team_id": m["awayTeam"]["id"],
            "venue": m.get("venue"),
        })
    return fixtures


def fetch_team_recent_results(team_id, limit=6):
    """Last N finished matches for a team, across all competitions available."""
    data = _get(f"/teams/{team_id}/matches", params={"status": "FINISHED", "limit": limit})
    results = []
    for m in data.get("matches", []):
        is_home = m["homeTeam"]["id"] == team_id
        gf = m["score"]["fullTime"]["home"] if is_home else m["score"]["fullTime"]["away"]
        ga = m["score"]["fullTime"]["away"] if is_home else m["score"]["fullTime"]["home"]
        if gf is None or ga is None:
            continue
        outcome = "W" if gf > ga else ("D" if gf == ga else "L")
        results.append({
            "date": m["utcDate"],
            "opponent": m["awayTeam"]["name"] if is_home else m["homeTeam"]["name"],
            "venue": "H" if is_home else "A",
            "goals_for": gf,
            "goals_against": ga,
            "outcome": outcome,
            "competition": m["competition"]["name"],
        })
    return results


def fetch_standings():
    data = _get(f"/competitions/{config.PL_COMPETITION_ID}/standings")
    table = {}
    for group in data.get("standings", []):
        if group.get("type") != "TOTAL":
            continue
        for row in group.get("table", []):
            table[row["team"]["name"]] = {
                "position": row["position"],
                "played": row["playedGames"],
                "won": row["won"],
                "draw": row["draw"],
                "lost": row["lost"],
                "goal_difference": row["goalDifference"],
                "points": row["points"],
                "form": row.get("form"),  # e.g. "W,W,D,L,W" if provided
            }
    return table


def run():
    config_dir = config.DATA_DIR
    import os
    os.makedirs(config_dir, exist_ok=True)

    print("Fetching upcoming fixtures...")
    fixtures = fetch_upcoming_fixtures()
    with open(config.FIXTURES_FILE, "w") as f:
        json.dump(fixtures, f, indent=2)
    print(f"  -> {len(fixtures)} fixtures saved")

    print("Fetching standings...")
    standings = fetch_standings()
    with open(os.path.join(config_dir, "standings.json"), "w") as f:
        json.dump(standings, f, indent=2)

    print("Fetching recent form per team involved in upcoming fixtures...")
    team_ids = {}
    for fx in fixtures:
        team_ids[fx["home_team_id"]] = fx["home_team"]
        team_ids[fx["away_team_id"]] = fx["away_team"]

    form_data = {}
    for tid, name in team_ids.items():
        try:
            form_data[name] = fetch_team_recent_results(tid)
        except Exception as e:
            print(f"  ! failed to fetch form for {name}: {e}")
            form_data[name] = []

    with open(config.FORM_FILE, "w") as f:
        json.dump(form_data, f, indent=2)
    print(f"  -> form data saved for {len(form_data)} teams")


if __name__ == "__main__":
    run()
