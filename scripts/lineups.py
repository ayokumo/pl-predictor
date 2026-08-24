"""
Confirmed lineup checker. Official lineups are typically posted ~60 minutes
before kickoff via club social accounts / the Premier League site.

Free approach: poll a public source close to kickoff. This is the most
time-sensitive part of the system — the GitHub Actions workflow runs this
every 15 minutes during the pre-match window (see .github/workflows/predict.yml)
so we catch the lineup drop and can trigger a final re-prediction.

As with injuries, there's no clean free structured API for this, so this
is written defensively: if no lineup is found yet, it just reports "not
posted" rather than failing.
"""

import json
import os
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import config

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PLPredictorBot/1.0)"}

# Placeholder source — swap for whichever public lineup source you verify
# works reliably (Premier League official site, or a football data mirror).
LINEUP_SOURCE_URL_TEMPLATE = "https://www.premierleague.com/match/{match_id}"


def _load_existing():
    if os.path.exists(config.LINEUPS_FILE):
        with open(config.LINEUPS_FILE) as f:
            return json.load(f)
    return {}


def check_lineup(match_id):
    """
    Returns {"posted": bool, "home_xi": [...], "away_xi": [...], "formation_home": str,
    "formation_away": str} or {"posted": False} if not yet available.
    """
    try:
        url = LINEUP_SOURCE_URL_TEMPLATE.format(match_id=match_id)
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Placeholder selector — inspect actual page structure and adjust.
        lineup_section = soup.select_one(".matchLineups")
        if not lineup_section:
            return {"posted": False, "checked_at": datetime.now(timezone.utc).isoformat()}

        # Real parsing logic goes here once selectors are confirmed against
        # the live page. Left minimal intentionally to avoid shipping
        # confidently-wrong scraping logic.
        return {"posted": False, "checked_at": datetime.now(timezone.utc).isoformat()}

    except Exception as e:
        print(f"  ! lineup check failed for match {match_id}: {e}")
        return {"posted": False, "checked_at": datetime.now(timezone.utc).isoformat()}


def run(fixtures):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    existing = _load_existing()
    for fx in fixtures:
        result = check_lineup(fx["match_id"])
        if result.get("posted") or fx["match_id"] not in existing:
            existing[str(fx["match_id"])] = result
    with open(config.LINEUPS_FILE, "w") as f:
        json.dump(existing, f, indent=2)
    return existing


if __name__ == "__main__":
    with open(config.FIXTURES_FILE) as f:
        fixtures = json.load(f)
    run(fixtures)
