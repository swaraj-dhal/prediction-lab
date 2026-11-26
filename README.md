# Prediction Lab: setup

This repo refreshes NFL and NBA player data every day and shows it on a web page.

## One-time setup (about 10 minutes)

1. Create a free GitHub account, then a new **public** repository (name it e.g. `prediction-lab`).
2. Upload everything in this folder to it: `index.html`, `build_data.py`, `requirements.txt`, `data.json`, and the `.github` folder.
   (Tip: on the repo page choose "Add file" > "Upload files". Drag the whole folder in.)
3. Turn on the page: **Settings > Pages > Source: Deploy from a branch > main > / (root) > Save.**
   Your site will be at `https://YOUR-USERNAME.github.io/prediction-lab/`.
4. Turn on the daily job: open the **Actions** tab, enable workflows, pick "Refresh prediction data" and press **Run workflow** once.
   After that it runs by itself at 6 AM and 1:30 PM Pacific.
5. Open the Actions run and check the log. It prints which sources worked. The page's yellow banner also shows any source that failed.

## Optional: real sportsbook lines

Without lines, each row's line is just the median of recent games (shown in orange), so you type your book's line in. To pull lines automatically:

1. Get an API key at https://the-odds-api.com (player props require a paid plan, so check pricing).
2. In your repo: **Settings > Secrets and variables > Actions > New repository secret.**
   Name: `ODDS_API_KEY`. Value: your key. Never put the key in a file or paste it in a chat.

## Optional: your own lines

Add a `lines.json` file next to `build_data.py`:

    {"Josh Allen|Passing yards": 248.5, "Jayson Tatum|Points": 27.5}

## What it uses

- NFL stats, schedule, spreads, totals and injuries: nflverse (free, no key).
- NBA game logs: the `nba_api` package.
- NBA injuries: ESPN's public injury feed.
- Lines: The Odds API (optional).

## Known limits

- NBA and ESPN steps were not testable where this was built. If one fails the first time, the page shows the error and the NFL side still works. Send the Actions log to get it fixed.
- No NFL game-by-game opponent position matchups (WR vs CB, etc.), no weather, no live lineup news during the day.
- Sportsbooks can set better lines than any model built on public data. Treat picks as estimates.
