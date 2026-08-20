"""
test_source.py — trial a single RSS source WITHOUT touching mentions.json

Run this manually for 24-48h before adding a new region to SOURCES in
scrape.py. Prints what would have been extracted, so you can eyeball
whether the LLM is finding real stance data or just noise on a source
that's news-wire style rather than opinion-blog style.

Usage:
    python test_source.py "https://www.finews.com/news/english-news?format=feed&type=rss"
"""

import sys
from scrape import fetch_full_article_text, extract_mentions
import feedparser


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_source.py <rss_url>")
        sys.exit(1)

    rss_url = sys.argv[1]
    feed = feedparser.parse(rss_url)

    print(f"Feed: {rss_url}")
    print(f"Entries found: {len(feed.entries)}\n")

    for entry in feed.entries[:5]:  # just the 5 newest, this is a manual spot-check
        title = entry.get("title", "(no title)")
        link = entry.get("link")
        print(f"--- {title[:70]} ---")
        print(f"URL: {link}")

        text = fetch_full_article_text(link)
        if not text:
            print("RESULT: fetch failed or content too short (likely paywalled)\n")
            continue

        print(f"Extracted article length: {len(text)} chars")
        mentions = extract_mentions(text)
        if not mentions:
            print("RESULT: no stock/stance mentions extracted\n")
        else:
            print(f"RESULT: {len(mentions)} mention(s) found:")
            for m in mentions:
                print(f"   {m.get('ticker')}: {m.get('stance')}")
            print()


if __name__ == "__main__":
    main()