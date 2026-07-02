#!/usr/bin/env python3
"""
extract_voice_sample.py — bootstrap the speaker library from a known-speaker
audio clip, in the SAME embedding space the worker matches against.

Why this runs WhisperX (not a bare pyannote/embedding model): speaker_naming.py
matches clusters using the per-speaker vectors WhisperX writes with
--speaker_embeddings (the diarization model's space). The library MUST live in
that same space, so we extract the clip's voiceprint via the identical WhisperX
path the worker uses, then keep the dominant speaker's embedding. A standalone
pyannote/embedding Inference would produce a different-dim vector that never
matches (and the new pyannote API no longer takes a model-name string).

Usage:
  extract_voice_sample.py --audio <path.wav|mp3> --label <name> \
                          [--start-s 30] [--end-s 60] \
                          [--library ~/transcribe-pipeline/speaker-library/<ctx>] \
                          [--hf-token <tok>]  [--diarize-model <id>]

Behavior:
  - Slices audio (optional) and downmixes to 16 kHz mono.
  - Runs WhisperX (--model tiny — ASR model is irrelevant to the embedding;
    the voiceprint comes from the diarization model) with --diarize
    --speaker_embeddings.
  - Picks the dominant speaker cluster (most talk-time) — the clip should be one
    person — and stacks its embedding into {label}.npy.

Multiple samples per speaker improve robustness — re-run with different
slices/sources. speaker_naming.py takes the BEST cosine-sim across stacked
embeddings. The preferred bootstrap is still apply_speaker_names.py
--save-embeddings straight off a real diarized meeting; use this for clean
solo clips (a voice memo, an intro where one person speaks alone).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

DEFAULT_DIARIZE_MODEL = "pyannote/speaker-diarization-community-1"


def slice_audio(src, start_s, end_s):
    """ffmpeg slice + downmix to 16 kHz mono WAV in a temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if start_s is not None:
        cmd += ["-ss", str(start_s)]
    if end_s is not None:
        cmd += ["-to", str(end_s)]
    cmd += ["-i", str(src), "-ar", "16000", "-ac", "1", tmp]
    subprocess.run(cmd, check=True)
    return tmp


def resolve_hf_token(explicit):
    if explicit:
        return explicit
    f = Path.home() / ".config/open-bridge/hf-token"
    if f.exists():
        return f.read_text().strip()
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
             "-s", "hf-token-pyannote", "-w"],
            capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def find_embeddings(data):
    """{speaker_label: np.ndarray (D,)} from the WhisperX --speaker_embeddings block."""
    for key in ("speaker_embeddings", "embeddings", "speakers"):
        v = data.get(key)
        if isinstance(v, dict) and v:
            out = {}
            for spk, val in v.items():
                vec = val.get("embedding") if isinstance(val, dict) else val
                if vec is not None:
                    out[spk] = np.asarray(vec, dtype=float).reshape(-1)
            if out:
                return out
        if isinstance(v, list) and v and isinstance(v[0], dict) and "embedding" in v[0]:
            return {d.get("speaker", d.get("label")):
                    np.asarray(d["embedding"], dtype=float).reshape(-1) for d in v}
    return {}


def dominant_speaker(data):
    """Speaker label with the most total talk-time in the diarized segments."""
    talk = {}
    for s in data.get("segments", []):
        spk = s.get("speaker")
        if not spk:
            continue
        talk[spk] = talk.get(spk, 0.0) + (float(s.get("end", 0)) - float(s.get("start", 0)))
    return max(talk, key=lambda k: talk[k]) if talk else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--label", required=True, help="speaker name, e.g. alice / bob")
    ap.add_argument("--start-s", type=float, default=None)
    ap.add_argument("--end-s", type=float, default=None)
    ap.add_argument("--library", default="~/transcribe-pipeline/speaker-library/main")
    ap.add_argument("--hf-token", default=None)
    ap.add_argument("--asr-model", default="tiny",
                    help="ASR model (irrelevant to the voiceprint; tiny = fast)")
    ap.add_argument("--diarize-model", default=DEFAULT_DIARIZE_MODEL)
    args = ap.parse_args()

    src = Path(args.audio).expanduser()
    if not src.exists():
        sys.exit(f"audio not found: {src}")

    hf = resolve_hf_token(args.hf_token)
    if not hf:
        sys.exit("HF token missing — pass --hf-token or put it in "
                 "~/.config/open-bridge/hf-token "
                 "(keychain hf-token-pyannote also works)")

    lib_dir = Path(args.library).expanduser()
    lib_dir.mkdir(parents=True, exist_ok=True)

    wav_path = slice_audio(src, args.start_s, args.end_s)
    outdir = tempfile.mkdtemp(prefix="voicesample_")
    try:
        cmd = ["whisperx", wav_path, "--model", args.asr_model,
               "--compute_type", "int8", "--batch_size", "4", "--device", "cpu",
               "--diarize", "--diarize_model", args.diarize_model,
               "--speaker_embeddings", "--hf_token", hf,
               "--output_format", "json", "--output_dir", outdir]
        print(f"  running whisperx (asr={args.asr_model}, diarize) …", file=sys.stderr)
        subprocess.run(cmd, check=True)
        js = next(iter(Path(outdir).glob("*.json")), None)
        if js is None:
            sys.exit("whisperx produced no JSON — cannot extract embedding")
        data = json.loads(js.read_text(encoding="utf-8"))
        embs = find_embeddings(data)
        if not embs:
            sys.exit("no speaker_embeddings in whisperx output — extraction failed")
        spk = dominant_speaker(data) or next(iter(embs))
        emb = embs.get(spk)
        if emb is None:
            spk = next(iter(embs))
            emb = embs[spk]
        emb = np.asarray(emb, dtype=float).reshape(1, -1)
        print(f"  dominant speaker {spk}: embedding shape={emb.shape} "
              f"norm={np.linalg.norm(emb):.3f}", file=sys.stderr)
    finally:
        Path(wav_path).unlink(missing_ok=True)
        subprocess.run(["rm", "-rf", outdir])

    target = lib_dir / f"{args.label.lower()}.npy"
    if target.exists():
        existing = np.load(target)
        if existing.ndim == 1:
            existing = existing.reshape(1, -1)
        if existing.shape[1] != emb.shape[1]:
            sys.exit(f"dim mismatch: {target.name} has dim {existing.shape[1]} but new "
                     f"sample is {emb.shape[1]} — different embedding space, refusing to mix")
        emb = np.vstack([existing, emb])
        print(f"  appended to {target}: now {emb.shape[0]} samples", file=sys.stderr)
    else:
        print(f"  created {target}: 1 sample (dim {emb.shape[1]})", file=sys.stderr)
    np.save(target, emb)


if __name__ == "__main__":
    main()
