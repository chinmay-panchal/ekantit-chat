"""
Batch-process every audio file in ./episodes/ through Gemini, using 2
parallel workers. Each worker owns its own pool of 2 API keys (with
automatic fallback if one key hits its rate/quota limit) — so this
combines the reliability of the original KeyPool approach with 2x
throughput from running two workers at once.

Resumable: episodes already present in transcripts.jsonl (by filename)
are skipped automatically, so you can stop and re-run anytime.

Usage:
    python batch_process.py
"""
import sys
import os
import json
import time
import re
import random
import shutil
import uuid
import queue
import threading
from pathlib import Path
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Load keys from environment, not hardcoded. Set these in your shell
# or a .env file (with python-dotenv) before running:
#   export GEMINI_API_KEY_1="..."
#   export GEMINI_API_KEY_2="..."
#   export GEMINI_API_KEY_3="..."
#   export GEMINI_API_KEY_4="..."
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY_1"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
    os.environ.get("GEMINI_API_KEY_4"),
]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

if len(GEMINI_API_KEYS) < 2:
    print("Need at least 2 GEMINI_API_KEY_* env vars set (4 recommended for 2 workers).")
    sys.exit(1)

# Split keys into 2 groups — one group per worker. Handles any even count.
mid = len(GEMINI_API_KEYS) // 2
KEY_GROUPS = [GEMINI_API_KEYS[:mid], GEMINI_API_KEYS[mid:]]

MODEL = "gemini-3.1-flash-lite"
EPISODES_DIR = Path("episodes")
OUTPUT_FILE = Path("transcripts.jsonl")
FAILED_LOG = Path("failed_episodes.jsonl")
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}

SECONDS_BETWEEN_REQUESTS = 5
MAX_RETRIES_PER_KEY = 4  # raised from 2 — overload retries need more room
FILE_PROCESSING_TIMEOUT = 120  # avoid hanging forever on a stuck upload
DELETE_AFTER_PROCESSING = True

PROMPT = """You are transcribing a Hindi satsang Q&A recording featuring
Premanand Ji Maharaj and devotees.

Listen to the full audio and transcribe it in Hindi (Devanagari script).
Split the transcript into an alternating sequence of QUESTION (the
devotee) and ANSWER (Premanand Ji Maharaj) turns, based on who is
actually speaking in the audio (voice, tone, pauses) — not just sentence
content.

Important hint: when a turn STARTS with a vocative/address phrase like
"महाराज जी", "राधे-राधे महाराज जी", or similar — addressing the teacher
directly at the start of a turn — that is a very strong signal the turn
is the DEVOTEE's question, not the teacher's answer. Premanand Ji does
not refer to himself this way. However, if such a phrase appears mid-way
through what is otherwise a continuous teaching/explanation (not at the
start of a new turn), treat it as part of that ANSWER — teachers can
reference or quote such phrases while explaining, without it meaning a
new speaker has started.

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:
{
  "turns": [
    {"speaker": "QUESTION", "text": "..."},
    {"speaker": "ANSWER", "text": "..."}
  ]
}
"""

write_lock = threading.Lock()
print_lock = threading.Lock()


def safe_print(msg):
    with print_lock:
        print(msg)


class KeyPool:
    """Rotates through a small set of Gemini API keys, skipping any
    that are currently quota-exhausted (429). 503 overload errors are
    handled separately with backoff, not by rotating keys — a 503 is
    Google's server being busy, not a problem with the key itself."""

    def __init__(self, keys):
        self.keys = keys
        self.clients = [genai.Client(api_key=k) for k in keys]
        self.exhausted = [False] * len(keys)
        self.current = 0

    def get_client(self):
        for _ in range(len(self.clients)):
            if not self.exhausted[self.current]:
                return self.current, self.clients[self.current]
            self.current = (self.current + 1) % len(self.clients)
        return None, None

    def mark_exhausted(self, index, worker_id):
        self.exhausted[index] = True
        safe_print(
            f"[Worker {worker_id}] Key #{index + 1} rate/quota-limited — switching.")
        self.current = (self.current + 1) % len(self.clients)

    def all_exhausted(self):
        return all(self.exhausted)


def classify_error(e):
    """429/quota errors mean THIS key is done — rotate to the next one.
    503/unavailable errors mean Google's servers are busy — backing off
    and retrying the SAME key is the right move, not rotating."""
    msg = str(e).lower()
    if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
        return "quota"
    if "503" in msg or "unavailable" in msg or "overloaded" in msg:
        return "overload"
    return "other"


def parse_metadata_from_filename(filename):
    episode_num_match = re.search(r"#?(\d+)", filename)
    date_match = re.search(r"(\d{2}-\d{2}-\d{4})", filename)
    return {
        "episode_num": episode_num_match.group(1) if episode_num_match else None,
        "date": date_match.group(1) if date_match else None,
    }


def load_processed_files():
    processed = set()
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    processed.add(record["source_file"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return processed


def log_failed_episode(audio_path, reason):
    with write_lock:
        with open(FAILED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "source_file": audio_path.name,
                "reason": reason,
                "timestamp": time.time(),
            }, ensure_ascii=False) + "\n")


def try_repair_json(raw_reply):
    """Best-effort recovery for truncated/malformed JSON — pulls out
    whatever QUESTION/ANSWER turn objects it can find via regex rather
    than discarding the whole episode on one bad character."""
    pattern = re.compile(
        r'\{\s*"speaker"\s*:\s*"(QUESTION|ANSWER)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        re.DOTALL,
    )
    turns = []
    for m in pattern.finditer(raw_reply):
        speaker, text = m.group(1), m.group(2)
        try:
            text = json.loads(f'"{text}"')  # unescape
        except json.JSONDecodeError:
            pass
        turns.append({"speaker": speaker, "text": text})
    return turns


def process_one_file(pool, audio_path, worker_id):
    """Try the pool's current key. On quota (429) errors, rotate to the
    next key. On overload (503) errors, back off and retry the same key —
    rotating keys does nothing for a server-side overload. Times out
    instead of hanging forever on a stuck upload."""
    while True:
        key_index, client = pool.get_client()
        if client is None:
            return None  # all keys in this worker's pool exhausted

        for attempt in range(1, MAX_RETRIES_PER_KEY + 1):
            temp_path = audio_path.parent / \
                f"_upload_{uuid.uuid4().hex}{audio_path.suffix}"
            try:
                shutil.copyfile(audio_path, temp_path)
                uploaded_file = client.files.upload(file=str(temp_path))

                wait_started = time.time()
                while uploaded_file.state.name == "PROCESSING":
                    if time.time() - wait_started > FILE_PROCESSING_TIMEOUT:
                        raise TimeoutError(
                            f"File stuck in PROCESSING for over {FILE_PROCESSING_TIMEOUT}s"
                        )
                    time.sleep(2)
                    uploaded_file = client.files.get(name=uploaded_file.name)

                if uploaded_file.state.name == "FAILED":
                    raise RuntimeError("Gemini file processing failed")

                response = client.models.generate_content(
                    model=MODEL,
                    contents=[PROMPT, uploaded_file],
                )

                raw_reply = response.text.strip()
                if raw_reply.startswith("```"):
                    raw_reply = raw_reply.split("```")[1]
                    if raw_reply.startswith("json"):
                        raw_reply = raw_reply[4:]
                    raw_reply = raw_reply.strip()

                try:
                    parsed = json.loads(raw_reply)
                    return parsed.get("turns", [])
                except json.JSONDecodeError as je:
                    safe_print(
                        f"[Worker {worker_id}] JSON parse failed ({je}) — attempting repair")
                    repaired = try_repair_json(raw_reply)
                    if repaired:
                        safe_print(
                            f"[Worker {worker_id}] Repaired {len(repaired)} turns from malformed JSON")
                        return repaired
                    raise

            except Exception as e:
                kind = classify_error(e)

                if kind == "quota":
                    pool.mark_exhausted(key_index, worker_id)
                    break  # move to next key immediately, no point retrying this one

                if kind == "overload":
                    wait = min(60, 5 * (2 ** attempt)) + random.uniform(0, 3)
                    safe_print(
                        f"[Worker {worker_id}] 503 overload (attempt {attempt}/{MAX_RETRIES_PER_KEY}) "
                        f"— backing off {wait:.0f}s")
                    time.sleep(wait)
                    continue  # retry same key after backoff

                safe_print(
                    f"[Worker {worker_id}] Attempt {attempt}/{MAX_RETRIES_PER_KEY} failed: {e}")
                if attempt < MAX_RETRIES_PER_KEY:
                    time.sleep(10 * attempt)
            finally:
                if temp_path.exists():
                    temp_path.unlink()
        else:
            # Retries exhausted on this key without hitting quota — give up on this file for now
            return None

        if pool.all_exhausted():
            return None


def worker(worker_id, keys, file_queue, total_count, done_counter):
    pool = KeyPool(keys)

    while True:
        try:
            audio_path = file_queue.get_nowait()
        except queue.Empty:
            break

        if pool.all_exhausted():
            safe_print(
                f"[Worker {worker_id}] All its keys exhausted — stopping this worker.")
            file_queue.put(audio_path)  # put it back for the other worker
            break

        safe_print(f"[Worker {worker_id}] Processing {audio_path.name}")
        turns = process_one_file(pool, audio_path, worker_id)

        if not turns:
            safe_print(
                f"[Worker {worker_id}] FAILED — {audio_path.name} (will retry on next run)")
            log_failed_episode(audio_path, "all_retries_exhausted")
            file_queue.task_done()
            continue

        metadata = parse_metadata_from_filename(audio_path.name)
        record = {
            "source_file": audio_path.name,
            "episode_num": metadata["episode_num"],
            "date": metadata["date"],
            "turns": turns,
        }

        with write_lock:
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            done_counter[0] += 1
            progress = done_counter[0]

        if DELETE_AFTER_PROCESSING:
            try:
                audio_path.unlink()
            except OSError as e:
                safe_print(
                    f"[Worker {worker_id}] Could not delete {audio_path.name}: {e}")

        safe_print(
            f"[Worker {worker_id}] Done ({progress}/{total_count}) — {len(turns)} turns — {audio_path.name}")
        file_queue.task_done()
        time.sleep(SECONDS_BETWEEN_REQUESTS)


def main():
    if not EPISODES_DIR.exists():
        print(
            f"'{EPISODES_DIR}' folder not found. Create it and put audio files inside.")
        sys.exit(1)

    all_files = sorted(
        p for p in EPISODES_DIR.rglob("*")
        if p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith("_upload_")
    )

    if not all_files:
        print(f"No audio files found in '{EPISODES_DIR}'.")
        sys.exit(1)

    processed = load_processed_files()
    remaining = [p for p in all_files if p.name not in processed]

    print(f"Total episodes found: {len(all_files)}")
    print(f"Already processed:    {len(processed)}")
    print(f"Remaining to process: {len(remaining)}")
    print(f"Workers: 2 ({len(KEY_GROUPS[0])}/{len(KEY_GROUPS[1])} keys)\n")

    if not remaining:
        print("Nothing left to do.")
        return

    file_queue = queue.Queue()
    for p in remaining:
        file_queue.put(p)

    done_counter = [0]
    threads = []
    for i, keys in enumerate(KEY_GROUPS, 1):
        t = threading.Thread(
            target=worker,
            args=(i, keys, file_queue, len(remaining), done_counter),
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    print(
        f"\nBatch run complete. {done_counter[0]}/{len(remaining)} processed this run.")


if __name__ == "__main__":
    main()
