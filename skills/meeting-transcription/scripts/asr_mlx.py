#!/usr/bin/env python3
"""
asr_mlx.py — Whisper ASR via Apple MLX (runs on the M-series GPU), the hybrid
pipeline's replacement for the CPU-only WhisperX/CTranslate2 transcription step.

WHY: WhisperX → faster-whisper → CTranslate2 has no Metal backend, so on Apple
Silicon it runs pure CPU (~4 of 10 cores on an M4, GPU/ANE idle). MLX-Whisper
runs large-v3 natively on the GPU — multiples faster for the same model.

This script does ASR ONLY: text + segment timestamps + detected language. It has
nothing to do with speaker identity — diarization and the 256-d voice embeddings
stay in diarize_assign.py (WhisperX/pyannote, same vector space as the library).

Runs in the ISOLATED venv ~/venvs/mlx-asr (mlx-whisper pulls numba, which forces
an older numpy than the whisperx venv needs — so it must NOT share that venv).

Output JSON (matches what merge_transcripts.py / diarize_assign.py consume):
  {"language": "de", "segments": [{"start": 0.0, "end": 3.2, "text": "..."}], "duration": <s>}

Usage:
  asr_mlx.py --audio teams.wav --out teams_out/teams_asr.json [--language de] \
             [--model mlx-community/whisper-large-v3-mlx]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import mlx_whisper

# large-v3 (NOT turbo) to keep transcription quality identical to the old CPU
# path. Swap to mlx-community/whisper-large-v3-turbo for ~more speed at a small
# quality cost — keep this the single place that decides the ASR model.
DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="16 kHz mono wav (or any ffmpeg-readable)")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--language", default=None,
                    help="de|en|... ; omit or 'auto' to let Whisper detect")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="HF repo of the MLX Whisper model")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.is_file():
        sys.exit(f"asr_mlx: audio not found: {audio}")

    kwargs = {"path_or_hf_repo": args.model, "word_timestamps": False}
    lang = (args.language or "").strip().lower()
    if lang and lang != "auto":
        kwargs["language"] = lang

    t0 = time.time()
    result = mlx_whisper.transcribe(str(audio), **kwargs)
    dt = time.time() - t0

    segments = []
    for s in result.get("segments", []):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "start": float(s.get("start", 0.0)),
            "end": float(s.get("end", 0.0)),
            "text": text,
        })

    out = {
        "language": (result.get("language") or lang or "de"),
        "segments": segments,
        "duration": round(dt, 1),
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"asr_mlx: {len(segments)} segments, lang={out['language']}, {dt:.0f}s "
          f"(model={args.model})", file=sys.stderr)


if __name__ == "__main__":
    main()
