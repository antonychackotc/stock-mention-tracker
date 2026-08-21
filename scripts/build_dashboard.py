"""
build_dashboard.py - reads data/mentions.json and generates a styled static
HTML dashboard into docs/ (GitHub Pages serves whatever is in docs/).

Updated to support multiple sources across regions (US/Europe/Asia/Africa).
Keep this SOURCES list in sync with scrape.py's SOURCES — it's duplicated
here (not imported) so this script has no dependency on scrape.py's
network/API code, just its own static metadata for attribution.
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

DATA_FILE = Path("data/mentions.json")
OUTPUT_FILE = Path("docs/index.html")

DASHBOARD_TITLE = "Big Picture Tracker"

# Static metadata for footer attribution — name + url per source, keyed by
# the same "region" string used in scrape.py's SOURCES list.
SOURCES = [
    {"name": "The Big Picture (Barry Ritholtz)", "region": "US", "url": "https://ritholtz.com"},
    {"name": "Klement on Investing", "region": "Europe", "url": "https://klementoninvesting.substack.com"},
    {"name": "Bursa Dummy", "region": "Asia", "url": "https://bursadummy.blogspot.com"},
    {"name": "SmallCaps.co.za", "region": "Africa", "url": "https://smallcaps.co.za"},
]

REGION_COLORS = {
    "US": "#7c6cf0",
    "Europe": "#0ea5b5",
    "Asia": "#e0862a",
    "Africa": "#c0479a",
    "US-legacy": "#7c6cf0",  # older records predating the region field
}


def load_dataset():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def parse_mentioned_at(value):
    """Handle both date formats seen across sources: ISO 8601 (Ritholtz)
    and RFC 822 (Klement/Bursa Dummy/SmallCaps). Never crash on a bad
    date — fall back to "now" so one malformed record doesn't break the
    whole dashboard build."""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def within_days(mention, days):
    mentioned_at = parse_mentioned_at(mention["mentioned_at"])
    return mentioned_at >= datetime.now(timezone.utc) - timedelta(days=days)


def summarize(mentions):
    by_ticker = defaultdict(lambda: {
        "bullish": 0, "bearish": 0, "neutral": 0, "count": 0,
        "latest_url": "", "regions": set(),
    })
    for m in mentions:
        t = by_ticker[m["ticker"]]
        t["count"] += 1
        t[m["stance"]] += 1
        t["latest_url"] = m.get("source_url", "")
        # Older records (pre-multi-source) won't have source_region —
        # label them US-legacy rather than silently dropping the tag.
        t["regions"].add(m.get("source_region", "US-legacy"))
    return dict(sorted(by_ticker.items(), key=lambda x: -x[1]["count"]))


def stance_badge(stats):
    if stats["bullish"] > stats["bearish"] and stats["bullish"] > 0:
        return '<span class="badge badge-bull">bullish</span>'
    if stats["bearish"] > stats["bullish"] and stats["bearish"] > 0:
        return '<span class="badge badge-bear">bearish</span>'
    return '<span class="badge badge-neutral">neutral</span>'


def region_tags(regions):
    tags = ""
    for r in sorted(regions):
        color = REGION_COLORS.get(r, "#8a8f98")
        tags += f'<span class="region-tag" style="background:{color}1a;color:{color};">{r}</span>'
    return tags


def render_cards(summary):
    if not summary:
        return '<p class="empty">No mentions in this window yet.</p>'
    cards = ""
    for ticker, stats in summary.items():
        # data-region carries ALL regions this ticker appeared under, space
        # separated, so the JS filter can match on any of them.
        data_region = " ".join(sorted(stats["regions"]))
        detail_url = f"tickers/{safe_filename(ticker)}.html"
        cards += f"""
        <a class="ticker-card" data-region="{data_region}" href="{detail_url}">
          <div class="ticker-card-top">
            <span class="ticker-symbol">{ticker}</span>
            {stance_badge(stats)}
          </div>
          <div class="region-row">{region_tags(stats['regions'])}</div>
          <div class="ticker-stats">
            <span>{stats['count']} mention{'s' if stats['count'] != 1 else ''}</span>
            <span class="stat-bull">{stats['bullish']} bull</span>
            <span class="stat-bear">{stats['bearish']} bear</span>
            <span class="stat-neutral">{stats['neutral']} neutral</span>
          </div>
        </a>"""
    return cards


def render_footer_sources():
    items = ""
    for s in SOURCES:
        items += f'<li>{s["name"]} ({s["region"]}) — <a href="{s["url"]}" target="_blank" rel="noopener">{s["url"].replace("https://", "")}</a></li>'
    return items


def safe_filename(ticker):
    """Ticker symbols like BRK.B contain characters unsafe for filenames.
    Replace non-alphanumeric chars with underscore."""
    return "".join(c if c.isalnum() else "_" for c in ticker)


def render_ticker_detail_page(ticker, ticker_mentions):
    """Generates the actual per-ticker detail page: bull case bullets,
    risks bullets (both built from real extracted 'reasoning' text, not
    invented), and the full mention list. NO price chart / 'vs prior
    close' data — that requires a separate price-API integration this
    build does NOT include."""
    ticker_mentions_sorted = sorted(
        ticker_mentions, key=lambda m: m.get("mentioned_at", ""), reverse=True
    )

    bull_count = sum(1 for m in ticker_mentions if m["stance"] == "bullish")
    bear_count = sum(1 for m in ticker_mentions if m["stance"] == "bearish")
    neutral_count = sum(1 for m in ticker_mentions if m["stance"] == "neutral")

    first_mention = min(m.get("mentioned_at", "") for m in ticker_mentions)
    latest_mention = max(m.get("mentioned_at", "") for m in ticker_mentions)

    def fmt_date(iso_str):
        dt = parse_mentioned_at(iso_str)
        return dt.strftime("%b %d, %Y")

    # Bull case / Risks are built ONLY from mentions that actually have a
    # non-empty "reasoning" field — older records (pre-reasoning-field)
    # and mentions where the LLM found no clear reason are correctly
    # excluded, not padded with invented text.
    bull_points = [
        m for m in ticker_mentions_sorted
        if m["stance"] == "bullish" and m.get("reasoning")
    ]
    bear_points = [
        m for m in ticker_mentions_sorted
        if m["stance"] == "bearish" and m.get("reasoning")
    ]

    def render_points(points):
        if not points:
            return '<p class="empty">No specific reasoning captured yet for this stance.</p>'
        html = ""
        for m in points:
            html += f"""
            <div class="point-row">
              <span class="point-text">{m['reasoning']}</span>
              <a href="{m.get('source_url', '#')}" target="_blank" rel="noopener" class="point-date">{fmt_date(m.get('mentioned_at', ''))} ↗</a>
            </div>"""
        return html

    def render_all_posts(mentions):
        html = ""
        for m in mentions:
            reasoning_html = f'<div class="post-reasoning">{m["reasoning"]}</div>' if m.get("reasoning") else ""
            html += f"""
            <div class="post-row">
              <div class="post-top">
                <span class="post-date">{fmt_date(m.get('mentioned_at', ''))}</span>
                {stance_badge_solo(m['stance'])}
                <span class="post-source">{m.get('source_name', 'Unknown source')} ({m.get('source_region', 'US-legacy')})</span>
              </div>
              {reasoning_html}
              <a href="{m.get('source_url', '#')}" target="_blank" rel="noopener" class="post-link">View original post ↗</a>
            </div>"""
        return html

    regions = sorted(set(m.get("source_region", "US-legacy") for m in ticker_mentions))
    region_tags_html = "".join(
        f'<span class="region-tag" style="background:{REGION_COLORS.get(r, "#8a8f98")}1a;color:{REGION_COLORS.get(r, "#8a8f98")};">{r}</span>'
        for r in regions
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} - Big Picture Tracker</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 800px; margin: 0 auto; padding: 40px 24px 80px;
    color: #17181c; background: #fafafa; line-height: 1.5;
  }}
  .back-link {{ font-size: 13px; color: #6b6f76; text-decoration: none; margin-bottom: 20px; display: inline-block; }}
  .back-link:hover {{ color: #7c6cf0; }}
  .ticker-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin: 12px 0 6px; }}
  h1 {{ font-size: 32px; font-weight: 800; }}
  .meta {{ font-size: 12.5px; color: #8a8f98; text-align: right; }}
  .region-row {{ display: flex; gap: 6px; margin: 10px 0 20px; }}
  .region-tag {{ font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 10px; text-transform: uppercase; }}
  .stat-summary {{ display: flex; gap: 20px; margin-bottom: 28px; font-size: 13px; color: #4a4738; }}
  .stat-summary b {{ font-size: 16px; }}
  .section-title {{ font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; color: #6b6f76; margin: 32px 0 12px; }}
  .points-box {{ background: #fff; border: 1px solid #ececec; border-radius: 12px; padding: 16px 20px; }}
  .points-box.bull {{ border-left: 4px solid #16a34a; }}
  .points-box.bear {{ border-left: 4px solid #dc2626; }}
  .point-row {{ display: flex; justify-content: space-between; align-items: baseline; padding: 8px 0; border-bottom: 1px solid #f1f1f1; font-size: 13.5px; }}
  .point-row:last-child {{ border-bottom: none; }}
  .point-date {{ font-size: 11px; color: #8a8f98; white-space: nowrap; margin-left: 12px; text-decoration: none; }}
  .empty {{ color: #8a8f98; font-size: 13px; font-style: italic; }}
  .post-row {{ background: #fff; border: 1px solid #ececec; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px; }}
  .post-top {{ display: flex; align-items: center; gap: 10px; font-size: 12px; color: #8a8f98; }}
  .post-date {{ font-weight: 600; color: #17181c; }}
  .post-reasoning {{ font-size: 13.5px; margin: 8px 0; color: #3a3830; }}
  .post-link {{ font-size: 12px; color: #7c6cf0; text-decoration: none; }}
  .badge {{ font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 8px; text-transform: uppercase; }}
  .badge-bull {{ background: #e3f7ea; color: #16a34a; }}
  .badge-bear {{ background: #fdeaea; color: #dc2626; }}
  .badge-neutral {{ background: #f1f1f1; color: #6b6f76; }}
  .disclaimer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ececec; font-size: 11.5px; color: #8a8f98; }}
</style>
</head>
<body>
  <a href="../index.html" class="back-link">← Back to dashboard</a>
  <div class="ticker-header">
    <h1>{ticker}</h1>
    <div class="meta">First mention {fmt_date(first_mention)}<br>Latest mention {fmt_date(latest_mention)}</div>
  </div>
  <div class="region-row">{region_tags_html}</div>
  <div class="stat-summary">
    <div><b>{len(ticker_mentions)}</b> total mentions</div>
    <div><b style="color:#16a34a">{bull_count}</b> bullish</div>
    <div><b style="color:#dc2626">{bear_count}</b> bearish</div>
    <div><b style="color:#6b6f76">{neutral_count}</b> neutral</div>
  </div>

  <div class="section-title">Bull Case</div>
  <div class="points-box bull">{render_points(bull_points)}</div>

  <div class="section-title">Risks Mentioned</div>
  <div class="points-box bear">{render_points(bear_points)}</div>

  <div class="section-title">All Mentions ({len(ticker_mentions)})</div>
  {render_all_posts(ticker_mentions_sorted)}

  <div class="disclaimer">
    Stance and reasoning are AI-inferred from the original post text and
    may be inaccurate. This is not investment advice. Always verify
    against the original source, linked on every entry above.
  </div>
</body>
</html>"""


def stance_badge_solo(stance):
    if stance == "bullish":
        return '<span class="badge badge-bull">bullish</span>'
    if stance == "bearish":
        return '<span class="badge badge-bear">bearish</span>'
    return '<span class="badge badge-neutral">neutral</span>'


def build_all_ticker_pages(all_mentions):
    """Groups ALL mentions (not just within a time window) by ticker and
    writes one detail page per ticker to docs/tickers/{ticker}.html."""
    by_ticker = defaultdict(list)
    for m in all_mentions:
        by_ticker[m["ticker"]].append(m)

    tickers_dir = OUTPUT_FILE.parent / "tickers"
    tickers_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for ticker, mentions in by_ticker.items():
        filename = safe_filename(ticker) + ".html"
        page_html = render_ticker_detail_page(ticker, mentions)
        (tickers_dir / filename).write_text(page_html, encoding="utf-8")
        count += 1
    return count


def render_html(dataset):
    all_mentions = dataset["mentions"]
    daily = summarize([m for m in all_mentions if within_days(m, 1)])
    weekly = summarize([m for m in all_mentions if within_days(m, 7)])
    monthly = summarize([m for m in all_mentions if within_days(m, 28)])
    total_mentions = len(all_mentions)
    total_tickers = len(set(m["ticker"] for m in all_mentions))
    # Normalize "US-legacy" into "US" for the region COUNT stat only — it's
    # not a real 5th region, just older records missing the region field.
    # The card tags still show "US-LEGACY" separately, which is fine/useful.
    normalized_regions = set(
        "US" if m.get("source_region", "US-legacy") == "US-legacy" else m.get("source_region")
        for m in all_mentions
    )
    total_regions = len(normalized_regions)

    last_updated_raw = dataset.get("last_updated")
    if last_updated_raw:
        dt = datetime.fromisoformat(last_updated_raw)
        last_updated = dt.strftime("%b %d, %Y at %H:%M UTC")
    else:
        last_updated = "never"

    region_filter_buttons = '<button class="region-btn active" data-filter="all">All</button>'
    for r in ["US", "Europe", "Asia", "Africa"]:
        region_filter_buttons += f'<button class="region-btn" data-filter="{r}">{r}</button>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{DASHBOARD_TITLE} - Multi-Region Stock Mention Tracker</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 960px; margin: 0 auto; padding: 48px 24px 80px;
    color: #17181c; background: #fafafa; line-height: 1.5;
  }}
  .eyebrow {{
    font-size: 13px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
    color: #7c6cf0; margin-bottom: 8px;
  }}
  h1 {{ font-size: 30px; font-weight: 700; margin: 0 0 6px; letter-spacing: -0.01em; }}
  .subtitle {{ color: #6b6f76; font-size: 15px; margin: 0 0 24px; }}
  .stat-row {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat-box {{
    background: #fff; border: 1px solid #ececec; border-radius: 12px;
    padding: 16px 20px; min-width: 140px;
  }}
  .stat-num {{ font-size: 24px; font-weight: 700; color: #17181c; }}
  .stat-label {{ font-size: 12px; color: #8a8f98; text-transform: uppercase; letter-spacing: 0.03em; margin-top: 2px; }}
  .region-filter-row {{ display: flex; gap: 8px; margin-bottom: 32px; flex-wrap: wrap; }}
  .region-btn {{
    font-size: 13px; font-weight: 600; padding: 7px 16px; border-radius: 20px;
    border: 1px solid #ececec; background: #fff; color: #6b6f76; cursor: pointer;
  }}
  .region-btn.active {{ background: #17181c; color: #fff; border-color: #17181c; }}
  h2 {{ font-size: 18px; font-weight: 600; margin: 40px 0 16px; display: flex; align-items: center; gap: 8px; }}
  .window-tag {{ font-size: 12px; font-weight: 500; color: #8a8f98; background: #f1f0fe; padding: 3px 10px; border-radius: 20px; }}
  .ticker-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }}
  .ticker-card {{
    display: block; background: #fff; border: 1px solid #ececec; border-radius: 12px;
    padding: 16px; text-decoration: none; color: inherit; transition: border-color 0.15s;
  }}
  .ticker-card:hover {{ border-color: #7c6cf0; }}
  .ticker-card-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .ticker-symbol {{ font-size: 17px; font-weight: 700; letter-spacing: -0.01em; }}
  .badge {{ font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.02em; }}
  .badge-bull {{ background: #e3f7ea; color: #16a34a; }}
  .badge-bear {{ background: #fdeaea; color: #dc2626; }}
  .badge-neutral {{ background: #f1f1f1; color: #6b6f76; }}
  .region-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
  .region-tag {{ font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; text-transform: uppercase; letter-spacing: 0.02em; }}
  .ticker-stats {{ display: flex; gap: 10px; flex-wrap: wrap; font-size: 12px; color: #8a8f98; }}
  .stat-bull {{ color: #16a34a; font-weight: 600; }}
  .stat-bear {{ color: #dc2626; font-weight: 600; }}
  .stat-neutral {{ color: #6b6f76; }}
  .empty {{ color: #8a8f98; font-size: 14px; font-style: italic; padding: 20px 0; }}
  .footer {{
    margin-top: 56px; padding-top: 24px; border-top: 1px solid #ececec;
    font-size: 12.5px; color: #8a8f98; line-height: 1.7;
  }}
  .footer a {{ color: #7c6cf0; }}
  .footer ul {{ margin: 8px 0 16px; padding-left: 20px; }}
</style>
</head>
<body>
  <div class="eyebrow">Fan-built · updates hourly · {total_regions} region{'s' if total_regions != 1 else ''} tracked</div>
  <h1>{DASHBOARD_TITLE}</h1>
  <p class="subtitle">Multi-region stock mention tracker · last updated {last_updated}</p>

  <div class="stat-row">
    <div class="stat-box"><div class="stat-num">{total_tickers}</div><div class="stat-label">Tickers tracked</div></div>
    <div class="stat-box"><div class="stat-num">{total_mentions}</div><div class="stat-label">Total mentions</div></div>
    <div class="stat-box"><div class="stat-num">{total_regions}</div><div class="stat-label">Regions</div></div>
  </div>

  <div class="region-filter-row" id="regionFilters">
    {region_filter_buttons}
  </div>

  <h2>Daily <span class="window-tag">last 24h</span></h2>
  <div class="ticker-grid">{render_cards(daily)}</div>

  <h2>Weekly <span class="window-tag">last 7 days</span></h2>
  <div class="ticker-grid">{render_cards(weekly)}</div>

  <h2>Monthly <span class="window-tag">last 28 days</span></h2>
  <div class="ticker-grid">{render_cards(monthly)}</div>

  <div class="footer">
    This is a fan-built information aggregation tool tracking public posts
    from multiple independent market commentators across regions:
    <ul>{render_footer_sources()}</ul>
    Not affiliated with any of the above. Stance labels are AI-inferred and
    may be inaccurate. Not investment advice - always verify against the
    original source posts and consult a licensed financial advisor.
  </div>

  <script>
    (function() {{
      var buttons = document.querySelectorAll('.region-btn');
      var cards = document.querySelectorAll('.ticker-card');
      buttons.forEach(function(btn) {{
        btn.addEventListener('click', function() {{
          buttons.forEach(function(b) {{ b.classList.remove('active'); }});
          btn.classList.add('active');
          var filter = btn.getAttribute('data-filter');
          cards.forEach(function(card) {{
            if (filter === 'all') {{
              card.style.display = '';
            }} else {{
              var regions = (card.getAttribute('data-region') || '').split(' ');
              card.style.display = regions.indexOf(filter) !== -1 ? '' : 'none';
            }}
          }});
        }});
      }});
    }})();
  </script>
</body>
</html>"""


def main():
    dataset = load_dataset()
    all_mentions = dataset["mentions"]
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(render_html(dataset), encoding="utf-8")
    print(f"Dashboard written to {OUTPUT_FILE}")
    ticker_page_count = build_all_ticker_pages(all_mentions)
    print(f"Generated {ticker_page_count} ticker detail page(s) in {OUTPUT_FILE.parent}/tickers/")


if __name__ == "__main__":
    main()