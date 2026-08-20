"""
scrape.py — Big Picture Tracker multi-source scraper

Reads multiple RSS feeds (tagged by region), fetches full article text for
NEW posts only, extracts stock/company mentions + stance via an LLM
fallback chain, and appends results to data/mentions.json.

IMPORTANT: This is a reconstruction based on the documented behavior of
the original single-source (Ritholtz-only) scraper. Diff this against
your actual scrape.py before deploying — do not overwrite blindly.

Fallback chain: Groq (key 1) -> Groq (key 2) -> Gemini -> Claude (Anthropic)
Env vars expected (GitHub Actions secrets, names unchanged from original):
  GROK_API_KEY_1   (actually a Groq key, per earlier naming fix)
  GROK_API_KEY_2
  GEMINI_API_KEY
  ANTHROPIC_API_KEY
"""

import calendar
import json
import os
import re
import time
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

DATA_FILE = "data/mentions.json"

# Each source is independently rate-capped so one noisy feed can't drain
# the day's free-tier quota. Add/remove sources here only.
SOURCES = [
    {
        "name": "The Big Picture (Barry Ritholtz)",
        "region": "US",
        "rss_url": "https://ritholtz.com/feed",
        "max_new_per_run": 5,
    },
    {
        "name": "Klement on Investing",
        "region": "Europe",
        "rss_url": "https://klementoninvesting.substack.com/feed",
        "max_new_per_run": 5,
    },
    {
        "name": "Bursa Dummy",
        "region": "Asia",
        "rss_url": "https://bursadummy.blogspot.com/feeds/posts/default?alt=rss",
        "max_new_per_run": 5,
    },
    {
        "name": "SmallCaps.co.za",
        "region": "Africa",
        "rss_url": "https://smallcaps.co.za/feed",
        "max_new_per_run": 5,
    },
]

REQUEST_TIMEOUT = 15
USER_AGENT = "BigPictureTracker/1.0 (+https://antonychackotc.github.io/stock-mention-tracker/)"

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"  # backend extraction only — NOT the Capafy-facing model

EXTRACTION_PROMPT = """You are a financial text analyst. Read the article
text below and extract every individual publicly-traded STOCK or COMPANY
mentioned, along with the author's apparent stance toward it.

Return ONLY a JSON array, no other text, no markdown fences. Each element:
{{"ticker": "AAPL", "stance": "bullish" | "bearish" | "neutral"}}

DO NOT include:
- Market indices (e.g. S&P 500, Nasdaq, ^GSPC, ^IXIC, KLCI as an index,
  FTSE, DAX) — only individual companies
- Currencies, commodities, or crypto tickers
- ETFs unless the author is discussing it as a specific investable
  product with a clear stance (not just mentioning "the market")

If no individual stocks/companies are mentioned, return an empty
array: []

Article text:
{article_text}
"""


# ---------------------------------------------------------------------------
# STATE / DEDUPE
# ---------------------------------------------------------------------------

def load_existing_mentions():
    """Returns the full data dict: {"mentions": [...], "last_updated": ...}
    Matches the REAL production schema (confirmed from live mentions.json),
    not a guessed flat-list format."""
    if not os.path.exists(DATA_FILE):
        return {"mentions": [], "last_updated": None}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if "mentions" not in data:
                data["mentions"] = []
            return data
        except json.JSONDecodeError:
            return {"mentions": [], "last_updated": None}


def already_seen_ids(data):
    """Dedupe by source_id (the real unique key in production), falling
    back to source_url for any older records that might lack it."""
    seen = set()
    for m in data.get("mentions", []):
        key = m.get("source_id") or m.get("source_url")
        if key:
            seen.add(key)
    return seen


# ---------------------------------------------------------------------------
# FETCHING
# ---------------------------------------------------------------------------

def fetch_full_article_text(url):
    """Fetch the article page and extract readable text. Best-effort —
    strips scripts/nav/footer, returns plain text of <p> tags. Falls back
    to the RSS summary if the page fetch fails (paywall, block, etc.)."""
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paragraphs)
        text = re.sub(r"\n{2,}", "\n", text).strip()
        # Guard against paywalled pages that return a short teaser only —
        # treat anything under ~400 chars as unusable rather than feeding
        # the LLM a near-empty prompt.
        if len(text) < 400:
            return None
        return text[:8000]  # cap tokens sent to the LLM
    except requests.RequestException:
        return None


def get_new_entries(source, seen_ids):
    feed = feedparser.parse(source["rss_url"])
    new_entries = []
    for entry in feed.entries:
        entry_id = entry.get("id") or entry.get("link")
        if not entry_id or entry_id in seen_ids:
            continue
        new_entries.append(entry)
    # newest first, capped per source
    new_entries.sort(
        key=lambda e: e.get("published_parsed") or time.gmtime(0), reverse=True
    )
    return new_entries[: source["max_new_per_run"]]


# ---------------------------------------------------------------------------
# LLM FALLBACK CHAIN
# ---------------------------------------------------------------------------

def _parse_json_array(raw_text):
    raw_text = raw_text.strip()
    raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def _try_groq(api_key, prompt):
    if not api_key:
        return None
    try:
        resp = requests.post(
            GROQ_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_array(content)
    except Exception:
        return None


def _try_gemini(api_key, prompt):
    if not api_key:
        return None
    try:
        resp = requests.post(
            f"{GEMINI_ENDPOINT}?key={api_key}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_array(content)
    except Exception:
        return None


def _try_anthropic(api_key, prompt):
    if not api_key:
        return None
    try:
        resp = requests.post(
            ANTHROPIC_ENDPOINT,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["content"][0]["text"]
        return _parse_json_array(content)
    except Exception:
        return None


def extract_mentions(article_text):
    prompt = EXTRACTION_PROMPT.format(article_text=article_text)

    keys = {
        "Groq (key 1)": os.environ.get("GROK_API_KEY_1"),
        "Groq (key 2)": os.environ.get("GROK_API_KEY_2"),
        "Gemini": os.environ.get("GEMINI_API_KEY"),
        "Anthropic": os.environ.get("ANTHROPIC_API_KEY"),
    }
    missing = [name for name, key in keys.items() if not key]
    if missing:
        print(f"  [WARNING] no API key set for: {', '.join(missing)} "
              f"— these providers will be skipped, not just 'found nothing'")

    result = _try_groq(keys["Groq (key 1)"], prompt)
    if result is not None:
        return result

    result = _try_groq(keys["Groq (key 2)"], prompt)
    if result is not None:
        return result

    result = _try_gemini(keys["Gemini"], prompt)
    if result is not None:
        return result

    result = _try_anthropic(keys["Anthropic"], prompt)
    if result is not None:
        return result

    if all(not k for k in keys.values()):
        print("  [ERROR] ALL 4 providers had no API key set — this result is "
              "MEANINGLESS, not a real 'no mentions found'. Set your API keys "
              "as environment variables before trusting this test.")
    else:
        print("  [WARNING] all configured providers failed (network error, "
              "rate limit, or bad key) — this is NOT a confirmed 'no mentions'")

    return []  # all providers failed — don't crash the run, just skip this post


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    data = load_existing_mentions()
    existing_mentions = data.get("mentions", [])
    seen = already_seen_ids(data)
    new_mentions = []

    for source in SOURCES:
        entries = get_new_entries(source, seen)
        print(f"[{source['name']}] {len(entries)} new post(s) to process")

        for entry in entries:
            link = entry.get("link")
            entry_id = entry.get("id") or link
            title = entry.get("title", "")
            # Normalize to ISO 8601 regardless of the source feed's raw
            # date format (Ritholtz gives ISO, others give RFC 822) — this
            # is what caused the dashboard crash on mixed-format dates.
            if entry.get("published_parsed"):
                published = datetime.fromtimestamp(
                    calendar.timegm(entry.published_parsed), tz=timezone.utc
                ).isoformat()
            else:
                published = datetime.now(timezone.utc).isoformat()

            article_text = fetch_full_article_text(link)
            if not article_text:
                print(f"  skip (fetch failed or paywalled): {link}")
                continue

            extracted = extract_mentions(article_text)
            if not extracted:
                print(f"  no mentions found: {title[:60]}")
                continue

            for item in extracted:
                ticker = item.get("ticker", "").upper().strip()
                stance = item.get("stance", "neutral").lower().strip()
                if not ticker or stance not in ("bullish", "bearish", "neutral"):
                    continue
                new_mentions.append({
                    "source_id": entry_id,
                    "ticker": ticker,
                    "stance": stance,
                    "text_excerpt": f"{title}\n{article_text[:280]}",
                    "source_url": link,
                    "source_name": source["name"],
                    "source_region": source["region"],
                    "mentioned_at": published,
                    "type": "post",
                })
            print(f"  extracted {len(extracted)} mention(s): {title[:60]}")

    if new_mentions:
        combined_mentions = existing_mentions + new_mentions
        output = {
            "mentions": combined_mentions,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Wrote {len(new_mentions)} new mention(s) to {DATA_FILE} "
              f"(total now {len(combined_mentions)})")
    else:
        print("No new mentions this run.")


if __name__ == "__main__":
    main()