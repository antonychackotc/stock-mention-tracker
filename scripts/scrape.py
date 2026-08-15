"""
scrape.py - fetches recent posts from an RSS feed, extracts stock/ticker
mentions, classifies each as bullish/bearish/neutral using a fallback
chain of LLM providers (cheapest/free first, paid last), and appends
results to data/mentions.json.
"""

import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

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


def _build_prompt(text, ticker):
    return (
        f"Classify the stance toward stock ticker {ticker} in this text as "
        f"exactly one word: bullish, bearish, or neutral.\n\nText: {text}\n\n"
        f"Answer with one word only."
    )


def _clean_stance(raw):
    raw = raw.strip().lower()
    for word in ("bullish", "bearish", "neutral"):
        if word in raw:
            return word
    return "neutral"


def _try_grok(prompt, api_key):
    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "grok-beta",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 5,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _try_gemini(prompt, api_key):
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _try_anthropic(prompt, api_key):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 5,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def classify_stance(text, ticker):
    prompt = _build_prompt(text, ticker)

    chain = [
        ("GROK_API_KEY_1", _try_grok),
        ("GROK_API_KEY_2", _try_grok),
        ("GEMINI_API_KEY", _try_gemini),
        ("ANTHROPIC_API_KEY", _try_anthropic),
    ]

    for env_name, fn in chain:
        api_key = os.environ.get(env_name)
        if not api_key:
            continue
        try:
            raw = fn(prompt, api_key)
            return _clean_stance(raw)
        except Exception as e:
            print(f"  [{env_name}] failed: {e}")
            continue

    print("  All providers failed - defaulting to neutral")
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