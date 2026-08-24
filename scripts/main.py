"""
Orchestrates the full pipeline:
  1. Fetch fixtures/form/standings (football-data.org)
  2. Refresh injuries
  3. Check lineups (only meaningfully useful within ~1hr of kickoff)
  4. Score every upcoming fixture with model.py
  5. Write predictions.json (consumed by docs/index.html dashboard)

Run modes (see .github/workflows/predict.yml):
  --mode daily   : full refresh, once a day
  --mode hourly  : lighter refresh on matchday (skip full re-fetch of form/standings)
  --mode lineup  : lineup-window check + re-score only fixtures kicking off soon
"""

import argparse
import json
import os
from datetime import datetime, timezone

import config
import fetch_data
import injuries_news
import lineups
import model


def load_team_meta():
    path = os.path.join(config.DATA_DIR, "team_meta.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    data.pop("_readme", None)
    data.pop("example_team_entry_template", None)
    return data


def build_team_data(team_name, form_data, injury_data, team_meta):
    meta = team_meta.get(team_name, {})
    return {
        "form_results": form_data.get(team_name, []),
        "injuries": injury_data.get(team_name, []),
        "playstyle": meta.get("playstyle"),
        "manager_edge": meta.get("manager_edge", 0.0),
        "key_players": set(meta.get("key_players", [])),
        "rotation_risk": meta.get("rotation_risk", 0.0),
    }


def predict_all(fixtures, form_data, injury_data, team_meta, lineup_data=None):
    predictions = []
    for fx in fixtures:
        home = build_team_data(fx["home_team"], form_data, injury_data, team_meta)
        away = build_team_data(fx["away_team"], form_data, injury_data, team_meta)

        lineup_info = (lineup_data or {}).get(str(fx["match_id"]), {"posted": False})

        result = model.score_match(home, away)
        predictions.append({
            "match_id": fx["match_id"],
            "utc_kickoff": fx["utc_kickoff"],
            "matchday": fx.get("matchday"),
            "home_team": fx["home_team"],
            "away_team": fx["away_team"],
            "lineups_posted": lineup_info.get("posted", False),
            "prediction": result,
        })
    return predictions


def run(mode):
    os.makedirs(config.DATA_DIR, exist_ok=True)

    if mode in ("daily",):
        fetch_data.run()
        injuries_news.run()
    elif mode == "hourly":
        # Lighter touch: refresh injuries/news, skip the heavier fixture/form
        # re-fetch unless it's missing (keeps us well under API rate limits).
        if not os.path.exists(config.FIXTURES_FILE):
            fetch_data.run()
        injuries_news.run()
    elif mode == "lineup":
        # Just check lineups; injuries/form assumed fresh from earlier runs today.
        pass

    with open(config.FIXTURES_FILE) as f:
        fixtures = json.load(f)
    with open(config.FORM_FILE) as f:
        form_data = json.load(f)
    with open(config.INJURIES_FILE) as f:
        injury_data = json.load(f)

    lineup_data = None
    if mode in ("lineup", "hourly"):
        lineup_data = lineups.run(fixtures)

    team_meta = load_team_meta()

    predictions = predict_all(fixtures, form_data, injury_data, team_meta, lineup_data)

    with open(config.PREDICTIONS_FILE, "w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "predictions": predictions,
        }, f, indent=2)

    print(f"Wrote {len(predictions)} predictions ({mode} mode).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "hourly", "lineup"], default="daily")
    args = parser.parse_args()
    run(args.mode)
