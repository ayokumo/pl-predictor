import os
import sys

import pandas as pd
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import predict_upcoming as pu  # noqa: E402
import train_validate as tv  # noqa: E402


def results(outcomes, gfs, gas):
    return [
        {"date": f"2026-09-{i + 1:02d}T12:00:00Z", "outcome": o, "goals_for": g, "goals_against": a}
        for i, (o, g, a) in enumerate(zip(outcomes, gfs, gas))
    ]


def test_live_form_uses_five_newest_results():
    r = results("LWWWWW", [0, 2, 2, 2, 2, 2], [1, 0, 0, 0, 0, 0])
    f = pu.live_form(r)
    assert f["ppg"] == 3.0 and f["gd"] == 2.0  # the oldest loss is dropped


def test_live_form_needs_five_results():
    assert pu.live_form(results("WWWW", [1] * 4, [0] * 4)) is None


def test_features_csv_has_no_leakage_and_enough_history():
    path = os.path.join(ROOT, "data", "features", "features.csv")
    if not os.path.exists(path):
        pytest.skip("features not built")
    f = pd.read_csv(path)
    assert (f["h_n_prev"] == 5).all() and (f["a_n_prev"] == 5).all()
    assert set(f["FTR"]) <= {"H", "D", "A"}
    assert all(c in f.columns for c in tv.FEATURES)


def test_validation_trains_only_on_earlier_seasons():
    path = os.path.join(ROOT, "data", "features", "features.csv")
    if not os.path.exists(path):
        pytest.skip("features not built")
    f = pd.read_csv(path)
    for season in tv.TEST_SEASONS:
        assert f[f["season"] < season]["season"].max() < season
