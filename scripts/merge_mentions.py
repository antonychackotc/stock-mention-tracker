"""
merge_mentions.py — combine local (multi-source) and remote (bot-updated
single-source) mentions.json versions after a git merge conflict.

FIXED: dedupe by (source_id, ticker) pair, not just source_id — one
article can mention many different tickers, and the first version of
this script wrongly kept only one ticker per article, discarding real
data.
"""

import json

with open("local_mentions.json", "r", encoding="utf-8") as f:
    local = json.load(f)

with open("remote_mentions.json", "r", encoding="utf-8") as f:
    remote = json.load(f)

local_mentions = local.get("mentions", [])
remote_mentions = remote.get("mentions", [])

seen = set()
merged = []

for m in local_mentions + remote_mentions:
    source_key = m.get("source_id") or m.get("source_url")
    ticker = m.get("ticker")
    key = (source_key, ticker)
    if source_key and key not in seen:
        seen.add(key)
        merged.append(m)

output = {
    "mentions": merged,
    "last_updated": max(
        local.get("last_updated") or "",
        remote.get("last_updated") or "",
    ),
}

with open("data/mentions.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Local had {len(local_mentions)} mentions")
print(f"Remote had {len(remote_mentions)} mentions")
print(f"Merged total: {len(merged)} mentions (true duplicates removed)")