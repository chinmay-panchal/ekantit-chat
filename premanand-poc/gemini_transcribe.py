"""
Content-based transcription + labeling using Gemini's native audio
understanding — no separate ASR pipeline, no diarization, no voice
fingerprint. Gemini listens to the audio directly and returns a
QUESTION (devotee) / ANSWER (Premanand Ji) labeled transcript in one call.

Usage:
    python gemini_transcribe.py test_clip_short.wav
"""
import sys
import json
import time
from google import genai

import os
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

MODEL = "gemini-3.1-flash-lite"

PROMPT = """You are transcribing a Hindi satsang Q&A recording.
One speaker is a devotee asking a question. The other is a spiritual
teacher (Premanand Ji Maharaj) giving a teaching/answer.

Listen to the full audio and transcribe it in Hindi (Devanagari script).
Split the transcript into an alternating sequence of QUESTION and ANSWER
turns based on who is actually speaking (use the audio itself — tone,
voice change, pauses — not just sentence content).

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:
{
  "turns": [
    {"speaker": "QUESTION", "text": "..."},
    {"speaker": "ANSWER", "text": "..."}
  ]
}
"""


def main():
    if len(sys.argv) != 2:
        print("Usage: python gemini_transcribe.py <audio_clip.wav>")
        sys.exit(1)

    audio_path = sys.argv[1]
    client = genai.Client(api_key=GEMINI_API_KEY)

    print(f"Uploading {audio_path} to Gemini File API...")
    uploaded_file = client.files.upload(file=audio_path)

    # Wait for the file to finish processing (Gemini processes audio async)
    while uploaded_file.state.name == "PROCESSING":
        print("  still processing...")
        time.sleep(2)
        uploaded_file = client.files.get(name=uploaded_file.name)

    if uploaded_file.state.name == "FAILED":
        print("File processing failed.")
        sys.exit(1)

    print("Asking Gemini to transcribe + label in one pass...")
    response = client.models.generate_content(
        model=MODEL,
        contents=[PROMPT, uploaded_file],
    )

    raw_reply = response.text.strip()

    # Strip markdown code fences if present
    if raw_reply.startswith("```"):
        raw_reply = raw_reply.split("```")[1]
        if raw_reply.startswith("json"):
            raw_reply = raw_reply[4:]
        raw_reply = raw_reply.strip()

    try:
        parsed = json.loads(raw_reply)
    except json.JSONDecodeError:
        print("\nCould not parse Gemini output as JSON. Raw reply was:\n")
        print(raw_reply)
        sys.exit(1)

    print("\n--- FINAL OUTPUT (Gemini, audio-native) ---\n")
    for turn in parsed.get("turns", []):
        label = "ANSWER (Premanand Ji)" if turn["speaker"] == "ANSWER" else "QUESTION (Devotee)"
        print(f"[{label}] {turn['text'].strip()}")


if __name__ == "__main__":
    main()
