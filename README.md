# PL Match Predictor (free-tier build)

A weekly/daily/hourly-updating Premier League predictor built entirely on free
tools: GitHub Actions for scheduling, football-data.org's free API for
fixtures/form/standings, and a static GitHub Pages dashboard. $0/month.

## What this does

- **Daily** (07:00 UTC): full refresh of fixtures, standings, team form, injuries.
- **Hourly on Fri/Sat/Sun**: refreshes injuries/news, re-scores predictions.
- **Every 15 min on matchdays**: checks whether lineups have posted for
  fixtures kicking off soon, and re-scores those matches once lineups are in.
- Publishes results to `data/predictions.json`, viewable on `index.html`
  (deployable free via GitHub Pages).

## Setup (10 minutes)

1. **Get a free API key** at https://www.football-data.org/client/register
   (free tier = 10 requests/min, which this pipeline respects).
2. **Push this repo to GitHub.**
3. **Add the API key as a secret**: repo Settings → Secrets and variables →
   Actions → New repository secret → name it `FOOTBALL_DATA_API_KEY`.
4. **Enable GitHub Pages**: Settings → Pages → Source: "Deploy from a branch"
   → Branch: `main`, folder: `/ (root)`. Your dashboard will be live at
   `https://<you>.github.io/<repo>/`.
5. **Enable Actions**: the workflow at `.github/workflows/predict.yml` runs
   automatically on the schedule once pushed. You can also trigger it
   manually from the Actions tab (workflow_dispatch).
6. **Fill in `data/team_meta.json`** with playstyle tags, manager edge scores,
   and key players per team — see the template inside that file. This part
   is intentionally manual (see Limitations below).

Run locally to test before pushing:
```bash
cd scripts
pip install -r ../requirements.txt
export FOOTBALL_DATA_API_KEY=your_key_here
python main.py --mode daily
```

## Architecture

```
scripts/
  config.py         # weights, paths, API settings - tune here
  fetch_data.py      # fixtures/form/standings from football-data.org
  injuries_news.py   # injury scraping (fragile - see limitations)
  lineups.py          # lineup checking near kickoff (fragile - see limitations)
  model.py            # weighted-factor scoring engine (transparent baseline)
  main.py              # orchestrator, entrypoint for all modes
data/
  team_meta.json       # hand-maintained playstyle/manager/key-player data
  *.json               # generated data + predictions (committed by the Action)
pipeline/                # PySpark features, validation, trained predictions
tests/
index.html               # static dashboard, reads data/predictions.json
.github/workflows/
  predict.yml         # the free scheduler
```

## Trained model and validation (weekly pipeline)

**Weekly schedule:** `.github/workflows/weekly.yml` runs every Monday at 08:00 UTC (cron `0 8 * * 1`) and can also be started by hand from the Actions tab. It refreshes fixtures and form, rebuilds the PySpark features, re-runs the season by season validation, writes `data/predictions_trained.json`, runs the tests and commits the results. The faster daily, hourly and matchday schedules in `predict.yml` are unchanged. First run on GitHub on 2026-10-18 finished successfully and committed fresh data and 11 trained predictions.

**Pipeline** (all local, no API key needed for the validation):
1. `data/raw/E0_*.csv`: 8 Premier League seasons, 2018/19 to 2025/26, from football-data.co.uk, unmodified.
2. `pipeline/features_spark.py`: a PySpark job. For each team and match it computes points per game, goals for, goals against and goal difference over the team's previous 5 matches (window rows -5 to -1, so the match itself is never included). Windows run across seasons. A match is kept only if both teams have 5 previous matches, which removes the first matches of newly promoted teams and the very start of 2018/19.
3. `pipeline/train_validate.py`: for each test season, fits logistic regression and gradient boosting on earlier seasons only, then predicts the test season. Hyperparameters are fixed in the file and were not tuned on the test seasons.
4. `pipeline/predict_upcoming.py`: trains logistic regression on all 8 seasons and scores upcoming fixtures.

Run it yourself:
```bash
pip install -r requirements.txt -r requirements-pipeline.txt   # needs Java 17 or newer for PySpark
python pipeline/features_spark.py
python pipeline/train_validate.py
python -m pytest tests
```

**Results (run on 2026-10-18).** Accuracy of picking the match result (home win, draw or away win). Each test season has 375 matches. "Always home win" is the baseline.

| Test season | Train matches | Always home win | Weighted model (form only) | Logistic regression | Gradient boosting |
|---|---|---|---|---|---|
| 2021/22 | 1065 | 43.2% | 50.1% | 48.8% | 47.7% |
| 2022/23 | 1440 | 48.3% | 52.3% | 50.7% | 49.1% |
| 2023/24 | 1815 | 45.9% | 53.1% | 54.7% | 53.1% |
| 2024/25 | 2190 | 41.1% | 47.7% | 48.0% | 47.7% |
| 2025/26 | 2565 | 42.4% | 44.0% | 47.5% | 46.9% |
| All 5 seasons | | 44.2% | 49.4% | 49.9% | 48.9% |

What this shows: the trained models beat always picking a home win in every season, by 2 to 9 percentage points for logistic regression, and about 5.7 points over all 5 seasons. They are not clearly better than the simple weighted model (the weighted model wins in 2 of 5 seasons). With 375 matches a season, one standard error is about 2.5 points, so season to season differences of a few points are mostly noise. Gradient boosting does not beat logistic regression here; with only 8 features and about 3000 matches that is expected. The always home win baseline ranges from 41.1% to 48.3% across seasons, and the best model per season from 47.7% to 54.7%.

Known limits: results based form only (no shots, injuries, lineups or odds), draws are almost never predicted, and a team's first matches after promotion are excluded. Two live pipeline notes: the football-data.org form feed returns matches oldest first, and `scripts/main.py` now sorts them newest first before scoring (before this, the weighted model weighted the oldest results most). Time savings from automation (for example hours of manual reruns) are not measured by this code.

## Honest limitations (please read before relying on this)

1. **Injuries and lineups are scraped, not API-fed.** There is no reliable
   free structured API for either. Scraping is fragile by nature — the
   selectors in `injuries_news.py` and `lineups.py` are placeholders that
   need to be pointed at real, verified page structures and re-checked
   periodically. Both are written to fail safe (keep old data, log a
   warning) rather than crash or silently corrupt data, but "safe failure"
   still means stale data if a site changes its layout.
2. **No free "breaking news" feed exists.** Real-time manager quotes,
   transfer news, etc. aren't wired in. You could extend `injuries_news.py`
   with a news-search step, but any AI-summarization of it would need an
   LLM API call, which has a small per-call cost (cents), not zero.
3. **Two models, one transparent and one trained.** The weighted factor
   model in `scripts/model.py` stays as a transparent baseline: hand set
   weights, not fitted, and in the live pipeline it can use injuries and
   lineups. The trained model (logistic regression and gradient boosting in
   `pipeline/`) only sees results based form, because historical injuries and
   lineups are not available. Neither beats a model built on paid data
   (Opta, StatsBomb) and both are weak on draws. See the results table below
   for what the trained model actually achieves.
4. **Playstyle, manager tactical edge, and key-player lists are manual.**
   These genuinely change slowly and are better curated by you than
   guessed at by scraping — but it does mean upkeep, not full automation.
5. **GitHub Actions cron isn't wall-clock precise** — schedule times can
   slip by a few minutes under load. Fine for this use case, but don't
   expect it firing at exactly :00 every time.

## Upgrading later (if budget opens up)

- Swap `injuries_news.py` for a paid injury API (Sportmonks ~$30-50/mo) —
  drop-in replacement, same output shape.
- Add richer features to the trained model (shots, odds, injuries once a historical source exists).
- Add real breaking-news ingestion via a news API + a cheap LLM call to
  summarize/tag it as a factor.

## Tuning the model

Edit the weights in `scripts/config.py` (`WEIGHTS` dict). They're
initialized to reasonable-feeling values, not statistically fitted — as
you compare predictions to actual results over a few gameweeks, adjust
weights toward what seems predictive for your eye. There's no substitute
here for watching it run for a month and recalibrating.
