"""
Injury / suspension / team-news tracking.

Honest limitation: there is no free, reliable, structured API for
Premier League injuries. This module scrapes public injury-list pages.
Scraping is inherently fragile — site HTML changes will break selectors.

Design principle: NEVER let a scrape failure crash the pipeline or wipe
existing data. If a fetch fails, we keep yesterday's data and log a
warning so you can see it needs attention.

You will likely need to adjust the CSS selectors below periodically —
that's the trade-off of $0 budget vs a paid injury API (e.g. Sportmonks,
which has this cleanly structured for ~$30-50/mo if you ever want to
upgrade this piece).
"""

import json
import os
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import config

# Example public source. Verify this URL still exists / matches structure
# before relying on it — sites change often. Swap in whichever free injury
# list source you find most reliable.
INJURY_SOURCE_URL = "https://www.premierinjuries.com/injury-table.php"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PLPredictorBot/1.0)"}


def _load_existing():
    if os.path.exists(config.INJURIES_FILE):
        with open(config.INJURIES_FILE) as f:
            return json.load(f)
    return {}


def scrape_injuries():
    """
    Returns dict: { team_name: [ {player, status, expected_return, reason} ] }
    Falls back to existing data on any failure.
    """
    existing = _load_existing()
    try:
        resp = requests.get(INJURY_SOURCE_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # NOTE: selector below is a placeholder — inspect the actual page
        # structure and adjust. Wrapped in try/except so a mismatch doesn't
        # crash the whole pipeline.
        rows = soup.select("table.injury-table tr")
        data = {}
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            team, player, status, expected = cells[0], cells[1], cells[2], cells[3]
            data.setdefault(team, []).append({
                "player": player,
                "status": status,
                "expected_return": expected,
                "last_checked": datetime.now(timezone.utc).isoformat(),
            })

        if not data:
            print("  ! injury scrape returned no rows — keeping previous data")
            return existing

        return data

    except Exception as e:
        print(f"  ! injury scrape failed ({e}) — keeping previous data")
        return existing


def run():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    print("Checking injuries/team news...")
    data = scrape_injuries()
    with open(config.INJURIES_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  -> injury data for {len(data)} teams saved")


if __name__ == "__main__":
    run()
