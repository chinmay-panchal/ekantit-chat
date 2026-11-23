"""
Run for EVERY new clip: diarizes speakers, identifies which one is
Premanand Ji using the saved reference fingerprint, transcribes with
Whisper, and prints labeled QUESTION / ANSWER output.

Usage:
    python process.py test_clip.wav
"""
import sys
import numpy as np
from pyannote.audio import Pipeline, Model, Inference
from pyannote.core import Segment
# only needed if you keep the OLD local path below
from faster_whisper import WhisperModel

import os
from dotenv import load_dotenv

load_dotenv()
HF_TOKEN = os.environ.get("HF_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

SIMILARITY_THRESHOLD = 0.5  # tune after your first run
MIN_TURN_SECONDS = 1.5      # groups shorter than this get merged into a neighbor


def cosine_similarity(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main():
    if len(sys.argv) != 2:
        print("Usage: python process.py <audio_clip.wav>")
        sys.exit(1)

    audio_path = sys.argv[1]
    reference = np.load("premanand_reference.npy")

    # --- Diarization: who spoke when (generic labels) ---
    print("Loading diarization pipeline...")
    diarization_pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", token=HF_TOKEN
    )

    print("Running diarization...")

    diarization_output = diarization_pipeline(
        audio_path, min_speakers=2, max_speakers=2)
    diarization = diarization_output.speaker_diarization

    turns = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append(
            {"start": turn.start, "end": turn.end, "raw_speaker": speaker})

    # --- DIAGNOSTIC: show raw diarization turns before any labeling/smoothing ---
    print("\n--- RAW DIARIZATION TURNS (before labeling/smoothing) ---")
    for t in turns:
        print(f"  {t['start']:.1f}s - {t['end']:.1f}s : {t['raw_speaker']}")
    print()

    if not turns:
        print("No speech detected. Check your audio file.")
        sys.exit(1)

    # --- Identification: which generic label is actually him ---
    print("Loading embedding model for identification...")
    embed_model = Model.from_pretrained(
        "pyannote/embedding", token=HF_TOKEN)
    inference = Inference(embed_model, window="whole")

    speaker_ids = sorted(set(t["raw_speaker"] for t in turns))
    speaker_identity = {}
    for sid in speaker_ids:
        segs = [t for t in turns if t["raw_speaker"] == sid]
        longest = max(segs, key=lambda t: t["end"] - t["start"])
        seg_embedding = inference.crop(
            audio_path, Segment(longest["start"], longest["end"])
        )
        score = cosine_similarity(reference, seg_embedding)
        speaker_identity[sid] = "premanand_ji" if score >= SIMILARITY_THRESHOLD else "devotee"
        print(f"  {sid}: similarity={score:.3f} -> {speaker_identity[sid]}")

    for t in turns:
        t["speaker"] = speaker_identity[t["raw_speaker"]]

    # =========================================================================
    # --- Transcription: what was said, independent of who ---
    #
    # OLD (local, slow on CPU — this is what was causing the 76+ minute runs):
    # UNCOMMENT these 3 lines and COMMENT OUT the Groq block below to
    # revert back to the local path if you ever want to.
    # -------------------------------------------------------------------------
    # print("Transcribing with Whisper (first run downloads the model)...")
    # whisper_model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    # segments, _ = whisper_model.transcribe(
    #     audio_path, language="hi", vad_filter=True, word_timestamps=True)
    # =========================================================================

    # --- Transcription via Groq API (full large-v3, not turbo, for accuracy) ---
    print("Transcribing with Groq (whisper-large-v3)...")
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY)

    with open(audio_path, "rb") as f:
        transcript = groq_client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3",
            language="hi",
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    class _Word:
        def __init__(self, word, start, end):
            self.word = word
            self.start = start
            self.end = end

    class _Segment:
        def __init__(self, words):
            self.words = words

    segments = [_Segment([_Word(w["word"], w["start"], w["end"])
                         for w in transcript.words])]

    def find_speaker(mid_time):
        # Exact match first
        for t in turns:
            if t["start"] <= mid_time <= t["end"]:
                return t["speaker"]
        # No exact match (small gap between turns) — snap to nearest turn
        if turns:
            closest = min(turns, key=lambda t: min(
                abs(t["start"] - mid_time), abs(t["end"] - mid_time)))
            return closest["speaker"]
        return "unknown"

    print("\n--- FINAL OUTPUT ---\n")

    # Flatten all words across all segments, each tagged with its speaker
    word_speaker_pairs = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                mid = (w.start + w.end) / 2
                speaker = find_speaker(mid)
                word_speaker_pairs.append((w.word, speaker, w.start, w.end))
        else:
            mid = (seg.start + seg.end) / 2
            speaker = find_speaker(mid)
            word_speaker_pairs.append((seg.text, speaker, seg.start, seg.end))

    if not word_speaker_pairs:
        print("No words transcribed.")
        return

    # --- Group consecutive words with the same speaker ---
    def build_groups(pairs):
        groups = []
        for word, speaker, start, end in pairs:
            if groups and groups[-1]["speaker"] == speaker:
                groups[-1]["words"].append(word)
                groups[-1]["end"] = end
            else:
                groups.append({"speaker": speaker, "start": start,
                              "end": end, "words": [word]})
        return groups

    def merge_same_speaker_neighbors(groups):
        merged = []
        for g in groups:
            if merged and merged[-1]["speaker"] == g["speaker"]:
                merged[-1]["words"].extend(g["words"])
                merged[-1]["end"] = g["end"]
            else:
                merged.append(g)
        return merged

    groups = build_groups(word_speaker_pairs)

    # --- Smooth out short flicker groups by merging them into a longer neighbor ---
    changed = True
    while changed and len(groups) > 2:
        changed = False
        for i in range(1, len(groups) - 1):
            duration = groups[i]["end"] - groups[i]["start"]
            if duration < MIN_TURN_SECONDS:
                prev_duration = groups[i - 1]["end"] - groups[i - 1]["start"]
                next_duration = groups[i + 1]["end"] - groups[i + 1]["start"]
                groups[i]["speaker"] = (
                    groups[i - 1]["speaker"] if prev_duration >= next_duration else groups[i + 1]["speaker"]
                )
                changed = True
                break
        if changed:
            groups = merge_same_speaker_neighbors(groups)

    # --- Print final labeled transcript ---
    for g in groups:
        label = "ANSWER (Premanand Ji)" if g["speaker"] == "premanand_ji" else "QUESTION (Devotee)"
        print(
            f"[{label}] ({g['start']:.1f}s-{g['end']:.1f}s) {' '.join(g['words']).strip()}")


if __name__ == "__main__":
    main()
