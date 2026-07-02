#!/usr/bin/env python3
"""
apply_speaker_names.py — apply a SPEAKER_NN → real-name mapping to a diarized
WhisperX JSON, and (optionally) persist that cluster's embedding into the
voice library so future meetings auto-name without human input.

Two jobs in one:
  1. Rename speaker labels in the JSON (for immediate transcript output).
  2. If the JSON carries --speaker_embeddings output, save each named cluster's
     embedding to speaker-library/embeddings/{name}.npy (stacking if exists).
     This is the library BOOTSTRAP — do it once per known speaker.

Usage:
  apply_speaker_names.py --json teams.json --out teams-named.json \
      --map "SPEAKER_00=Alice,SPEAKER_01=Bob,SPEAKER_02=Carol" \
      [--library ~/transcribe-pipeline/speaker-library/embeddings] \
      [--save-embeddings]

Embedding key discovery: whisperx --speaker_embeddings writes embeddings under
a top-level key. We probe several likely shapes (dict {speaker: vec},
list-of-dicts, or per-segment) for robustness across whisperx point releases.
"""

import argparse
import json
import sys
from pathlib import Path


def parse_map(s):
    out = {}
    for pair in s.split(","):
        pair = pair.strip()
        if not pair:
            continue
        k, _, v = pair.partition("=")
        out[k.strip()] = v.strip()
    return out


def find_embeddings(data):
    """Return {speaker_label: vector} if discoverable, else {}."""
    # Shape A: top-level dict
    for key in ("speaker_embeddings", "embeddings", "speakers"):
        v = data.get(key)
        if isinstance(v, dict) and v and all(isinstance(x, (list, dict)) for x in v.values()):
            out = {}
            for spk, val in v.items():
                vec = val.get("embedding") if isinstance(val, dict) else val
                if vec is not None:
                    out[spk] = vec
            if out:
                return out
        # Shape B: list of {speaker, embedding}
        if isinstance(v, list) and v and isinstance(v[0], dict) and "embedding" in v[0]:
            return {d.get("speaker", d.get("label")): d["embedding"] for d in v}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--map", required=True, help='e.g. "SPEAKER_00=Alice,SPEAKER_01=Bob"')
    ap.add_argument("--library", default="~/transcribe-pipeline/speaker-library/embeddings")
    ap.add_argument("--save-embeddings", action="store_true",
                    help="persist named clusters' embeddings into the voice library")
    args = ap.parse_args()

    mapping = parse_map(args.map)
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))

    # 1. Rename labels in segments
    renamed = 0
    for seg in data.get("segments", []):
        sp = seg.get("speaker")
        if sp in mapping:
            seg["speaker"] = mapping[sp]
            renamed += 1
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"renamed {renamed} segments → {args.out}", file=sys.stderr)

    # 2. Save embeddings to library
    if args.save_embeddings:
        embs = find_embeddings(data)
        if not embs:
            print("WARN: --save-embeddings set but no embeddings found in JSON "
                  "(was whisperx run with --speaker_embeddings?)", file=sys.stderr)
            return
        import numpy as np
        lib = Path(args.library).expanduser()
        lib.mkdir(parents=True, exist_ok=True)
        saved = 0
        for spk, name in mapping.items():
            vec = embs.get(spk)
            if vec is None:
                print(f"  no embedding for {spk} ({name}) — skip", file=sys.stderr)
                continue
            vec = np.asarray(vec, dtype=float).reshape(1, -1)
            target = lib / f"{name.lower()}.npy"
            if target.exists():
                ex = np.load(target)
                if ex.ndim == 1:
                    ex = ex.reshape(1, -1)
                vec = np.vstack([ex, vec])
            np.save(target, vec)
            saved += 1
            print(f"  saved {name.lower()}.npy  ({vec.shape[0]} sample(s), dim {vec.shape[1]})",
                  file=sys.stderr)
        print(f"library updated: {saved} speakers", file=sys.stderr)


if __name__ == "__main__":
    main()
