#!/usr/bin/env python3
"""
asr_whispercpp.py — Whisper ASR via whisper.cpp (whisper-cli, Metal GPU), the
hybrid pipeline's ASR step. Replaces the CPU-only WhisperX/CTranslate2 transcribe.

WHY whisper.cpp and not MLX: on a 16 GB M4, MLX-Whisper large-v3 thrashes
swap (unified-memory Metal buffers); whisper.cpp loads the GGML model
memory-disciplined and runs the encoder on Metal — real large-v3 quality,
~3.5x realtime, stable. (Measured: 38-min track in 10m42s vs MLX
large-v3 still unfinished at 17m.) NOT turbo — the full large-v3 weights.

ASR ONLY: text + segment timestamps + language. Speaker identity stays in
diarize_assign.py (pyannote/whisperx on MPS — same 256-d space as the library).

Segmentation: `-ml <max-len> -sow` yields clean phrase-level segments (~2-3 s,
word-boundary splits) instead of whisper.cpp's default ~12 s segments. Short
segments rarely span a speaker turn, so the downstream overlap-assignment in
diarize_assign stays accurate even on multi-speaker tracks (a long segment
straddling a turn boundary is the classic mis-label source).

Loop-safety: runs with `-mc 0` (no prior-text context) so the decoder can't feed
its own output back and lock into a repetition/hallucination loop on quiet
stretches — whisper.cpp's unbounded default (-mc -1) does exactly that. Tunable
via --max-context; see that flag's help for the incident it fixes.

Needs only whisper-cli (brew install whisper-cpp) + the GGML model; no venv
imports, so it runs under any python3.

Output JSON (consumed by diarize_assign.py / merge_transcripts.py):
  {"language": "de", "segments": [{"start","end","text"}], "duration": <s>}

Usage:
  asr_whispercpp.py --audio teams.wav --out teams_out/teams_asr.json [--language de] \
      [--model ~/transcribe-pipeline/models/ggml-large-v3.bin] [--max-len 50] [--threads 8]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_MODEL = os.path.expanduser("~/transcribe-pipeline/models/ggml-large-v3.bin")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--language", default=None, help="de|en|... ; omit/'auto' to detect")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-len", type=int, default=50,
                    help="whisper.cpp -ml: max segment length in chars (phrase-level)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--max-context", type=int, default=0,
                    help="whisper.cpp -mc: max text-context tokens carried across "
                         "decode windows. Default 0 DISABLES prior-text conditioning. "
                         "whisper.cpp's own default is -1 (unbounded), which lets the "
                         "decoder feed its last output back into itself and lock into a "
                         "repetition/hallucination loop on quiet/low-speech stretches "
                         "(observed in production: a 23-min customer-context track looped "
                         "'I'm just going to be in charge of the whole thing' x250 from "
                         "min ~7, deterministically — re-runs reproduced it "
                         "byte-for-byte). "
                         "0 breaks the feedback path; temperature fallback (no -nf) stays "
                         "on. Harmless here because -ml/-sow already cut phrase-level "
                         "segments, so cross-window text context buys little.")
    ap.add_argument("--whisper-cli", default="whisper-cli")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.is_file():
        sys.exit(f"asr_whispercpp: audio not found: {audio}")
    if not Path(args.model).is_file():
        sys.exit(f"asr_whispercpp: model not found: {args.model}")

    lang = (args.language or "").strip().lower() or "auto"
    with tempfile.TemporaryDirectory() as td:
        prefix = os.path.join(td, "out")
        # -mc 0: no prior-text context → prevents the repetition-loop whisper.cpp's
        # unbounded default (-mc -1) falls into on quiet stretches. See --max-context.
        cmd = [args.whisper_cli, "-m", args.model, "-f", str(audio),
               "-l", lang, "-ml", str(args.max_len), "-sow",
               "-mc", str(args.max_context),
               "-oj", "-of", prefix, "-t", str(args.threads)]
        t0 = time.time()
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dt = time.time() - t0
        if r.returncode != 0:
            sys.exit(f"asr_whispercpp: whisper-cli failed (rc={r.returncode})")
        wj = json.loads(Path(prefix + ".json").read_text(encoding="utf-8"))

    segments = []
    for t in wj.get("transcription", []):
        text = (t.get("text") or "").strip()
        if not text:
            continue
        o = t.get("offsets", {})
        segments.append({
            "start": float(o.get("from", 0)) / 1000.0,
            "end": float(o.get("to", 0)) / 1000.0,
            "text": text,
        })

    detected = ((wj.get("result") or {}).get("language")
                or (lang if lang != "auto" else "de"))
    out = {"language": detected, "segments": segments, "duration": round(dt, 1)}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"asr_whispercpp: {len(segments)} segments, lang={detected}, {dt:.0f}s",
          file=sys.stderr)


if __name__ == "__main__":
    main()
