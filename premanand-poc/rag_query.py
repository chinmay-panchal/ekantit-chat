"""
Interactive CLI for Satsang RAG pipeline.
Uses the shared RAG functions from rag.py.
"""
import os
from google import genai
from dotenv import load_dotenv

from rag import (
    BASE_DIR,
    CHAT_MODEL,
    EMBED_MODEL,
    FALLBACK_MODELS,
    SYSTEM_PROMPT,
    TRANSCRIPTS_FILE,
    answer_conversational,
    cosine_similarity,
    generate_answer,
    load_cache,
    load_or_build_cache,
    load_qa_pairs,
    retrieve_top_k,
    rewrite_query,
    with_retry,
)

load_dotenv(BASE_DIR / ".env")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def main():
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set. Add it to .env file.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)

    pairs = load_qa_pairs()
    print(f"Loaded {len(pairs)} Q&A pairs from transcripts.jsonl.")
    cached_pairs = load_or_build_cache(client, pairs, embed_missing=True)

    print(f"Loaded {len(cached_pairs)} cached Q&A embeddings.")
    print("--- Satsang Conversational RAG Ready ---")
    print("Type your question (or 'new' to start a new chat, 'quit' to exit)\n")

    history = []

    while True:
        try:
            query = input("Aapka sawaal: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAlvida!")
            break

        if query.lower() in ("quit", "exit", "q"):
            print("Radhe Radhe!")
            break

        if query.lower() == "new":
            history = []
            print("--- Started new conversation session ---\n")
            continue

        if not query:
            continue

        try:
            result = answer_conversational(
                client=client,
                query=query,
                history=history,
                cached_pairs=cached_pairs,
            )
        except Exception as e:
            print(f"\n  [error] Failed to process query: {e}\n")
            continue

        print("\n" + "-" * 60)
        is_follow_up = result.get("is_follow_up")
        if is_follow_up is not None:
            mode_label = "Follow-up (Context memory used)" if is_follow_up else "New Topic (Clean context, memory isolated)"
            print(f"Topic Mode: {mode_label}")
        if result.get("standalone_query") != query:
            print(f"Standalone search query: {result.get('standalone_query')}")
        print("Matched episodes:")
        for ep in result.get("matched_episodes", []):
            short_name = ep["source_file"].split("_")[0]
            print(f"  {short_name}  (match: {ep['score']:.0%})")

        print("-" * 60)
        print("ANSWER:")
        print("-" * 60)
        print(result["answer"])
        print("=" * 60 + "\n")

        # Update conversational session history
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": result["answer"]})


if __name__ == "__main__":
    main()
