"""
scrape.py - fetches recent posts from an RSS feed, extracts stock/ticker
mentions, classifies each as bullish/bearish/neutral, and appends results
to data/mentions.json (the historical dataset).
"""

import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser

FEED_URL = "https://ritholtz.com/feed"
TARGET_NAME = "The Big Picture (Barry Ritholtz)"
DATA_FILE = Path("data/mentions.json")

TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")


def fetch_recent_posts():
    feed = feedparser.parse(FEED_URL)
    items = []

    for entry in feed.entries:
        text = entry.get("title", "") + "\n" + entry.get("summary", "")
        items.append({
            "id": entry.get("id", entry.get("link")),
            "text": text,
            "url": entry.get("link"),
            "published": entry.get("published_parsed"),
        })

    return items


def extract_tickers(text):
    return sorted(set(TICKER_PATTERN.findall(text)))


def classify_stance(text, ticker):
    prompt = (
        f"Classify the stance toward stock ticker {ticker} in this text as "
        f"exactly one word: bullish, bearish, or neutral.\n\nText: {text}\n\n"
        f"Answer with one word only."
    )
    return "neutral"


def load_existing_dataset():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"mentions": [], "last_updated": None}


def save_dataset(dataset):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    dataset["last_updated"] = datetime.now(timezone.utc).isoformat()
    DATA_FILE.write_text(json.dumps(dataset, indent=2))


def main():
    dataset = load_existing_dataset()
    existing_ids = {m["source_id"] for m in dataset["mentions"]}

    items = fetch_recent_posts()
    new_mentions = []

    for item in items:
        if item["id"] in existing_ids:
            continue

        tickers = extract_tickers(item["text"])
        for ticker in tickers:
            stance = classify_stance(item["text"], ticker)
            published = item["published"]
            mentioned_at = (
                datetime(*published[:6], tzinfo=timezone.utc).isoformat()
                if published else datetime.now(timezone.utc).isoformat()
            )
            new_mentions.append({
                "source_id": item["id"],
                "ticker": ticker,
                "stance": stance,
                "text_excerpt": item["text"][:280],
                "source_url": item["url"],
                "mentioned_at": mentioned_at,
                "type": "post",
            })

    dataset["mentions"].extend(new_mentions)
    save_dataset(dataset)
    print(f"Added {len(new_mentions)} new mentions. "
          f"Total dataset size: {len(dataset['mentions'])}")


if __name__ == "__main__":
    main()