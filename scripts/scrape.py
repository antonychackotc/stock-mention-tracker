"""
scrape.py - fetches recent posts from an RSS feed, uses an LLM (with a
fallback chain of providers) to extract real stock/company mentions and
classify stance, and appends results to data/mentions.json.
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


def _build_extraction_prompt(text):
    return (
        "Read the following article text. Identify any publicly traded "
        "companies or stock tickers mentioned, and classify the stance "
        "toward each as bullish, bearish, or neutral based on the context.\n\n"
        "Respond with ONLY a JSON array, no other text, in this exact format:\n"
        '[{"ticker": "AAPL", "stance": "bullish"}, {"ticker": "TSLA", "stance": "neutral"}]\n\n'
        "If a company is mentioned but has no clear public ticker, use its "
        "common short name instead (e.g. \"Fed\" is not a ticker, skip it - "
        "only include actual publicly traded companies).\n"
        "If no companies/stocks are mentioned, respond with exactly: []\n\n"
        f"Article text:\n{text[:3000]}"
    )


def _parse_json_array(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []


def _try_grok(prompt, api_key):
    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "grok-beta",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _try_gemini(prompt, api_key):
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30,
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
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def extract_mentions(text):
    prompt = _build_extraction_prompt(text)

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
            mentions = _parse_json_array(raw)
            return mentions
        except Exception as e:
            print(f"  [{env_name}] failed: {e}")
            continue

    print("  All providers failed - no mentions extracted for this post")
    return []


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

        extracted = extract_mentions(item["text"])
        published = item["published"]
        mentioned_at = (
            datetime(*published[:6], tzinfo=timezone.utc).isoformat()
            if published else datetime.now(timezone.utc).isoformat()
        )

        for entry in extracted:
            ticker = entry.get("ticker", "").upper().strip()
            stance = entry.get("stance", "neutral").lower().strip()
            if stance not in ("bullish", "bearish", "neutral"):
                stance = "neutral"
            if not ticker:
                continue

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