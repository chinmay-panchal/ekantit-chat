"""
Content-based (no voice-matching) speaker labeling experiment.

Transcribes audio with Groq Whisper, then asks an LLM to split the
transcript into QUESTION (devotee) / ANSWER (Premanand Ji) turns based
purely on the CONTENT of what was said — no diarization, no voice
fingerprint, no pyannote at all.

Usage:
    python text_diarize.py test_clip_short.wav
"""
import sys
import json
from groq import Groq

import os
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# NOTE: check Groq's current model list (https://console.groq.com/docs/models)
# before relying on this — model names/availability change over time.
LLM_MODEL = "openai/gpt-oss-120b"

LABELING_PROMPT = """You are labeling a transcript of a Hindi satsang Q&A session.
One speaker is a devotee asking a question. The other is a spiritual
teacher (Premanand Ji Maharaj) giving a teaching/answer.

Split the transcript below into an alternating sequence of QUESTION and
ANSWER turns, based ONLY on the content and tone of what is said (short
questions, honorifics like "जी", question words like क्या/कैसे/क्यों
typically indicate a devotee; longer teaching-style explanations,
references to भगवान/शास्त्र, and non-question guidance typically
indicate the teacher).

Return ONLY valid JSON, no other text, in this exact format:
{
  "turns": [
    {"speaker": "QUESTION", "text": "..."},
    {"speaker": "ANSWER", "text": "..."}
  ]
}

Transcript:
"""


def main():
    if len(sys.argv) != 2:
        print("Usage: python text_diarize.py <audio_clip.wav>")
        sys.exit(1)

    audio_path = sys.argv[1]
    groq_client = Groq(api_key=GROQ_API_KEY)

    # --- Step 1: Transcribe (no diarization, no speaker info at all) ---
    print("Transcribing with Groq (whisper-large-v3)...")
    with open(audio_path, "rb") as f:
        transcript = groq_client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3",
            language="hi",
            response_format="verbose_json",
        )

    full_text = transcript.text.strip()
    print("\n--- RAW TRANSCRIPT (no speaker info) ---\n")
    print(full_text)

    # --- Step 2: Ask an LLM to split it based on content alone ---
    print("\nAsking LLM to label turns based on content...")
    response = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "user", "content": LABELING_PROMPT + full_text}
        ],
        temperature=0,
    )

    raw_reply = response.choices[0].message.content.strip()

    # Strip markdown code fences if the model wrapped its JSON in them
    if raw_reply.startswith("```"):
        raw_reply = raw_reply.split("```")[1]
        if raw_reply.startswith("json"):
            raw_reply = raw_reply[4:]
        raw_reply = raw_reply.strip()

    try:
        parsed = json.loads(raw_reply)
    except json.JSONDecodeError:
        print("\nCould not parse LLM output as JSON. Raw reply was:\n")
        print(raw_reply)
        sys.exit(1)

    # --- Step 3: Print final labeled output ---
    print("\n--- FINAL OUTPUT (content-based, no voice matching) ---\n")
    for turn in parsed.get("turns", []):
        label = "ANSWER (Premanand Ji)" if turn["speaker"] == "ANSWER" else "QUESTION (Devotee)"
        print(f"[{label}] {turn['text'].strip()}")


if __name__ == "__main__":
    main()
