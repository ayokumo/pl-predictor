"""
Weekly predictions from the trained logistic regression.

Trains on every match in data/features/features.csv, then scores the upcoming
fixtures in data/fixtures.json using each team's last 5 results from
data/team_form.json. Teams with fewer than 5 finished results are skipped and
listed under "skipped". Writes data/predictions_trained.json.
"""

import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from train_validate import FEATURES, make_models  # noqa: E402

N = 5


def live_form(results):
    """Same definitions as features_spark.py, from a list of result dicts."""
    recent = sorted(results, key=lambda r: r["date"], reverse=True)[:N]
    if len(recent) < N:
        return None
    pts = [3 if r["outcome"] == "W" else 1 if r["outcome"] == "D" else 0 for r in recent]
    gf = sum(r["goals_for"] for r in recent) / N
    ga = sum(r["goals_against"] for r in recent) / N
    return {"ppg": sum(pts) / N, "gf": gf, "ga": ga, "gd": gf - ga}


def feature_row(h, a):
    return {
        "d_ppg": h["ppg"] - a["ppg"], "d_gd": h["gd"] - a["gd"],
        "h_form_ppg": h["ppg"], "a_form_ppg": a["ppg"],
        "h_form_gf": h["gf"], "h_form_ga": h["ga"],
        "a_form_gf": a["gf"], "a_form_ga": a["ga"],
    }


def main():
    feats = pd.read_csv(os.path.join("data", "features", "features.csv"))
    clf = make_models()["logreg"].fit(feats[FEATURES], feats["FTR"])
    with open(os.path.join("data", "fixtures.json")) as f:
        fixtures = json.load(f)
    with open(os.path.join("data", "team_form.json")) as f:
        form = json.load(f)

    preds, skipped = [], []
    for fx in fixtures:
        h, a = live_form(form.get(fx["home_team"], [])), live_form(form.get(fx["away_team"], []))
        if h is None or a is None:
            skipped.append({"match_id": fx["match_id"], "home_team": fx["home_team"],
                            "away_team": fx["away_team"], "reason": "fewer than 5 finished results"})
            continue
        x = pd.DataFrame([feature_row(h, a)])[FEATURES]
        p = dict(zip(clf.classes_, clf.predict_proba(x)[0]))
        preds.append({
            "match_id": fx["match_id"], "utc_kickoff": fx["utc_kickoff"],
            "home_team": fx["home_team"], "away_team": fx["away_team"],
            "home_win_prob": round(float(p["H"]), 3),
            "draw_prob": round(float(p["D"]), 3),
            "away_win_prob": round(float(p["A"]), 3),
            "pick": max(p, key=p.get),
        })

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "logistic regression on last 5 match form, trained on 2018/19 to 2025/26",
        "predictions": preds, "skipped": skipped,
    }
    with open(os.path.join("data", "predictions_trained.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(preds)} predictions, skipped {len(skipped)}.")


if __name__ == "__main__":
    main()
