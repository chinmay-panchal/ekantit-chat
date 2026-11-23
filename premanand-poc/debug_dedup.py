import json
import unicodedata
from pathlib import Path

OUTPUT_FILE = Path("transcripts.jsonl")
EPISODES_DIR = Path("episodes")
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}

processed = set()
bad_lines = 0
with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            processed.add(json.loads(line)["source_file"])
        except (json.JSONDecodeError, KeyError):
            bad_lines += 1

all_files = [
    p.name for p in EPISODES_DIR.iterdir()
    if p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith("_upload_")
]

print(f"processed entries in jsonl : {len(processed)}  (bad lines: {bad_lines})")
print(f"files currently in episodes/: {len(all_files)}")

exact_overlap = [n for n in all_files if n in processed]
print(f"exact string overlap        : {len(exact_overlap)}")

if not exact_overlap and processed and all_files:
    p_sample = sorted(processed)[0]
    f_sample = all_files[0]
    print("\n--- sample comparison ---")
    print("from transcripts.jsonl:", repr(p_sample))
    print("from episodes/ folder :", repr(f_sample))
    print("same length?          :", len(p_sample) == len(f_sample))

    nfc_processed = {unicodedata.normalize("NFC", n) for n in processed}
    nfc_files = {unicodedata.normalize("NFC", n) for n in all_files}
    nfc_overlap = nfc_files & nfc_processed
    print(f"\noverlap after NFC normalization: {len(nfc_overlap)}")
