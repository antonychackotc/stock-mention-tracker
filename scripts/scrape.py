"""
scrape.py — fetches recent public posts/comments from a target Reddit user,
extracts stock/ticker mentions, classifies each as bullish/bearish/neutral,
and appends results to data/mentions.json (the historical dataset).
"""

import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import praw

TARGET_REDDIT_USERNAME = "CHANGE_ME"
DATA_FILE = Path("data/mentions.json")
MAX_POSTS_PER_RUN = 25

TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")


def get_reddit_client():
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "stock-mention-tracker/1.0"),
    )


def fetch_recent_posts(reddit, username, limit=MAX_POSTS_PER_RUN):
    redditor = reddit.redditor(username)
    items = []

    for submission in redditor.submissions.new(limit=limit):
        items.append({
            "type": "post",
            "id": submission.id,
            "text": f"{submission.title}\n{submission.selftext}",
            "url": f"https://reddit.com{submission.permalink}",
            "created_utc": submission.created_utc,
        })

    for comment in redditor.comments.new(limit=limit):
        items.append({
            "type": "comment",
            "id": comment.id,
            "text": comment.body,
            "url": f"https://reddit.com{comment.permalink}",
            "created_utc": comment.created_utc,
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
    return "neutral"  # placeholder until an LLM client is wired in


def load_existing_dataset():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"mentions": [], "last_updated": None}


def save_dataset(dataset):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    dataset["last_updated"] = datetime.now(timezone.utc).isoformat()
    DATA_FILE.write_text(json.dumps(dataset, indent=2))


def main():
    reddit = get_reddit_client()
    dataset = load_existing_dataset()
    existing_ids = {m["source_id"] for m in dataset["mentions"]}

    items = fetch_recent_posts(reddit, TARGET_REDDIT_USERNAME)
    new_mentions = []

    for item in items:
        if item["id"] in existing_ids:
            continue

        tickers = extract_tickers(item["text"])
        for ticker in tickers:
            stance = classify_stance(item["text"], ticker)
            new_mentions.append({
                "source_id": item["id"],
                "ticker": ticker,
                "stance": stance,
                "text_excerpt": item["text"][:280],
                "source_url": item["url"],
                "mentioned_at": datetime.fromtimestamp(
                    item["created_utc"], tz=timezone.utc
                ).isoformat(),
                "type": item["type"],
            })

    dataset["mentions"].extend(new_mentions)
    save_dataset(dataset)
    print(f"Added {len(new_mentions)} new mentions. "
          f"Total dataset size: {len(dataset['mentions'])}")


if __name__ == "__main__":
    main()