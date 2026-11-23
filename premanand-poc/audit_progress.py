"""
READ-ONLY audit: which episodes have transcripts, which are embedded,
and how many Q&A pairs still need embedding.

This script never writes, moves, or deletes anything. It only reads.
Run it from inside the premanand-poc folder:
    python3 audit_progress.py
"""
import json
import re
from collections import Counter
from pathlib import Path

TRANSCRIPT_FILES = ["transcripts.jsonl", "transcripts_recovered.jsonl"]
CACHE_JSONL = "embeddings_cache.jsonl"
CACHE_JSON_OLD = "embeddings_cache.json"
RANGE_LO, RANGE_HI = 1, 1400

NUM_RE = re.compile(r"#\s*(\d+)")


def ep_num(name):
    m = NUM_RE.search(name or "")
    return int(m.group(1)) if m else None


def compress(nums):
    nums = sorted(set(nums))
    if not nums:
        return "none"
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = n
    out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(out)


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # skip a truncated/broken line


def pairs_from_record(rec):
    """Same QUESTION -> following ANSWER(s) pairing as rag_query.py."""
    src = rec.get("source_file", "?")
    turns = rec.get("turns", [])
    out = []
    i = 0
    while i < len(turns):
        t = turns[i]
        sp = t.get("speaker") if isinstance(t, dict) else None
        if sp is None:
            i += 1
            continue
        if sp == "QUESTION":
            q = t.get("text", "")
            j = i + 1
            has_answer = False
            while (j < len(turns) and isinstance(turns[j], dict)
                   and turns[j].get("speaker") == "ANSWER"):
                has_answer = True
                j += 1
            if has_answer:
                out.append((src, q))
            i = j
        else:
            i += 1
    return out


def coverage_line(label, nums):
    present = {n for n in nums if RANGE_LO <= n <= RANGE_HI}
    missing = [n for n in range(RANGE_LO, RANGE_HI + 1) if n not in present]
    beyond = sorted(n for n in nums if n > RANGE_HI)
    print(f"{label}: have {len(present)} of {RANGE_HI - RANGE_LO + 1} "
          f"episodes in {RANGE_LO}-{RANGE_HI}")
    print(f"   ALL PRESENT? {'YES' if not missing else 'NO'}")
    if missing:
        print(f"   missing ({len(missing)}): {compress(missing)}")
    if beyond:
        print(f"   also have beyond {RANGE_HI}: {compress(beyond)}")


def main():
    print("=" * 70)
    print("TRANSCRIPT FILES")
    print("=" * 70)
    t_pairs = set()
    t_eps = set()
    t_no_num = set()
    for name in TRANSCRIPT_FILES:
        p = Path(name)
        if not p.exists():
            print(f"{name}: NOT FOUND")
            continue
        lines = 0
        files = set()
        pairs = set()
        for rec in read_jsonl(p):
            lines += 1
            files.add(rec.get("source_file", "?"))
            pairs.update(pairs_from_record(rec))
        nums = {ep_num(f) for f in files} - {None}
        print(f"{name}: {lines} records, {len(files)} distinct source files, "
              f"{len(pairs)} Q&A pairs, "
              f"episode numbers {min(nums) if nums else '-'}..{max(nums) if nums else '-'}")
        t_pairs |= pairs
        t_eps |= nums
        t_no_num |= {f for f in files if ep_num(f) is None}
    print(f"\nCOMBINED transcripts: {len(t_eps)} distinct episode numbers, "
          f"{len(t_pairs)} distinct Q&A pairs")
    if t_no_num:
        print(f"   {len(t_no_num)} source file(s) have no #number in the name")

    print("\n" + "=" * 70)
    print("EMBEDDINGS (what you can actually search)")
    print("=" * 70)
    e_pairs = set()
    e_eps = set()
    dims = Counter()
    for name, is_jsonl in ((CACHE_JSONL, True), (CACHE_JSON_OLD, False)):
        p = Path(name)
        if not p.exists():
            print(f"{name}: NOT FOUND")
            continue
        if is_jsonl:
            entries = read_jsonl(p)
        else:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, MemoryError) as e:
                print(f"{name}: could not be read ({type(e).__name__})")
                continue
        count = 0
        local_pairs = set()
        local_dims = Counter()
        for e in entries:
            count += 1
            key = (e.get("source_file", "?"), e.get("question", ""))
            local_pairs.add(key)
            local_dims[len(e.get("embedding", []))] += 1
        nums = {ep_num(k[0]) for k in local_pairs} - {None}
        print(f"{name}: {count} entries, {len(local_pairs)} distinct pairs, "
              f"{len(nums)} episodes, vector sizes {dict(local_dims)}")
        e_pairs |= local_pairs
        e_eps |= nums
        dims.update(local_dims)
    print(f"\nCOMBINED embedded: {len(e_pairs)} distinct Q&A pairs, "
          f"{len(e_eps)} episodes")
    if len(dims) > 1:
        print("   WARNING: more than one vector size found - mixed embedding "
              "models would break search. Do not merge these.")

    print("\n" + "=" * 70)
    print(f"COVERAGE OF EPISODES {RANGE_LO}-{RANGE_HI}")
    print("=" * 70)
    coverage_line("Transcribed", t_eps)
    print()
    coverage_line("Embedded   ", e_eps)

    print("\n" + "=" * 70)
    print("WHAT IS LEFT")
    print("=" * 70)
    to_embed = t_pairs - e_pairs
    cache_only = e_pairs - t_pairs
    to_embed_eps = {ep_num(k[0]) for k in to_embed} - {None}
    cache_only_eps = {ep_num(k[0]) for k in cache_only} - {None}
    print(f"Transcribed but NOT embedded yet : {len(to_embed)} pairs "
          f"(episodes: {compress(to_embed_eps)})")
    print(f"Embedded but NOT in any transcript file: {len(cache_only)} pairs "
          f"(episodes: {compress(cache_only_eps)})")
    print("   ^ these Q&A texts only survive inside the embeddings cache; "
          "keep it backed up.")
    pct = (len(e_pairs & t_pairs) / len(t_pairs) * 100) if t_pairs else 0
    print(f"\nOf the pairs in your transcript files, {pct:.1f}% are embedded.")


if __name__ == "__main__":
    main()
