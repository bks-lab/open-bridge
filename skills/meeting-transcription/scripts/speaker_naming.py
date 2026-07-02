#!/usr/bin/env python3
"""
speaker_naming.py — replace WhisperX/pyannote SPEAKER_NN labels with real
names by matching each cluster's voice-embedding against a known-speaker
library.

Embedding source: the per-cluster vectors WhisperX already wrote into the
diarized JSON via --speaker_embeddings (the worker always passes that flag).
This is the SAME embedding space apply_speaker_names.py --save-embeddings
persists into the library, so matches are apples-to-apples. We deliberately do
NOT re-run a separate pyannote/embedding model: that is a different vector
space (different dim), needs its own gated download + HF token, and would never
match a library built from WhisperX embeddings.

Pipeline:
  1. Read WhisperX diarized JSON (segments tagged SPEAKER_00, ... + a top-level
     speaker_embeddings block: {SPEAKER_NN: vector}).
  2. For each cluster: cosine-similarity against every library embedding (same
     dim only — mismatched library entries are skipped with a warning).
  3. If best-match similarity >= THRESHOLD → rename segments to that label.
     Otherwise leave as SPEAKER_NN (downstream surfaces it as 'unknown').
  4. Write updated JSON.

Library layout:
  ~/transcribe-pipeline/speaker-library/<context>/
    alice.npy     — (N, D) stacked samples (or (D,) single)
    ...
Bootstrap entries with apply_speaker_names.py --save-embeddings (preferred —
reads the same WhisperX speaker_embeddings block, so the spaces line up).
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def cosine_sim(a, b):
    """a: (D,) or (N,D); b: (D,) or (M,D) — returns max sim across pairs."""
    a = np.atleast_2d(a)
    b = np.atleast_2d(b)
    a_n = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b_n = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return float((a_n @ b_n.T).max())


def find_embeddings(data):
    """Return {speaker_label: np.ndarray (D,)} from the WhisperX
    --speaker_embeddings block. Probes the shapes whisperx has used across
    point releases (top-level dict, or list of {speaker, embedding})."""
    for key in ("speaker_embeddings", "embeddings", "speakers"):
        v = data.get(key)
        # Shape A: top-level dict {speaker: vec | {embedding: vec}}
        if isinstance(v, dict) and v:
            out = {}
            for spk, val in v.items():
                vec = val.get("embedding") if isinstance(val, dict) else val
                if vec is not None:
                    out[spk] = np.asarray(vec, dtype=float).reshape(-1)
            if out:
                return out
        # Shape B: list of {speaker, embedding}
        if isinstance(v, list) and v and isinstance(v[0], dict) and "embedding" in v[0]:
            return {d.get("speaker", d.get("label")):
                    np.asarray(d["embedding"], dtype=float).reshape(-1) for d in v}
    return {}


def load_library(lib_dir):
    lib = {}
    for npy in sorted(Path(lib_dir).expanduser().glob("*.npy")):
        lib[npy.stem] = np.load(npy)
    return lib


def write_through(data, out):
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams-json", required=True)
    ap.add_argument("--library", required=True, help="dir of {name}.npy files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.60,
                    help="cosine-similarity threshold for a hard auto-match (default 0.60)")
    ap.add_argument("--soft-floor", type=float, default=0.45,
                    help="lower floor for a soft match when one library voice is clearly "
                         "dominant (best >= soft-floor AND margin over 2nd >= --soft-margin)")
    ap.add_argument("--soft-margin", type=float, default=0.20,
                    help="min lead of best over 2nd-best for a soft match (default 0.20)")
    # Accepted for backward-compat with the worker invocation; no longer used —
    # embeddings come from the JSON, not a re-embedding of the wav.
    ap.add_argument("--teams-wav", default=None)
    ap.add_argument("--max-sample-s", type=float, default=20.0)
    args = ap.parse_args()

    data = json.loads(Path(args.teams_json).read_text(encoding="utf-8"))
    segments = data.get("segments", [])

    clusters = sorted({s.get("speaker") for s in segments
                       if (s.get("speaker") or "").startswith("SPEAKER_")})
    if not clusters:
        print("no SPEAKER_NN clusters found — nothing to rename", file=sys.stderr)
        write_through(data, args.out)
        return

    embs = find_embeddings(data)
    if not embs:
        print("WARN: no speaker_embeddings in JSON (was whisperx run with "
              "--speaker_embeddings?) — keeping raw SPEAKER_NN labels", file=sys.stderr)
        write_through(data, args.out)
        return

    library = load_library(args.library)
    if not library:
        print(f"warn: library {args.library} empty — keeping raw SPEAKER_NN labels",
              file=sys.stderr)
        write_through(data, args.out)
        return

    print(f"clusters: {clusters}", file=sys.stderr)
    print(f"library:  {sorted(library)}", file=sys.stderr)

    rename = {}
    for spk in clusters:
        emb = embs.get(spk)
        if emb is None:
            print(f"  {spk}: no embedding in JSON — keep raw", file=sys.stderr)
            continue
        scores = {}
        for name, lib_emb in library.items():
            lib2d = np.atleast_2d(lib_emb)
            if lib2d.shape[1] != emb.shape[0]:
                print(f"  {spk}: dim mismatch vs {name} "
                      f"({lib2d.shape[1]} != {emb.shape[0]}) — skip {name}", file=sys.stderr)
                continue
            scores[name] = cosine_sim(emb, lib2d)
        if not scores:
            print(f"  {spk} → KEEP (no comparable library entry)", file=sys.stderr)
            continue
        ranked = sorted(scores.values(), reverse=True)
        best = max(scores, key=lambda k: scores[k])
        best_sim = ranked[0]
        second = ranked[1] if len(ranked) > 1 else -1.0
        scores_str = ", ".join(f"{n}={s:.2f}" for n, s in sorted(scores.items(), key=lambda x: -x[1]))
        # Hard match (clearly over threshold) or soft match (one voice clearly
        # dominant: above the floor AND well ahead of the runner-up — catches a
        # short diarization fragment of a known speaker without lowering the bar
        # for genuine unknowns, whose scores are low and tightly clustered).
        hard = best_sim >= args.threshold
        soft = (not hard) and best_sim >= args.soft_floor and (best_sim - second) >= args.soft_margin
        if hard or soft:
            # Library keys are lowercase slugs (alice.npy); capitalize the first
            # letter for the transcript label without lowercasing the rest (so a
            # name like "McKay" survives). Multi-token slugs keep their case.
            rename[spk] = best[:1].upper() + best[1:]
            tag = "" if hard else "  [soft: dominant, lead %.2f]" % (best_sim - second)
            print(f"  {spk} → {rename[spk]}  (sim={best_sim:.2f}){tag}  [{scores_str}]", file=sys.stderr)
        else:
            print(f"  {spk} → KEEP  (best {best}={best_sim:.2f} < {args.threshold})  [{scores_str}]",
                  file=sys.stderr)

    for seg in segments:
        sp = seg.get("speaker")
        if sp in rename:
            seg["speaker"] = rename[sp]

    write_through(data, args.out)
    print(f"wrote {args.out}: renamed {len(rename)} of {len(clusters)} clusters",
          file=sys.stderr)


if __name__ == "__main__":
    main()
