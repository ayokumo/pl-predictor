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
  model.py            # weighted-factor scoring engine
  main.py              # orchestrator, entrypoint for all modes
data/
  team_meta.json       # hand-maintained playstyle/manager/key-player data
  *.json               # generated data + predictions (committed by the Action)
index.html               # static dashboard, reads data/predictions.json
.github/workflows/
  predict.yml         # the free scheduler
```

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
3. **The prediction engine is a transparent weighted-factor model, not a
   trained ML model.** This is a deliberate trade-off for a free-data,
   explainable v1. It won't out-predict a professionally trained model
   using paid data (Opta, StatsBomb, etc.), but it's honest about its
   reasoning and cheap to run. Section below covers how to upgrade it.
4. **Playstyle, manager tactical edge, and key-player lists are manual.**
   These genuinely change slowly and are better curated by you than
   guessed at by scraping — but it does mean upkeep, not full automation.
5. **GitHub Actions cron isn't wall-clock precise** — schedule times can
   slip by a few minutes under load. Fine for this use case, but don't
   expect it firing at exactly :00 every time.

## Upgrading later (if budget opens up)

- Swap `injuries_news.py` for a paid injury API (Sportmonks ~$30-50/mo) —
  drop-in replacement, same output shape.
- Train a real model: football-data.org's free tier includes historical
  results back several seasons — enough for a simple logistic regression
  on (recent form, goal difference, home/away) predicting match outcome.
  `model.py` is structured so this is a contained swap.
- Add real breaking-news ingestion via a news API + a cheap LLM call to
  summarize/tag it as a factor.

## Tuning the model

Edit the weights in `scripts/config.py` (`WEIGHTS` dict). They're
initialized to reasonable-feeling values, not statistically fitted — as
you compare predictions to actual results over a few gameweeks, adjust
weights toward what seems predictive for your eye. There's no substitute
here for watching it run for a month and recalibrating.
