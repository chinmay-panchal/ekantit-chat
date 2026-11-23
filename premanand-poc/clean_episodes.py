"""
Clean up the episodes folder. Put this file in premanand-poc and run it
from there.

    python clean_episodes.py            dry run: only SHOWS what it would do
    python clean_episodes.py --delete   delete audio whose transcript is already
                                        saved (+ leftover _upload_* temp copies)
    python clean_episodes.py --move     move all remaining audio into ONE folder
                                        (episodes/to_process/)

An audio file counts as "already transcribed" if its filename, or its
#episode number, is in transcripts.jsonl with at least one turn.
Nothing is deleted or moved unless you pass --delete or --move, and both
refuse to run while batch_process.py is running.
"""
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
EPISODES = BASE / "episodes"
TRANSCRIPTS = BASE / "transcripts.jsonl"
TARGET = EPISODES / "to_process"
DUPES = BASE / "episodes_duplicates"
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


def norm(s):
    """Same text can be stored in different Unicode forms (Devanagari)."""
    return unicodedata.normalize("NFC", s)


def ep_num(name):
    m = re.search(r"#\s*(\d+)", name)
    return int(m.group(1)) if m else None


def mb(path):
    try:
        return path.stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


def ranges(nums):
    out, start, prev = [], None, None
    for n in sorted(nums):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append((start, prev))
            start = prev = n
    if start is not None:
        out.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def load_done():
    """Names and episode numbers that have a saved transcript with turns."""
    names, nums, empty = set(), set(), 0
    with open(TRANSCRIPTS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("turns"):
                empty += 1
                continue
            src = rec.get("source_file", "")
            names.add(norm(src))
            n = ep_num(src)
            if n is not None:
                nums.add(n)
    return names, nums, empty


def batch_running():
    try:
        r = subprocess.run(["pgrep", "-f", "batch_process.py"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return bool(r.stdout.strip())


def scan():
    audio, temp = [], []
    for p in sorted(EPISODES.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("_upload_"):
            temp.append(p)
        elif p.suffix.lower() in AUDIO_EXT:
            audio.append(p)
    return audio, temp


def safe_dest(folder, name):
    base = Path(name)
    dest = folder / name
    i = 1
    while dest.exists():
        dest = folder / f"{base.stem}__{i}{base.suffix}"
        i += 1
    return dest


def short(p, width=70):
    s = p.name
    return s if len(s) <= width else s[:width] + "..."


def main():
    do_delete = "--delete" in sys.argv
    do_move = "--move" in sys.argv

    if not EPISODES.exists():
        print(f"'{EPISODES}' not found.")
        return
    if not TRANSCRIPTS.exists():
        print(f"'{TRANSCRIPTS}' not found - nothing to compare with, stopping.")
        return

    names, nums, empty = load_done()
    audio, temp = scan()

    done, keep, why = [], [], {}
    for p in audio:
        n = ep_num(p.name)
        if norm(p.name) in names:
            done.append(p)
            why[p] = "same filename"
        elif n is not None and n in nums:
            done.append(p)
            why[p] = f"episode #{n} already transcribed"
        else:
            keep.append(p)

    print(f"Audio files found        : {len(audio)}")
    print(f"Already transcribed      : {len(done)}  "
          f"({sum(mb(p) for p in done) / 1024:.1f} GB can be freed)")
    print(f"Not transcribed (keep)   : {len(keep)}")
    print(f"Leftover _upload_ copies : {len(temp)}  "
          f"({sum(mb(p) for p in temp) / 1024:.1f} GB)")
    if empty:
        print(f"Note: {empty} transcript record(s) have no turns, so their "
              f"audio is NOT treated as done.")

    if done:
        print()
        print("Examples of files that would be deleted:")
        for p in done[:8]:
            print(f"  {short(p)}   [{why[p]}]")

    keep_nums = [ep_num(p.name) for p in keep]
    nums_keep = {n for n in keep_nums if n is not None}
    print()
    print("Files that stay (still need transcription):")
    print("  episodes:", ranges(nums_keep) or "-")
    no_num = [p for p in keep if ep_num(p.name) is None]
    if no_num:
        print(f"  {len(no_num)} file(s) without a #number in the name")
    seen, dup_nums = set(), set()
    for n in keep_nums:
        if n is None:
            continue
        if n in seen:
            dup_nums.add(n)
        seen.add(n)
    if dup_nums:
        print("  present more than once:", ranges(dup_nums),
              "(extra copies go to episodes_duplicates/ on --move)")

    if not (do_delete or do_move):
        print()
        print("Dry run only - nothing was changed.")
        print("Next: python clean_episodes.py --delete")
        return

    if batch_running():
        print()
        print("batch_process.py is running right now. Stop it first "
              "(Ctrl+C in its terminal), then run this again.")
        return

    if do_delete:
        total = len(done) + len(temp)
        if total == 0:
            print()
            print("Nothing to delete.")
        else:
            print()
            answer = input(f"Delete {len(done)} transcribed file(s) and "
                           f"{len(temp)} temp copy(ies)? Type YES to confirm: ")
            if answer.strip() != "YES":
                print("Cancelled, nothing deleted.")
                return
            freed = 0.0
            for p in done + temp:
                size = mb(p)
                try:
                    p.unlink()
                    freed += size
                except OSError as e:
                    print("could not delete", p.name, e)
            print(f"Deleted. Freed {freed / 1024:.1f} GB.")

    if do_move:
        TARGET.mkdir(parents=True, exist_ok=True)
        taken = set()
        for p in keep:
            if p.parent == TARGET and ep_num(p.name) is not None:
                taken.add(ep_num(p.name))

        moved = duped = 0
        for p in keep:
            if p.parent == TARGET:
                continue
            n = ep_num(p.name)
            dest = TARGET / p.name
            if (n is not None and n in taken) or dest.exists():
                DUPES.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(safe_dest(DUPES, p.name)))
                duped += 1
            else:
                shutil.move(str(p), str(dest))
                if n is not None:
                    taken.add(n)
                moved += 1

        left_done = len([p for p in done if p.exists()])
        print()
        print(f"Moved {moved} file(s) into {TARGET}")
        if duped:
            print(f"{duped} duplicate copy(ies) moved to {DUPES} (not deleted)")
        if left_done:
            print(f"{left_done} already-transcribed file(s) are still in "
                  f"place - run with --delete to remove them")
        print("Next: python batch_process.py")


if __name__ == "__main__":
    main()
