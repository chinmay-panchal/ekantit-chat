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
from google.genai import errors, types

BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")

# Models
EMBED_MODEL = "gemini-embedding-2"
CHAT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
REWRITE_MODEL = "gemini-3.5-flash-lite"
REWRITE_FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]

# Files
TRANSCRIPTS_FILE = BASE_DIR / "transcripts.jsonl"
CACHE_JSONL_FILE = BASE_DIR / "embeddings_cache.jsonl"
CACHE_JSON_FILE = BASE_DIR / "embeddings_cache.json"
CACHE_NPZ_FILE = BASE_DIR / "embeddings.npz"
CACHE_META_FILE = BASE_DIR / "metadata.json.gz"
SKIPPED_TURNS_LOG = BASE_DIR / "skipped_turns.log"

# Configuration
TOP_K = 3
MAX_HISTORY_MESSAGES = 20

QUERY_ANALYSIS_PROMPT = """You are an expert conversation analyzer for a spiritual Q&A system based on teachings of Premanand Ji Maharaj.
Analyze the user's latest question in relation to the conversation history.

Determine whether the latest question is:
1. A FOLLOW-UP (is_follow_up = true): The user is continuing, clarifying, or asking about the previous topic, using pronouns, elisions, or references (e.g. 'which is best?', 'how to do it?', 'aur bataiye', 'iska kya fayda hai?', 'why?').
2. A NEW TOPIC / INDEPENDENT QUESTION (is_follow_up = false): The user is asking a completely new, distinct question or request that does NOT depend on the previous conversation (e.g. asking for a shlok after discussing naam-jap techniques, asking about anger, guru, karma, family, or a new spiritual concept), even if it is within the same chat session.

Important Rules:
- If the question is an independent new topic, DO NOT inject or drag topics from the previous conversation into it. Keep the standalone question true to the user's new question.
- If the question is a follow-up, rewrite it into a single, complete standalone question that resolves all pronouns/references using explicit terms from the conversation.
- Output a JSON object with EXACTLY these two keys:
  - "is_follow_up": boolean (true if it depends on previous messages, false if it is a new independent topic)
  - "standalone_query": string

Conversation History:
{history}

Latest Question: {query}
"""
QUERY_REWRITE_PROMPT = QUERY_ANALYSIS_PROMPT

SYSTEM_PROMPT = """You are helping someone by drawing on the teachings of
Premanand Ji Maharaj, based on the Q&A excerpts provided below from
his actual satsang sessions.

Read the person's situation/question, then look at the excerpts — even
if none match their exact situation, identify the underlying spiritual
principles Premanand Ji teaches (e.g. naam-jap, surrender, seeing
God's grace, non-attachment) and apply them to the person's specific
situation, in his tone and style (warm, direct, often using stories,
verses, and repeated emphasis on naam-jap).

Language and Script Matching:
- Match the exact language and script of the user's question:
  1. If the user asks in English: Respond in natural, warm, spiritually rich English (you can retain familiar devotional terms in quotes or brackets like 'Radha-Radha', 'naam-jap', 'bhakti').
  2. If the user asks in Hindi (Devanagari script, e.g. "राधे-राधे, मैं क्या करूं?"): Respond in respectful, pure Hindi using Devanagari script (e.g. "राधे-राधे, देखो बेटा...").
  3. If the user asks in Hinglish (Hindi written in Roman/Latin script, e.g. "Radhe-Radhe, mai kya karu?"): Respond in Hinglish (e.g. "Radhe-Radhe, dekho beta...").
- Keep the tone, warmth and loving fatherly style of Maharaj Ji across all languages. Do not invent biographical facts about Premanand Ji himself.

Excerpts:
{context}

Person's situation/question:
{query}
"""

CONVERSATIONAL_SYSTEM_PROMPT = """You are helping someone by drawing on the teachings of
Premanand Ji Maharaj, based on the Q&A excerpts provided below from
his actual satsang sessions.

Read the person's situation/question and recent conversation history, then look at the excerpts — even
if none match their exact situation, identify the underlying spiritual
principles Premanand Ji teaches (e.g. naam-jap, surrender, seeing
God's grace, non-attachment) and apply them to the person's specific
situation, in his tone and style (warm, direct, often using stories,
verses, and repeated emphasis on naam-jap).

Language and Script Matching:
- Match the exact language and script of the user's question:
  1. If the user asks in English: Respond in natural, warm, spiritually rich English (you can retain familiar devotional terms in quotes or brackets like 'Radha-Radha', 'naam-jap', 'bhakti').
  2. If the user asks in Hindi (Devanagari script, e.g. "राधे-राधे, मैं क्या करूं?"): Respond in respectful, pure Hindi using Devanagari script (e.g. "राधे-राधे, देखो बेटा...").
  3. If the user asks in Hinglish (Hindi written in Roman/Latin script, e.g. "Radhe-Radhe, mai kya karu?"): Respond in Hinglish (e.g. "Radhe-Radhe, dekho beta...").
- Keep the tone, warmth and loving fatherly style of Maharaj Ji across all languages. Do not invent biographical facts about Premanand Ji himself.

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


class GeminiClientPool:
    """Round-robin / failover pool of Gemini clients across multiple API keys."""
    def __init__(self, keys: list[str]):
        self.keys = [k.strip() for k in keys if k and k.strip()]
        if not self.keys:
            raise RuntimeError("No Gemini API keys provided to GeminiClientPool.")
        self.clients = [genai.Client(api_key=k) for k in self.keys]
        self.current_idx = 0
        for c in self.clients:
            c._pool = self

    @property
    def current(self) -> genai.Client:
        return self.clients[self.current_idx % len(self.clients)]

    def rotate(self, reason: str = "") -> genai.Client:
        if len(self.clients) > 1:
            self.current_idx = (self.current_idx + 1) % len(self.clients)
            print(f"[ClientPool] {reason} -> Rotated to API key #{self.current_idx + 1}/{len(self.clients)}")
            return self.current
        return self.clients[0]

    def __getattr__(self, name):
        return getattr(self.current, name)


def with_retry(fn, label, max_retries=4, base_wait=2, pool=None):
    """Call fn(); retry with exponential backoff on 5xx and 429.
    If a client pool is provided and 429 occurs, rotate key immediately!"""
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except (errors.ServerError, errors.ClientError) as e:
            code = getattr(e, "code", None)
            err_str = str(e)
            is_quota = code == 429 or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()
            if is_quota and pool and len(pool.clients) > 1 and attempt < max_retries:
                pool.rotate("429 Resource Exhausted")
                continue
            retryable = isinstance(e, errors.ServerError) or code == 429
            if not retryable or attempt == max_retries:
                raise
            wait = base_wait * (2 ** (attempt - 1))
            print(f"\n  [{label}] {code} from Gemini — retrying in {wait}s "
                  f"(attempt {attempt}/{max_retries})...")
            time.sleep(wait)


def generate_answer(client, prompt):
    """Try CHAT_MODEL first (with retries), then each fallback model."""
    pool = getattr(client, "_pool", client if isinstance(client, GeminiClientPool) else None)
    last_err = None
    for model in [CHAT_MODEL] + FALLBACK_MODELS:
        try:
            response = with_retry(
                lambda: client.models.generate_content(
                    model=model,
                    contents=[prompt],
                ),
                label=model,
                pool=pool,
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


def analyze_and_rewrite_query(client, query: str, history: list = None) -> tuple[str, bool]:
    """Stage 1: Analyze user question against conversation context.
    Returns:
        (standalone_query, is_follow_up)
        - If follow-up: resolves references/pronouns into an explicit standalone query, is_follow_up=True
        - If new topic: preserves question as-is without contaminating with prior topics, is_follow_up=False
    """
    clean_query = (query or "").strip()
    if not clean_query:
        return "", False

    if not history:
        return clean_query, False

    # Take recent history messages up to limit
    trimmed_history = history[-MAX_HISTORY_MESSAGES:]
    formatted_lines = []
    for msg in trimmed_history:
        role = msg.get("role", "user").capitalize()
        content = (msg.get("content") or "").strip()
        if content:
            formatted_lines.append(f"{role}: {content}")

    if not formatted_lines:
        return clean_query, False

    formatted_history = "\n".join(formatted_lines)
    prompt = QUERY_ANALYSIS_PROMPT.format(
        history=formatted_history, query=clean_query
    )

    pool = getattr(client, "_pool", client if isinstance(client, GeminiClientPool) else None)
    models_to_try = [REWRITE_MODEL] + REWRITE_FALLBACK_MODELS
    for model in models_to_try:
        try:
            cfg = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            )
            response = with_retry(
                lambda m=model: client.models.generate_content(
                    model=m,
                    contents=[prompt],
                    config=cfg,
                ),
                label=f"query_analysis_{model}",
                max_retries=2,
                base_wait=2,
                pool=pool,
            )
            raw_text = (response.text or "").strip()
            data = json.loads(raw_text)
            is_follow_up = bool(data.get("is_follow_up", False))
            standalone_query = (data.get("standalone_query") or "").strip()
            if not standalone_query:
                standalone_query = clean_query
            return standalone_query, is_follow_up
        except Exception as e:
            continue

    return clean_query, False


def rewrite_query(client, query: str, history: list = None) -> str:
    """Stage 1 backwards compatibility: returns standalone query string."""
    standalone_query, _ = analyze_and_rewrite_query(client, query, history)
    return standalone_query


def retrieve_top_k(client, query: str, cached_pairs: list, k: int = TOP_K):
    """Stage 2: Embed standalone retrieval query and get top-k cosine similarity matches."""
    pool = getattr(client, "_pool", client if isinstance(client, GeminiClientPool) else None)
    query_embedding = with_retry(
        lambda: client.models.embed_content(
            model=EMBED_MODEL,
            contents=query,
        ),
        label="embed query",
        pool=pool,
    ).embeddings[0].values

    # Ultra-fast vectorized similarity if numpy vectors are present
    try:
        import numpy as np
        if cached_pairs and isinstance(cached_pairs[0].get("embedding"), np.ndarray):
            q_vec = np.array(query_embedding, dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)
            if q_norm > 0:
                q_vec /= q_norm
            vectors = np.array([p["embedding"] for p in cached_pairs], dtype=np.float32)
            v_norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors_norm = vectors / np.maximum(v_norms, 1e-9)
            scores = np.dot(vectors_norm, q_vec)
            top_indices = np.argsort(scores)[::-1][:k]
            return [(float(scores[idx]), cached_pairs[idx]) for idx in top_indices]
    except Exception as e:
        pass

    scored = []
    for pair in cached_pairs:
        score = cosine_similarity(query_embedding, pair["embedding"])
        scored.append((score, pair))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


def answer_conversational(client, query: str, history: list = None, cached_pairs: list = None, k: int = TOP_K) -> dict:
    """Full conversational RAG pipeline with smart topic-shift awareness:
    1. Resolve question and detect whether it is a follow-up or brand new topic.
    2. Retrieve top-k relevant excerpts from Q&A dataset.
    3. If follow-up: feed recent conversation history to maintain continuity.
       If new topic: do NOT pass prior conversation history, keeping context clean and unbiased.
    """
    clean_query = (query or "").strip()
    if not clean_query:
        raise ValueError("Query cannot be empty.")

    # Step 1: Query analysis & rewriting
    has_prior_history = any(
        (m.get("content") or "").strip()
        for m in (history or [])
        if (m.get("content") or "").strip() != clean_query
    )
    if has_prior_history:
        standalone_query, is_follow_up = analyze_and_rewrite_query(client, clean_query, history)
    else:
        standalone_query = clean_query
        is_follow_up = False

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

    # Step 3: Conditional history injection
    if is_follow_up and history:
        trimmed_history = history[-MAX_HISTORY_MESSAGES:]
        lines = []
        for msg in trimmed_history:
            role = msg.get("role", "user").capitalize()
            content = (msg.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        history_section = "Recent Conversation History:\n" + "\n".join(lines) if lines else ""
        prompt = CONVERSATIONAL_SYSTEM_PROMPT.format(
            context="\n\n".join(context_blocks),
            history_section=history_section,
            query=clean_query,
        )
    else:
        # Clean break / new topic: do NOT pollute prompt with unrelated past conversation
        prompt = SYSTEM_PROMPT.format(
            context="\n\n".join(context_blocks),
            query=clean_query,
        )

    answer = generate_answer(client, prompt)

    return {
        "answer": answer,
        "matched_episodes": matched_episodes,
        "standalone_query": standalone_query,
        "is_follow_up": is_follow_up,
    }
