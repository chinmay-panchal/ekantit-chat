"""
Shared RAG module for Satsang Q&A.
Provides:
- Embeddings caching and loading (embeddings_cache.jsonl / embeddings_cache.json)
- Query rewriting / context resolution for multi-turn conversational retrieval
- Semantic retrieval using cosine similarity over gemini-embedding-2
- Hinglish answer generation using gemini-3.1-flash-lite (with fallbacks)
"""
import json
import math
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import errors

BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")

# Models
EMBED_MODEL = "gemini-embedding-2"
CHAT_MODEL = "gemini-3.1-flash-lite"
FALLBACK_MODELS = ["gemini-2.5-flash-lite"]
REWRITE_MODEL = "gemini-3.1-flash-lite"

# Files
TRANSCRIPTS_FILE = BASE_DIR / "transcripts.jsonl"
CACHE_JSONL_FILE = BASE_DIR / "embeddings_cache.jsonl"
CACHE_JSON_FILE = BASE_DIR / "embeddings_cache.json"
CACHE_NPZ_FILE = BASE_DIR / "embeddings.npz"
CACHE_META_FILE = BASE_DIR / "metadata.json.gz"
SKIPPED_TURNS_LOG = BASE_DIR / "skipped_turns.log"

# Configuration
TOP_K = 6
MAX_HISTORY_MESSAGES = 20

QUERY_REWRITE_PROMPT = """Given the conversation history and a follow-up question from a user seeking spiritual guidance, determine if the question depends on the conversation context.
- If it is a follow-up referring to previous topics, concepts, or pronouns (e.g. 'why is it important?', 'how can I overcome it?', 'aur bataiye', 'isse kaise bachein?'), rewrite it into a single, complete, standalone question that preserves the specific spiritual topic and context from the conversation.
- If the question is already independent and standalone (e.g. 'What is meditation?', 'Naam jap kaise karein?'), output the question as-is without altering its meaning.
- Do NOT answer the question.
- Do NOT add explanations or preamble.
- Output ONLY the standalone question in plain text.

Conversation History:
{history}

Follow-up Question: {query}
Standalone Question:"""

SYSTEM_PROMPT = """You are helping someone by drawing on the teachings of
Premanand Ji Maharaj, based ONLY on the Q&A excerpts provided below from
his actual satsang sessions.

Read the person's situation/question, then look at the excerpts — even
if none match their exact situation, identify the underlying spiritual
principles Premanand Ji teaches (e.g. naam-jap, surrender, seeing
God's grace, non-attachment) and apply them to the person's specific
situation, in his tone and style (warm, direct, often using stories,
Sanskrit/Hindi verses, and repeated emphasis on naam-jap).

Respond in Hinglish (Hindi language written in Roman/English script,
NOT Devanagari) — e.g. "Radhe-Radhe, dekho beta..." instead of
"राधे-राधे, देखो बच्चा...". Keep the tone, warmth and style of the
excerpts, just transliterate to Roman script. Do not invent facts about
Premanand Ji himself. Ground your answer in the principles shown in the
excerpts, adapted to the new situation.

Strict grounding rules:
- Quote a shloka, verse, scripture name or story ONLY if it appears in
  the excerpts above. Never add quotes from your own memory.
- Do not say things like "mere gurudev ne kaha" or "maine pichle satsang
  me bataya" unless the excerpts actually say that.
- If the excerpts don't cover the question well, say that briefly and
  give only the general principles that do appear in them.

Excerpts:
{context}

Person's situation/question:
{query}
"""

CONVERSATIONAL_SYSTEM_PROMPT = """You are helping someone by drawing on the teachings of
Premanand Ji Maharaj, based ONLY on the Q&A excerpts provided below from
his actual satsang sessions.

Read the person's situation/question and recent conversation history, then look at the excerpts — even
if none match their exact situation, identify the underlying spiritual
principles Premanand Ji teaches (e.g. naam-jap, surrender, seeing
God's grace, non-attachment) and apply them to the person's specific
situation, in his tone and style (warm, direct, often using stories,
Sanskrit/Hindi verses, and repeated emphasis on naam-jap).

Respond in Hinglish (Hindi language written in Roman/English script,
NOT Devanagari) — e.g. "Radhe-Radhe, dekho beta..." instead of
"राधे-राधे, देखो बच्चा...". Keep the tone, warmth and style of the
excerpts, just transliterate to Roman script. Do not invent facts about
Premanand Ji himself. Ground your answer in the principles shown in the
excerpts, adapted to the new situation.

Strict grounding rules:
- Quote a shloka, verse, scripture name or story ONLY if it appears in
  the excerpts above. Never add quotes from your own memory.
- Do not say things like "mere gurudev ne kaha" or "maine pichle satsang
  me bataya" unless the excerpts actually say that.
- If the excerpts don't cover the question well, say that briefly and
  give only the general principles that do appear in them.

Excerpts:
{context}

{history_section}

Current Question:
{query}
"""


def cosine_similarity(a, b):
    try:
        import numpy as np
        if isinstance(b, np.ndarray):
            dot = float(np.dot(a, b))
            norm_a = float(np.linalg.norm(a))
            norm_b = float(np.linalg.norm(b))
            return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
    except Exception:
        pass
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def with_retry(fn, label, max_retries=4, base_wait=5):
    """Call fn(); retry with exponential backoff on 5xx (e.g. 503 overloaded)
    and 429 (rate limit). Any other error is raised immediately."""
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except (errors.ServerError, errors.ClientError) as e:
            code = getattr(e, "code", None)
            retryable = isinstance(e, errors.ServerError) or code == 429
            if not retryable or attempt == max_retries:
                raise
            wait = base_wait * (2 ** (attempt - 1))
            print(f"\n  [{label}] {code} from Gemini — retrying in {wait}s "
                  f"(attempt {attempt}/{max_retries})...")
            time.sleep(wait)


def generate_answer(client, prompt):
    """Try CHAT_MODEL first (with retries), then each fallback model."""
    last_err = None
    for model in [CHAT_MODEL] + FALLBACK_MODELS:
        try:
            response = with_retry(
                lambda: client.models.generate_content(
                    model=model,
                    contents=[prompt],
                ),
                label=model,
            )
            return (response.text or "").strip()
        except errors.ServerError as e:
            last_err = e
            print(f"\n  [{model}] still unavailable — trying next model...")
    raise last_err


def load_qa_pairs(transcripts_file=TRANSCRIPTS_FILE):
    """Pair each QUESTION with the ANSWER(s) that follow it, until the
    next QUESTION, so each chunk is a self-contained Q + full answer."""
    transcripts_path = Path(transcripts_file)
    if not transcripts_path.exists():
        print(f"Warning: transcripts file not found at {transcripts_path}")
        return []

    pairs = []
    skipped = 0
    log_lines = []
    with open(transcripts_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            turns = record.get("turns", [])
            i = 0
            while i < len(turns):
                turn = turns[i]
                speaker = turn.get("speaker")
                if speaker is None:
                    skipped += 1
                    log_lines.append(
                        f"line {line_num}, turn {i} in "
                        f"{record.get('source_file', '?')} has no 'speaker' key: {turn}")
                    i += 1
                    continue
                if speaker == "QUESTION":
                    question_text = turn.get("text", "")
                    answer_parts = []
                    j = i + 1
                    while j < len(turns) and turns[j].get("speaker") == "ANSWER":
                        answer_parts.append(turns[j].get("text", ""))
                        j += 1
                    if answer_parts:
                        pairs.append({
                            "source_file": record.get("source_file", "?"),
                            "question": question_text,
                            "answer": " ".join(answer_parts),
                        })
                    i = j
                else:
                    i += 1
    if skipped:
        with open(SKIPPED_TURNS_LOG, "w", encoding="utf-8") as logf:
            logf.write("\n".join(log_lines))
        print(
            f"\n  Skipped {skipped} turn(s) missing 'speaker' — "
            f"details written to {SKIPPED_TURNS_LOG}, not printed here.\n")
    return pairs


def load_cache(jsonl_file=CACHE_JSONL_FILE, json_file=CACHE_JSON_FILE):
    """Load cached embeddings from embeddings.npz/metadata.json.gz, or fallback to jsonl."""
    # 1. Fast compressed cache load (<0.4s and ~200MB RAM)
    if CACHE_NPZ_FILE.exists() and CACHE_META_FILE.exists():
        try:
            import gzip, numpy as np
            with gzip.open(CACHE_META_FILE, "rb") as f:
                metadata = json.loads(f.read().decode("utf-8"))
            data = np.load(CACHE_NPZ_FILE)
            vectors = data["vectors"]
            cached = []
            for i, item in enumerate(metadata):
                cached.append({
                    "source_file": item.get("source_file", ""),
                    "question": item.get("question", ""),
                    "answer": item.get("answer", ""),
                    "embedding": vectors[i],
                })
            print(f"Loaded {len(cached)} cached pairs from compressed cache in <0.5s.")
            return cached
        except Exception as e:
            print(f"Warning: Failed loading compressed cache ({e}), falling back to raw files.")

    cached = []
    jsonl_path = Path(jsonl_file)
    json_path = Path(json_file)

    if jsonl_path.exists():
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        cached.append(json.loads(line))
            if cached:
                print(
                    f"Loaded {len(cached)} cached pairs from {jsonl_path.name}.")
                return cached
        except Exception as e:
            print(f"Warning: Failed reading {jsonl_path}: {e}")
            cached = []

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            print(f"Loaded {len(cached)} cached pairs from {json_path.name}.")
            return cached
        except Exception as e:
            print(f"Warning: Failed reading {json_path}: {e}")

    return []


class DailyQuotaExhausted(Exception):
    """Raised when Gemini says the per-day free-tier quota is used up."""


def embed_one_text(client, text, max_retries=5):
    """Embed ONE text and return its vector.

    gemini-embedding-2 merges a list of texts into a single vector, so
    every text must be sent in its own request (one request = one pair).
    Raises if the reply does not contain exactly one embedding, so a bad
    vector can never be saved to the cache."""
    for attempt in range(1, max_retries + 1):
        try:
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
            )
            if len(result.embeddings) != 1:
                raise RuntimeError(
                    f"expected 1 embedding, got {len(result.embeddings)}")
            return result.embeddings[0].values
        except errors.ClientError as e:
            msg = str(e)
            if getattr(e, "code", None) == 429:
                if "PerDay" in msg:
                    raise DailyQuotaExhausted()
                if attempt < max_retries:
                    wait = 15 * attempt
                    print(
                        f"\n  [rate limit] backing off {wait}s (attempt {attempt}/{max_retries})...")
                    time.sleep(wait)
                    continue
            raise
        except Exception as e:
            if attempt < max_retries:
                wait = 15 * attempt
                print(
                    f"\n  [network error] {type(e).__name__}: {e} — backing off {wait}s...")
                time.sleep(wait)
            else:
                raise


def load_or_build_cache(client, pairs=None, embed_missing=False):
    """Load cached embeddings. If embed_missing=True and new pairs exist, embed them."""
    cached = load_cache()
    cached_keys = {(c["source_file"], c["question"]) for c in cached}

    if not pairs or not embed_missing:
        return cached

    new_pairs = [
        p for p in pairs
        if (p["source_file"], p["question"]) not in cached_keys
    ]

    if not new_pairs:
        return cached

    print(
        f"Embedding {len(new_pairs)} new Q&A pairs (one request per pair)...")

    done = 0
    try:
        # Each vector is written to the cache file as soon as it is ready,
        # so stopping (or a quota stop) never loses finished work.
        with open(CACHE_JSONL_FILE, "a", encoding="utf-8") as f:
            for pair in new_pairs:
                text = f"{pair['question']} {pair['answer']}"
                vector = embed_one_text(client, text)
                item = {**pair, "embedding": vector}
                cached.append(item)
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()
                done += 1
                if done % 25 == 0 or done == len(new_pairs):
                    print(
                        f"\r  Embedding progress: {done}/{len(new_pairs)}", end="", flush=True)
    except DailyQuotaExhausted:
        print(f"\n  Daily free-tier quota exhausted after {done} pairs. "
              f"Progress is saved — run again later to continue.\n")
        return cached

    print("\nEmbeddings updated.\n")
    return cached


def rewrite_query(client, query: str, history: list = None) -> str:
    """Stage 1: Resolve the user's question using conversation context into a standalone retrieval query."""
    clean_query = (query or "").strip()
    if not clean_query:
        return ""

    if not history:
        return clean_query

    # Take recent history messages up to limit
    trimmed_history = history[-MAX_HISTORY_MESSAGES:]
    formatted_lines = []
    for msg in trimmed_history:
        role = msg.get("role", "user").capitalize()
        content = (msg.get("content") or "").strip()
        if content:
            formatted_lines.append(f"{role}: {content}")

    if not formatted_lines:
        return clean_query

    formatted_history = "\n".join(formatted_lines)
    prompt = QUERY_REWRITE_PROMPT.format(
        history=formatted_history, query=clean_query)

    try:
        response = with_retry(
            lambda: client.models.generate_content(
                model=REWRITE_MODEL,
                contents=[prompt],
            ),
            label="query_rewrite",
            max_retries=2,
            base_wait=2,
        )
        rewritten = (response.text or "").strip()
        # Clean up any potential quotation marks around the output
        if rewritten.startswith('"') and rewritten.endswith('"'):
            rewritten = rewritten[1:-1].strip()
        if rewritten:
            return rewritten
    except Exception as e:
        print(
            f"[rewrite_query warning] Failed to rewrite query ({type(e).__name__}: {e}). Using original query.")

    return clean_query


def retrieve_top_k(client, query: str, cached_pairs: list, k: int = TOP_K):
    """Stage 2: Embed standalone retrieval query and get top-k cosine similarity matches."""
    query_embedding = with_retry(
        lambda: client.models.embed_content(
            model=EMBED_MODEL,
            contents=query,
        ),
        label="embed query",
    ).embeddings[0].values

    scored = []
    for pair in cached_pairs:
        score = cosine_similarity(query_embedding, pair["embedding"])
        scored.append((score, pair))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


def answer_conversational(client, query: str, history: list = None, cached_pairs: list = None, k: int = TOP_K) -> dict:
    """Full conversational RAG pipeline:
    1. Resolve question into standalone query using conversation history.
    2. Retrieve top-k relevant excerpts from Q&A dataset.
    3. Generate final Hinglish answer using context + conversation history + original query.
    """
    clean_query = (query or "").strip()
    if not clean_query:
        raise ValueError("Query cannot be empty.")

    # Step 1: Query rewriting
    standalone_query = rewrite_query(client, clean_query, history)

    # Step 2: Retrieval using standalone query
    matches = retrieve_top_k(client, standalone_query, cached_pairs or [], k=k)

    context_blocks = []
    matched_episodes = []
    for score, pair in matches:
        context_blocks.append(f"Q: {pair['question']}\nA: {pair['answer']}")
        matched_episodes.append({
            "source_file": pair.get("source_file", "unknown"),
            "score": round(score, 4),
        })

    # Step 3: Format conversation history for final answer generation
    history_section = ""
    if history:
        trimmed_history = history[-MAX_HISTORY_MESSAGES:]
        lines = []
        for msg in trimmed_history:
            role = msg.get("role", "user").capitalize()
            content = (msg.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        if lines:
            history_section = "Recent Conversation History:\n" + \
                "\n".join(lines)

    prompt = CONVERSATIONAL_SYSTEM_PROMPT.format(
        context="\n\n".join(context_blocks),
        history_section=history_section,
        query=clean_query,
    )

    answer = generate_answer(client, prompt)

    return {
        "answer": answer,
        "matched_episodes": matched_episodes,
        "standalone_query": standalone_query,
    }
