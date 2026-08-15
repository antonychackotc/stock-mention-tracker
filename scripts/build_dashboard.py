"""
build_dashboard.py - reads data/mentions.json and generates a static HTML
dashboard into docs/ (GitHub Pages serves whatever is in docs/ automatically
once Pages is enabled for this repo).
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

DATA_FILE = Path("data/mentions.json")
OUTPUT_FILE = Path("docs/index.html")

TARGET_NAME = "The Big Picture (Barry Ritholtz)"


def load_dataset():
    return json.loads(DATA_FILE.read_text())


def within_days(mention, days):
    mentioned_at = datetime.fromisoformat(mention["mentioned_at"])
    return mentioned_at >= datetime.now(timezone.utc) - timedelta(days=days)


def summarize(mentions):
    by_ticker = defaultdict(lambda: {"bullish": 0, "bearish": 0, "neutral": 0, "count": 0})
    for m in mentions:
        by_ticker[m["ticker"]]["count"] += 1
        by_ticker[m["ticker"]][m["stance"]] += 1
    return dict(sorted(by_ticker.items(), key=lambda x: -x[1]["count"]))


def render_table(summary):
    rows = ""
    for ticker, stats in summary.items():
        rows += f"""
        <tr>
          <td><strong>{ticker}</strong></td>
          <td>{stats['count']}</td>
          <td class="bull">{stats['bullish']}</td>
          <td class="bear">{stats['bearish']}</td>
          <td>{stats['neutral']}</td>
        </tr>"""
    return rows


def render_html(dataset):
    all_mentions = dataset["mentions"]
    daily = summarize([m for m in all_mentions if within_days(m, 1)])
    weekly = summarize([m for m in all_mentions if within_days(m, 7)])
    monthly = summarize([m for m in all_mentions if within_days(m, 28)])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{TARGET_NAME} - Stock Mention Tracker</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ font-size: 28px; }}
  .updated {{ color: #666; font-size: 13px; margin-bottom: 30px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 40px; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #eee; }}
  th {{ color: #888; font-size: 12px; text-transform: uppercase; }}
  .bull {{ color: #16a34a; font-weight: 600; }}
  .bear {{ color: #dc2626; font-weight: 600; }}
  .disclaimer {{ font-size: 13px; color: #888; border-top: 1px solid #eee; padding-top: 20px; margin-top: 40px; }}
</style>
</head>
<body>
  <h1>{TARGET_NAME} - Stock Mention Tracker</h1>
  <p class="updated">Last updated: {dataset.get('last_updated', 'never')}</p>

  <h2>Daily</h2>
  <table>
    <tr><th>Ticker</th><th>Mentions</th><th>Bullish</th><th>Bearish</th><th>Neutral</th></tr>
    {render_table(daily)}
  </table>

  <h2>Weekly</h2>
  <table>
    <tr><th>Ticker</th><th>Mentions</th><th>Bullish</th><th>Bearish</th><th>Neutral</th></tr>
    {render_table(weekly)}
  </table>

  <h2>Monthly</h2>
  <table>
    <tr><th>Ticker</th><th>Mentions</th><th>Bullish</th><th>Bearish</th><th>Neutral</th></tr>
    {render_table(monthly)}
  </table>

  <p class="disclaimer">
    This is a fan-built information aggregation tool tracking {TARGET_NAME}'s
    public posts. Not affiliated with {TARGET_NAME}. Stance labels are
    AI-inferred and may be inaccurate. Not investment advice - always verify
    against the original source posts and consult a licensed financial advisor.
  </p>
</body>
</html>"""


def main():
    dataset = load_dataset()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(render_html(dataset))
    print(f"Dashboard written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()