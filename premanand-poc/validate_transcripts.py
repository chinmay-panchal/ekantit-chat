"""
Sanity-check transcripts.jsonl: counts, empty-turn detection, and
speaker-alternation check (flags episodes where QUESTION/ANSWER don't
alternate properly, which usually signals a labeling issue worth a
manual look).

Usage:
    python validate_transcripts.py
"""
import json
from pathlib import Path

FILE = Path("transcripts.jsonl")

def main():
    if not FILE.exists():
        print(f"{FILE} not found.")
        return

    total = 0
    empty_turns = []
    non_alternating = []
    total_turns = 0

    with open(FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            total += 1
            turns = record.get("turns", [])
            total_turns += len(turns)

            if not turns:
                empty_turns.append(record["source_file"])
                continue

            speakers = [t["speaker"] for t in turns]
            for a, b in zip(speakers, speakers[1:]):
                if a == b:
                    non_alternating.append(record["source_file"])
                    break

    print(f"Total episodes in file: {total}")
    print(f"Total turns overall:    {total_turns}")
    print(f"Avg turns/episode:      {total_turns / total:.1f}" if total else "")
    print(f"\nEpisodes with EMPTY turns ({len(empty_turns)}):")
    for f_ in empty_turns[:10]:
        print(f"  - {f_}")

    print(f"\nEpisodes with NON-ALTERNATING speakers ({len(non_alternating)}):")
    for f_ in non_alternating[:10]:
        print(f"  - {f_}")

    print("\n--- Sample preview (first episode) ---")
    with open(FILE, "r", encoding="utf-8") as f:
        first = json.loads(f.readline())
        for t in first["turns"][:4]:
            print(f"[{t['speaker']}] {t['text'][:80]}...")


if __name__ == "__main__":
    main()
