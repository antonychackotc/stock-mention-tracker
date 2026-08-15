# Stock Mention Tracker

A Serenity-style tracker: monitors a public figure's posts, extracts stock mentions, classifies stance, and publishes an auto-updating dashboard, running entirely free on GitHub (Actions + Pages), no VPS needed.

## Setup needed before this runs for real

1. Pick the target Reddit account and fill in TARGET_REDDIT_USERNAME in scripts/scrape.py
2. Fill in TARGET_NAME in scripts/build_dashboard.py
3. Create a free Reddit API app at https://www.reddit.com/prefs/apps (type: script) to get a client ID and secret
4. Wire in a real LLM call in classify_stance() inside scrape.py, currently a placeholder that always returns neutral
5. Add repo secrets on GitHub: Settings, Secrets and variables, Actions: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT, LLM_API_KEY
6. Enable GitHub Pages: repo Settings, Pages, Source: GitHub Actions
7. Test manually first: Actions tab, select workflow, Run workflow button
