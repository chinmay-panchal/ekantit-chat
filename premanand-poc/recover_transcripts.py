"""
Rebuild a transcripts file from embeddings_cache.jsonl.
Writes transcripts_recovered.jsonl (does NOT touch transcripts.jsonl).
"""
import json
import os
import re
from collections import OrderedDict

BASE = "/Users/shadowwolf/premanand-poc"
CACHE = os.path.join(BASE, "embeddings_cache.jsonl")
OUT = os.path.join(BASE, "transcripts_recovered.jsonl")

episodes = OrderedDict()
pair_count = 0

with open(CACHE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        src = row["source_file"]
        episodes.setdefault(src, []).append((row["question"], row["answer"]))
        pair_count += 1

with open(OUT, "w", encoding="utf-8") as out:
    for src, pairs in episodes.items():
        num_match = re.search(r"#(\d+)", src)
        date_match = re.search(r"(\d{2}-\d{2}-\d{4})", src)
        turns = []
        for q, a in pairs:
            turns.append({"speaker": "QUESTION", "text": q})
            turns.append({"speaker": "ANSWER", "text": a})
        record = {
            "source_file": src,
            "episode_num": int(num_match.group(1)) if num_match else None,
            "date": date_match.group(1) if date_match else None,
            "turns": turns,
        }
        out.write(json.dumps(record, ensure_ascii=False) + os.linesep)

print(f"Episodes: {len(episodes)}")
print(f"Q&A pairs: {pair_count}")
print(f"Written to: {OUT}")
