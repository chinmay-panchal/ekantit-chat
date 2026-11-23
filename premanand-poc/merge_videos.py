import subprocess
import sys
from pathlib import Path

# ---------- CONFIG ----------
DOWNLOADS = Path.home() / "Downloads"

VIDEOS = [
    DOWNLOADS / "part1_papervisor.mp4",
    DOWNLOADS / "part2_papervisor.mp4",
    DOWNLOADS / "part3_papervisor.mp4",
]
OUTPUT = DOWNLOADS / "papervisor_merged_final.mp4"

# Mute range in part1 only (seconds)
MUTE_START = 5
MUTE_END = 7

# Output settings (all parts get normalized to this)
WIDTH = 1280
HEIGHT = 720
FPS = 30
# ----------------------------


def build_command():
    cmd = ["ffmpeg", "-y"]
    for v in VIDEOS:
        cmd += ["-i", str(v)]

    filters = []
    for i in range(len(VIDEOS)):
        # Video: same size, aspect ratio preserved with black bars, same fps
        filters.append(
            f"[{i}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[v{i}]"
        )

        # Audio: same sample rate / channels
        audio_chain = f"[{i}:a]"
        if i == 0:
            # Silence only 5-7s of part1
            audio_chain += f"volume=enable='between(t,{MUTE_START},{MUTE_END})':volume=0,"
        audio_chain += "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
        audio_chain += f"[a{i}]"
        filters.append(audio_chain)

    inputs = "".join(f"[v{i}][a{i}]" for i in range(len(VIDEOS)))
    filters.append(f"{inputs}concat=n={len(VIDEOS)}:v=1:a=1[outv][outa]")

    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        str(OUTPUT),
    ]
    return cmd


def main():
    for v in VIDEOS:
        if not v.exists():
            print(f"File not found: {v}")
            sys.exit(1)

    print("Running ffmpeg...\n")
    result = subprocess.run(build_command())
    if result.returncode != 0:
        print("\nffmpeg failed.")
        sys.exit(1)
    print(f"\nDone! Saved as {OUTPUT}")


if __name__ == "__main__":
    main()
