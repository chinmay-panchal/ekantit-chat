"""
FastAPI backend for EkantitChat spiritual Q&A RAG pipeline.

Supports:
- True multi-turn conversation context
- Stage 1: History-aware standalone query resolution
- Stage 2: Semantic retrieval against Q&A embeddings cache
- Stage 3: Grounded Hinglish answer generation in the teacher's voice
- Matched episodes with similarity scores
- CORS for local and LAN device testing

Run:
    uvicorn server:app --host 0.0.0.0 --port 8000
"""
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google import genai
from pydantic import BaseModel, Field

from rag import (
    MAX_HISTORY_MESSAGES,
    GeminiClientPool,
    answer_conversational,
    load_cache,
    load_or_build_cache,
)

state = {}


def load_all_api_keys() -> list[str]:
    keys = []
    # 1. Comma separated in GEMINI_API_KEYS
    env_keys = os.environ.get("GEMINI_API_KEYS", "")
    if env_keys:
        for k in env_keys.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
    # 2. Numbered GEMINI_API_KEY_1 .. GEMINI_API_KEY_10
    for i in range(1, 11):
        k = (os.environ.get(f"GEMINI_API_KEY_{i}") or "").strip()
        if k and k not in keys:
            keys.append(k)
    # 3. Main GEMINI_API_KEY
    main_k = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if main_k and main_k not in keys:
        keys.append(main_k)
    return keys


@asynccontextmanager
async def lifespan(app: FastAPI):
    keys = load_all_api_keys()
    if not keys:
        raise RuntimeError("Set GEMINI_API_KEY or GEMINI_API_KEYS environment variable first.")

    pool = GeminiClientPool(keys)
    state["client"] = pool

    # Load pre-built embeddings cache (append-only embeddings_cache.jsonl)
    cached_pairs = load_cache()
    if not cached_pairs:
        # Fallback if cache file is empty/missing
        cached_pairs = load_or_build_cache(pool, embed_missing=False)

    print(f"--- RAG ready with {len(cached_pairs)} Q&A pairs across {len(keys)} API keys, server accepting requests ---")
    state["cached_pairs"] = cached_pairs
    yield
    state.clear()


app = FastAPI(
    title="EkantitChat API",
    description="Conversational Satsang RAG API",
    lifespan=lifespan,
)

# Allow Flutter web (localhost:random) and physical devices on local network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message text content")


class MatchedEpisode(BaseModel):
    source_file: str
    score: float


class ChatRequest(BaseModel):
    query: str
    history: List[ChatMessage] = []


class ChatResponse(BaseModel):
    success: bool = True
    answer: str
    matched_episodes: List[MatchedEpisode]
    standalone_query: Optional[str] = None
    is_follow_up: Optional[bool] = None


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


@app.get("/health")
def health_check():
    client = state.get("client")
    key_count = len(client.keys) if isinstance(client, GeminiClientPool) else 1
    return {
        "status": "healthy",
        "cached_pairs": len(state.get("cached_pairs", [])),
        "api_keys_loaded": key_count,
        "max_history_messages": MAX_HISTORY_MESSAGES,
    }


# Plain def (not async): Gemini calls are blocking, so FastAPI runs
# this in a worker thread pool instead of freezing the event loop.
@app.post("/chat")
def chat(req: ChatRequest):
    query = req.query.strip()
    if not query:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error_type": "invalid_request",
                "user_message": "Kripya apna sawaal likhein.",
                "detail": "Query cannot be empty.",
                "status_code": 400,
            },
        )

    client = state.get("client")
    cached_pairs = state.get("cached_pairs")
    if client is None or cached_pairs is None:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error_type": "service_unavailable",
                "user_message": "Server abhi restart ho raha hai. Kripya kuch second baad prayas karein.",
                "detail": "Server RAG state not initialized.",
                "status_code": 503,
            },
        )

    try:
        raw_history = [m.model_dump() for m in req.history]
        result = answer_conversational(
            client=client,
            query=query,
            history=raw_history,
            cached_pairs=cached_pairs,
        )
    except Exception as e:
        err_msg = str(e)
        print(f"[chat error] {type(e).__name__}: {err_msg}")

        status_code = 500
        error_type = "internal_error"
        user_message = "Kuch asuvidha hui. Kripya thodi der baad punah prayas karein."

        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
            status_code = 429
            error_type = "quota_exhausted"
            user_message = "Server par anurodh ki seema samapt ho gayi hai. Kripya kuch samay baad punah prayas karein."
        elif "timeout" in err_msg.lower():
            status_code = 504
            error_type = "timeout"
            user_message = "Jawab aane me samay lag raha hai. Kripya punah prayas karein."

        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error_type": error_type,
                "user_message": user_message,
                "detail": err_msg,
                "status_code": status_code,
            },
        )

    answer = (result.get("answer") or "").strip()
    if not answer:
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error_type": "empty_answer",
                "user_message": "Koi uttar prapt nahi hua. Kripya punah prayas karein.",
                "detail": "Gemini returned an empty answer.",
                "status_code": 502,
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "answer": answer,
            "matched_episodes": result.get("matched_episodes", []),
            "standalone_query": result.get("standalone_query"),
            "is_follow_up": result.get("is_follow_up"),
        },
    )


@app.post("/ask")
def ask(req: AskRequest):
    """Backward-compatible endpoint for single-turn queries."""
    question = req.question.strip()
    if not question:
        return JSONResponse(
            status_code=400,
            content={"error": "Question is empty."},
        )

    chat_req = ChatRequest(query=question, history=[])
    chat_resp = chat(chat_req)
    return chat_resp

