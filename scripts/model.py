"""
Weighted-factor prediction engine.

Why weighted-factors instead of a trained ML model: with $0 budget and
free data sources, you don't have the depth of historical data (xG,
tracking data, etc.) that makes a trained model meaningfully better than
a well-reasoned weighted system. This approach is transparent, tunable
(edit config.WEIGHTS), and easy to sanity-check — you can see exactly
why a prediction came out the way it did, which matters when you're
debugging or building trust in the system.

If you later want to graduate to a trained model: football-data.org's
free tier gives you historical match results going back several seasons,
enough to train a simple logistic regression on (form, home/away, GD)
features predicting W/D/L. That's a natural v2 — this file is written so
swapping in a trained model later is a small change (replace `score_team`
internals, keep the same output shape).
"""

import json
from datetime import datetime, timezone

import config


def _form_score(results, max_games=5):
    """Recency-weighted points-per-game from recent results. Returns 0-1."""
    if not results:
        return 0.5  # neutral if unknown
    recent = results[:max_games]
    weights = [1.0, 0.85, 0.7, 0.55, 0.4][: len(recent)]
    total_weight = sum(weights)
    points_map = {"W": 3, "D": 1, "L": 0}
    weighted_points = sum(points_map[r["outcome"]] * w for r, w in zip(recent, weights))
    max_possible = 3 * total_weight
    return weighted_points / max_possible if max_possible else 0.5


def _goal_diff_trend(results, max_games=5):
    """Average goal difference per game recently, normalized to 0-1 (0.5 = even)."""
    if not results:
        return 0.5
    recent = results[:max_games]
    avg_gd = sum(r["goals_for"] - r["goals_against"] for r in recent) / len(recent)
    # squash to 0-1 range, +/-3 goal avg diff treated as extreme
    normalized = 0.5 + (avg_gd / 6.0)
    return max(0.0, min(1.0, normalized))


def _injury_impact(injury_list, key_players=None):
    """
    Returns 0-1 penalty score (0 = no impact, 1 = severe impact).
    Without a "key player" weighting dataset, this uses count + status as
    a proxy. Wire in `key_players` (a set of important player names per
    team) for sharper results if you maintain that list yourself.
    """
    if not injury_list:
        return 0.0
    out_count = sum(1 for i in injury_list if "out" in i.get("status", "").lower())
    doubtful_count = sum(1 for i in injury_list if "doubt" in i.get("status", "").lower())
    raw = out_count * 1.0 + doubtful_count * 0.4
    if key_players:
        for i in injury_list:
            if i.get("player") in key_players and "out" in i.get("status", "").lower():
                raw += 1.5  # extra weight for confirmed key absences
    return min(1.0, raw / 6.0)


def _playstyle_matchup(home_style, away_style):
    """
    Placeholder scoring for tactical matchup edge, -1 to +1 (favor home / favor away).
    Wire this to real style tags (e.g. "high-press", "low-block", "possession",
    "counter-attack") that you maintain per team — this is genuinely the
    hardest factor to source from free data and benefits from manual curation
    since it changes slowly (tied to manager identity, not week-to-week).
    """
    if not home_style or not away_style:
        return 0.0
    # Simple rock-paper-scissors style rules as a starting point — refine
    # these based on actual tactical analysis as you build out style tags.
    counters = {
        ("high-press", "low-block"): -0.2,   # high press struggles to break low blocks
        ("possession", "counter-attack"): -0.15,  # possession sides vulnerable to counters
        ("counter-attack", "high-press"): 0.15,   # counter sides exploit space behind press
        ("high-press", "possession"): 0.2,   # press disrupts build-up play
    }
    return counters.get((home_style, away_style), 0.0)


def score_match(home_data, away_data, weights=None):
    """
    home_data / away_data: {
        "form_results": [...], "injuries": [...], "playstyle": str,
        "manager_edge": float (-1 to 1, manual/subjective input),
        "rotation_risk": float (0-1, higher = more likely to rotate),
        "is_home": bool
    }
    Returns dict with win/draw/loss probabilities and factor breakdown.
    """
    w = weights or config.WEIGHTS

    home_form = _form_score(home_data.get("form_results"))
    away_form = _form_score(away_data.get("form_results"))

    home_gd = _goal_diff_trend(home_data.get("form_results"))
    away_gd = _goal_diff_trend(away_data.get("form_results"))

    home_injury_penalty = _injury_impact(home_data.get("injuries"), home_data.get("key_players"))
    away_injury_penalty = _injury_impact(away_data.get("injuries"), away_data.get("key_players"))

    style_edge = _playstyle_matchup(home_data.get("playstyle"), away_data.get("playstyle"))

    manager_edge = (home_data.get("manager_edge", 0) - away_data.get("manager_edge", 0)) / 2

    rotation_penalty_home = home_data.get("rotation_risk", 0.0)
    rotation_penalty_away = away_data.get("rotation_risk", 0.0)

    # Combine into a single "home advantage score" from -1 (away dominant) to +1 (home dominant)
    raw_score = (
        w["recent_form"] * (home_form - away_form)
        + w["home_advantage"] * 1.0  # home team always gets this fixed nudge
        + w["goal_difference_trend"] * (home_gd - away_gd)
        + w["injury_impact"] * (away_injury_penalty - home_injury_penalty)
        + w["playstyle_matchup"] * style_edge
        + w["manager_tactical_edge"] * manager_edge
        + w["squad_rotation_risk"] * (rotation_penalty_away - rotation_penalty_home)
    )
    # head_to_head weight reserved for when you wire in H2H history

    # Convert raw_score (~ -1 to 1) into W/D/L probabilities via a soft
    # logistic-style split. This is a heuristic, not a calibrated model —
    # treat probabilities as relative confidence, not precise odds.
    home_win_raw = max(0.05, 0.40 + raw_score * 0.45)
    away_win_raw = max(0.05, 0.40 - raw_score * 0.45)
    draw_raw = max(0.10, 1.0 - home_win_raw - away_win_raw)

    total = home_win_raw + away_win_raw + draw_raw
    home_win = round(home_win_raw / total, 3)
    away_win = round(away_win_raw / total, 3)
    draw = round(1.0 - home_win - away_win, 3)

    confidence = round(abs(raw_score), 3)  # how decisive the factors are

    return {
        "home_win_prob": home_win,
        "draw_prob": draw,
        "away_win_prob": away_win,
        "confidence": confidence,
        "raw_score": round(raw_score, 3),
        "factors": {
            "home_form": round(home_form, 3),
            "away_form": round(away_form, 3),
            "home_goal_diff_trend": round(home_gd, 3),
            "away_goal_diff_trend": round(away_gd, 3),
            "home_injury_penalty": round(home_injury_penalty, 3),
            "away_injury_penalty": round(away_injury_penalty, 3),
            "playstyle_edge": style_edge,
            "manager_edge": round(manager_edge, 3),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
