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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from pydantic import BaseModel, Field

from rag import (
    MAX_HISTORY_MESSAGES,
    answer_conversational,
    load_cache,
    load_or_build_cache,
)

state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY environment variable first.")

    client = genai.Client(api_key=api_key)
    state["client"] = client

    # Load pre-built embeddings cache (append-only embeddings_cache.jsonl)
    cached_pairs = load_cache()
    if not cached_pairs:
        # Fallback if cache file is empty/missing
        cached_pairs = load_or_build_cache(client, embed_missing=False)

    print(f"--- RAG ready with {len(cached_pairs)} Q&A pairs, server accepting requests ---")
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
    answer: str
    matched_episodes: List[MatchedEpisode]
    standalone_query: Optional[str] = None


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "cached_pairs": len(state.get("cached_pairs", [])),
        "max_history_messages": MAX_HISTORY_MESSAGES,
    }


# Plain def (not async): Gemini calls are blocking, so FastAPI runs
# this in a worker thread pool instead of freezing the event loop.
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    client = state.get("client")
    cached_pairs = state.get("cached_pairs")
    if client is None or cached_pairs is None:
        raise HTTPException(status_code=503, detail="Server RAG state not initialized.")

    try:
        raw_history = [m.model_dump() for m in req.history]
        result = answer_conversational(
            client=client,
            query=query,
            history=raw_history,
            cached_pairs=cached_pairs,
        )
    except Exception as e:
        print(f"[chat error] {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail=f"RAG processing failed: {e}")

    answer = (result.get("answer") or "").strip()
    if not answer:
        raise HTTPException(status_code=502, detail="Gemini returned an empty answer.")

    return ChatResponse(
        answer=answer,
        matched_episodes=[MatchedEpisode(**ep) for ep in result.get("matched_episodes", [])],
        standalone_query=result.get("standalone_query"),
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    """Backward-compatible endpoint for single-turn queries."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")

    chat_req = ChatRequest(query=question, history=[])
    chat_resp = chat(chat_req)
    return AskResponse(answer=chat_resp.answer)
