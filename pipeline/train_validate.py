"""
Train scikit-learn models on past seasons and validate season by season,
always moving forward in time: for each test season, the models are fit only
on matches from earlier seasons.

Compared against:
  home_win        always predict a home win (the baseline in the README)
  weighted_model  the repo's transparent weighted factor model (form only,
                  no injuries or lineups, which are not in historical data)
  logreg          logistic regression on form features
  gboost          gradient boosting on form features

Hyperparameters are fixed in this file and were not tuned on the test seasons.

Run (after features_spark.py):
    python pipeline/train_validate.py
"""

import glob
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import model as weighted  # noqa: E402  (the repo's weighted factor model)

FEATURES = [
    "d_ppg", "d_gd", "h_form_ppg", "a_form_ppg",
    "h_form_gf", "h_form_ga", "a_form_gf", "a_form_ga",
]
TEST_SEASONS = ["2021/22", "2022/23", "2023/24", "2024/25", "2025/26"]
OUT_DIR = os.path.join("data", "results")


def make_models():
    return {
        "logreg": make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)),
        "gboost": GradientBoostingClassifier(
            n_estimators=100, max_depth=2, learning_rate=0.05,
            subsample=0.8, random_state=0,
        ),
    }


def load_raw_results():
    frames = []
    for p in sorted(glob.glob(os.path.join("data", "raw", "E0_*.csv"))):
        d = pd.read_csv(p, usecols=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]).dropna()
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d["date"] = pd.to_datetime(d["Date"], format="%d/%m/%Y")
    return d.sort_values("date", kind="stable").reset_index(drop=True)


def weighted_predictions(feats):
    """Run the weighted factor model with each team's last 5 results."""
    raw = load_raw_results()
    history = {}  # team -> list of result dicts, most recent first
    preds = {}
    for r in raw.itertuples():
        key = (r.date, r.HomeTeam, r.AwayTeam)
        hist_h, hist_a = history.get(r.HomeTeam, []), history.get(r.AwayTeam, [])
        if len(hist_h) >= 5 and len(hist_a) >= 5:
            out = weighted.score_match(
                {"form_results": hist_h[:5]}, {"form_results": hist_a[:5]}
            )
            probs = {"H": out["home_win_prob"], "D": out["draw_prob"], "A": out["away_win_prob"]}
            preds[key] = max(probs, key=probs.get)
        for team, gf, ga in ((r.HomeTeam, r.FTHG, r.FTAG), (r.AwayTeam, r.FTAG, r.FTHG)):
            o = "W" if gf > ga else "D" if gf == ga else "L"
            history.setdefault(team, []).insert(
                0, {"outcome": o, "goals_for": int(gf), "goals_against": int(ga)}
            )
    feats = feats.copy()
    feats["date_dt"] = pd.to_datetime(feats["date"])
    return np.array(
        [preds[(d, h, a)] for d, h, a in zip(feats["date_dt"], feats["HomeTeam"], feats["AwayTeam"])]
    )


def main():
    path = os.path.join("data", "features", "features.csv")
    if not os.path.exists(path):
        sys.exit("Run pipeline/features_spark.py first.")
    feats = pd.read_csv(path)
    feats["weighted_model"] = weighted_predictions(feats)

    rows = []
    for season in TEST_SEASONS:
        train = feats[feats["season"] < season]
        test = feats[feats["season"] == season]
        row = {
            "season": season, "train_matches": len(train), "test_matches": len(test),
            "home_win_rate": (test["FTR"] == "H").mean(),
            "weighted_model": (test["weighted_model"] == test["FTR"]).mean(),
        }
        for name, m in make_models().items():
            m.fit(train[FEATURES], train["FTR"])
            row[name] = (m.predict(test[FEATURES]) == test["FTR"]).mean()
        rows.append(row)

    res = pd.DataFrame(rows)
    # pooled over all test matches, weighted by matches
    n = res["test_matches"]
    pooled = {"season": "all 5 seasons", "train_matches": "", "test_matches": int(n.sum())}
    for c in ["home_win_rate", "weighted_model", "logreg", "gboost"]:
        pooled[c] = float((res[c] * n).sum() / n.sum())
    res = pd.concat([res, pd.DataFrame([pooled])], ignore_index=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    res.to_csv(os.path.join(OUT_DIR, "validation_results.csv"), index=False)

    show = res.copy()
    for c in ["home_win_rate", "weighted_model", "logreg", "gboost"]:
        show[c] = (show[c] * 100).map(lambda v: f"{v:.1f}%")
    lines = [
        f"Validation run on {date.today().isoformat()}",
        "",
        "| Test season | Train matches | Test matches | Always home win | Weighted model | Logistic regression | Gradient boosting |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in show.itertuples():
        lines.append(
            f"| {r.season} | {r.train_matches} | {r.test_matches} | {r.home_win_rate} | "
            f"{r.weighted_model} | {r.logreg} | {r.gboost} |"
        )
    text = "\n".join(lines)
    with open(os.path.join(OUT_DIR, "validation_results.md"), "w") as f:
        f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
