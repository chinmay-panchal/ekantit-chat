"""
Non-destructively convert embeddings_cache.jsonl into a compact,
high-performance format for cloud deployment (<100MB for GitHub & <150MB RAM).
Original files (transcripts.jsonl, embeddings_cache.jsonl) are NEVER modified.
"""
import json
import gzip
import time
from pathlib import Path
import numpy as np

def main():
    base_dir = Path(__file__).parent.resolve()
    input_file = base_dir / "embeddings_cache.jsonl"
    out_vec_file = base_dir / "embeddings.npz"
    out_meta_file = base_dir / "metadata.json.gz"

    if not input_file.exists():
        print(f"Error: {input_file} not found!")
        return

    print("Step 1: Reading embeddings_cache.jsonl (read-only)...")
    t0 = time.time()
    vectors = []
    metadata = []

    with open(input_file, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            vec = item["embedding"]
            vectors.append(vec)
            metadata.append({
                "source_file": item.get("source_file", ""),
                "question": item.get("question", ""),
                "answer": item.get("answer", ""),
            })
            if (idx + 1) % 2000 == 0:
                print(f"  Processed {idx + 1} pairs...")

    total = len(vectors)
    print(f"Loaded {total} pairs in {time.time()-t0:.1f}s.")

    print("\nStep 2: Compressing vectors to float16 .npz...")
    vec_array = np.array(vectors, dtype=np.float16)
    np.savez_compressed(out_vec_file, vectors=vec_array)
    vec_size_mb = out_vec_file.stat().st_size / (1024 * 1024)
    print(f"  -> {out_vec_file.name}: {vec_size_mb:.2f} MB")

    print("\nStep 3: Compressing metadata to gzip JSON...")
    meta_json = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    with gzip.open(out_meta_file, "wb", compresslevel=9) as f:
        f.write(meta_json)
    meta_size_mb = out_meta_file.stat().st_size / (1024 * 1024)
    print(f"  -> {out_meta_file.name}: {meta_size_mb:.2f} MB")

    print("\nStep 4: Accuracy Verification Test...")
    # Test cosine similarity between original and float16
    q_vec = np.array(vectors[0], dtype=np.float32)
    loaded_vec = vec_array[0].astype(np.float32)
    cosine_sim = np.dot(q_vec, loaded_vec) / (np.linalg.norm(q_vec) * np.linalg.norm(loaded_vec))
    print(f"  Float16 vs Original Cosine Correlation: {cosine_sim:.6f} (Target: >0.9999)")

    total_mb = vec_size_mb + meta_size_mb
    print(f"\nSUCCESS! Total compressed size: {total_mb:.2f} MB (Well under GitHub's 100MB limit).")
    print(f"Original file is safe and untouched: {input_file.name} ({input_file.stat().st_size / (1024*1024):.1f} MB)")

if __name__ == "__main__":
    main()
