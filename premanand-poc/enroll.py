"""
Run ONCE: creates a saved voice fingerprint (embedding) for Premanand Ji
from a clean reference clip. Reuse the saved file for every future video.

Usage:
    python enroll.py reference.wav
"""
import sys
import numpy as np
from pyannote.audio import Model, Inference

import os
from dotenv import load_dotenv

load_dotenv()
HF_TOKEN = os.environ.get("HF_TOKEN", "")


def main():
    if len(sys.argv) != 2:
        print("Usage: python enroll.py <reference_clip.wav>")
        sys.exit(1)

    reference_path = sys.argv[1]

    print("Loading embedding model (first run downloads it, ~few hundred MB)...")
    model = Model.from_pretrained("pyannote/embedding", token=HF_TOKEN)
    inference = Inference(model, window="whole")

    print(f"Extracting voice fingerprint from {reference_path}...")
    embedding = inference(reference_path)

    np.save("premanand_reference.npy", embedding)
    print("Saved reference fingerprint to premanand_reference.npy")
    print("You will not need to run this script again for future videos.")


if __name__ == "__main__":
    main()
