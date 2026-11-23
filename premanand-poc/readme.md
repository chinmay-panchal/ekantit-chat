Premanand Ji Diarization POC — One Day Plan
Goal: feed a ~1 minute clip (1 question + 1 answer), get back correctly labeled QUESTION / ANSWER text, using free local tools only.
Step 0 — Get two audio clips first (5 min)
reference.wav — a clean 20-30 sec clip of ONLY Premanand Ji talking, no overlapping voices, minimal noise. Any episode works.
test_clip.wav — your 1-minute test clip with one question + one answer.

Convert anything to wav with ffmpeg if needed:

ffmpeg -i input.mp4 -ar 16000 -ac 1 output.wav
Step 1 — Install dependencies (15-20 min)
brew install ffmpeg

mkdir premanand-poc && cd premanand-poc

python3 -m venv venv

source venv/bin/activate

pip install pyannote.audio faster-whisper numpy torch torchaudio
Step 2 — Get a Hugging Face token (10 min)
Sign up free at https://huggingface.co
Accept the user agreement on these two model pages (just visit and click accept):
https://huggingface.co/pyannote/speaker-diarization-3.1
https://huggingface.co/pyannote/segmentation-3.0
Generate a token (read access is enough): https://huggingface.co/settings/tokens
Paste that token into the HF_TOKEN variable at the top of BOTH enroll.py and process.py
Step 3 — Run enrollment (once, ~1-2 min)
python enroll.py reference.wav

This saves premanand_reference.npy — your permanent voice fingerprint. You never need to run this again unless you want a better reference clip.
Step 4 — Run the test clip (~2-5 min, first run downloads models)
python process.py test_clip.wav

You'll see similarity scores printed per detected speaker, then the final labeled output:

[QUESTION (Devotee)] <text>

[ANSWER (Premanand Ji)] <text>
Step 5 — Tune if needed
If a devotee gets mislabeled as him or vice versa, adjust SIMILARITY_THRESHOLD in process.py (starts at 0.75) — lower it if his real turns are getting rejected, raise it if a devotee is getting accepted as him.

Once this works cleanly on one clip, the exact same process.py is what you'd loop over all 1,700+ videos later — nothing changes, just batch it.

