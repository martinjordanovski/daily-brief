# daily-brief

AI, technology and software development news, summarised every morning by Claude. Leadership & management, psychology and investing are added on Mondays.

Shown at **https://martinjordanovski.com/daily-brief/**. The page reads `data/index.json` and `briefs/*.json` straight from this repo. An RSS feed of the briefs is in `feed.xml`.

## How it runs

`.github/workflows/daily-brief.yml`, every day at 05:13 UTC:

1. **Tripwire**: lists any commit since the last run that changed `.github/`, `scripts/` or `sources.json`. If there is one, the run fails at the end (after publishing), so GitHub emails you. After your own edits that's expected; otherwise revoke the API key.
2. **Fetch**: `scripts/fetch.py` reads the sources in `sources.json` (RSS/Atom, Hacker News, github-radar), keeps the last 26 hours (7 days for weekly sections), removes duplicates. Broken sources are skipped and listed in `data/health.json`.
3. **Summarize**: `scripts/summarize.py` sends each section to Claude and validates the answer. It signs in without an API key: GitHub issues a short-lived identity token, which Anthropic swaps for a ~10-minute access token (Workload Identity Federation).
4. **Commit**: `briefs/YYYY-MM-DD.json`, `data/index.json`, `data/health.json`, `feed.xml`.

"Run workflow" with **check_only** ticked tests the sources without calling Claude or saving anything.

## Security

- No third-party GitHub Actions: the job clones the repo with plain `git` and runs Python standard library only.
- No API key is stored. The Claude Console federation rule only accepts identity tokens from this repo's `main` branch, and maps them to a dedicated workspace with a $10 monthly limit. The rule, organization and workspace IDs are repository variables (not secrets).
- News text is untrusted. The model has no tools, must answer in a fixed JSON format, and returns item ids instead of links; links come only from the fetched feeds. All text is cut to fixed lengths and stripped of markup and URLs, and the page shows it as plain text under a strict Content Security Policy.
- Force-pushes to `main` are blocked by a ruleset, so a malicious commit can't be erased from history.

## Editing sources

Add or remove entries in `sources.json`. Types: `rss` (any RSS/Atom feed, `https` only), `hn` (Hacker News front page, optional `min_points` and `keywords`), `github_radar`. Each section has a `stories` limit and a `cadence` of `daily` or `weekly`.
