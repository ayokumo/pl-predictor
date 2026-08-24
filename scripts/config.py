"""
Central config: API settings, model weights, and paths.
Edit weights here to tune the prediction engine without touching logic.
"""

import os

# --- football-data.org (free tier) ---
# Get a free key at https://www.football-data.org/client/register
FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
PL_COMPETITION_ID = "PL"  # Premier League code on football-data.org

# --- Rate limiting (free tier = 10 requests/minute) ---
REQUEST_DELAY_SECONDS = 6.5  # keeps us safely under 10/min

# --- Paths ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FIXTURES_FILE = os.path.join(DATA_DIR, "fixtures.json")
FORM_FILE = os.path.join(DATA_DIR, "team_form.json")
INJURIES_FILE = os.path.join(DATA_DIR, "injuries.json")
LINEUPS_FILE = os.path.join(DATA_DIR, "lineups.json")
NEWS_FILE = os.path.join(DATA_DIR, "news_flags.json")
PREDICTIONS_FILE = os.path.join(DATA_DIR, "predictions.json")

# --- Model weights (0-1 range, tuned by feel — adjust as you validate results) ---
WEIGHTS = {
    "recent_form": 0.28,       # last 5 results, weighted recency
    "home_advantage": 0.10,
    "head_to_head": 0.08,
    "goal_difference_trend": 0.12,
    "injury_impact": 0.18,     # missing key players
    "playstyle_matchup": 0.12, # e.g. high press vs weak build-up-under-press team
    "manager_tactical_edge": 0.07,
    "squad_rotation_risk": 0.05,  # European fixture congestion, rotation likelihood
}

# Sanity check weights sum to 1.0 (informational only)
assert abs(sum(WEIGHTS.values()) - 1.0) < 0.01, "WEIGHTS should sum to ~1.0"

# How many hours before kickoff lineup-based re-scoring should trigger
LINEUP_CHECK_WINDOW_HOURS = 1.25  # start checking a bit before the 1hr mark
