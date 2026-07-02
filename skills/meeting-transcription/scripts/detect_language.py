#!/usr/bin/env python3
"""
detect_language.py — robust spoken-language detection by MAJORITY VOTE over
several short clips sampled ACROSS the recording (not just the opening). The
transcription worker calls this when a context/bundle language is "auto", then
FORCES the winning language for the full ASR run.

WHY multi-window: whisper.cpp auto-detect keys off the FIRST ~30 s only. A
meeting that opens in the "wrong" language (English smalltalk before a German
daily) misdetects — which is exactly why contexts used to be hard-pinned to a
single language (e.g. customer-x=en), silently breaking the other half of a
bilingual surface. Sampling 3 windows at 15/45/75 % and taking the majority is
immune to an unrepresentative opening and to a brief code-switch, at ~10-15 s
overhead (each detect is `whisper-cli -dl`: encoder + language head on ONE 30 s
clip, then exit — no full transcription).

Measured on a real customer-context pair: a German daily that the en-pin had
mis-transcribed to English detected `de` at 3/45/80 % (p≥0.97 each); an English
1:1 detected `en` — so plain `auto` already fixes the pin, and the vote adds
robustness for the smalltalk edge case.

Mechanism: ffmpeg cuts each clip to 16 kHz mono wav; `whisper-cli -dl -l auto`
prints `auto-detected language: <xx> (p = <prob>)` and exits; we parse the code
+ probability, tally votes (tie-break by summed probability), print the winning
2-letter code to STDOUT (nothing else). Diagnostics go to STDERR. If every clip
fails to detect, print nothing and exit 1 so the caller can fall back to
whisper's own single-window auto.

Needs only python3 stdlib + ffmpeg/ffprobe + whisper-cli on PATH — no venv
imports, so it runs under any python3 (same discipline as asr_whispercpp.py).

Usage:
  detect_language.py --audio teams.wav
  detect_language.py --audio in.mp3 --positions 0.15,0.45,0.75 --clip-len 30 \
      [--model ~/transcribe-pipeline/models/ggml-large-v3.bin] [--whisper-cli whisper-cli]
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

DEFAULT_MODEL = os.path.expanduser("~/transcribe-pipeline/models/ggml-large-v3.bin")
# whisper-cli prints e.g. "auto-detected language: de (p = 0.988894)" (stderr).
_LANG_RE = re.compile(r"auto-detected language:\s*([a-z]{2,3})\s*\(p\s*=\s*([0-9.]+)\)", re.I)


def log(msg):
    print(f"detect_language: {msg}", file=sys.stderr)


def audio_duration_s(ffprobe, audio):
    """Total duration in seconds, or None if ffprobe can't read it."""
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out)
    except (subprocess.SubprocessError, ValueError):
        return None


def detect_one(ffmpeg, whisper_cli, model, audio, offset_s, clip_len, tmpdir):
    """Cut a clip at offset and return (lang, prob) or None."""
    clip = os.path.join(tmpdir, f"clip_{int(offset_s)}.wav")
    cut = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-ss", str(int(offset_s)), "-i", str(audio),
         "-t", str(clip_len), "-ar", "16000", "-ac", "1", clip],
        capture_output=True, text=True, timeout=120,
    )
    if cut.returncode != 0 or not os.path.isfile(clip):
        log(f"  @{int(offset_s)}s ffmpeg cut failed")
        return None
    try:
        # -dl = detect-language-then-exit; -l auto so the language head runs.
        r = subprocess.run(
            [whisper_cli, "-m", model, "-f", clip, "-dl", "-l", "auto"],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.SubprocessError as e:
        log(f"  @{int(offset_s)}s whisper-cli failed: {e}")
        return None
    m = _LANG_RE.search((r.stderr or "") + "\n" + (r.stdout or ""))
    if not m:
        log(f"  @{int(offset_s)}s no language line in output")
        return None
    lang, prob = m.group(1).lower(), float(m.group(2))
    log(f"  @{int(offset_s)}s → {lang} (p={prob:.3f})")
    return lang, prob


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--positions", default="0.15,0.45,0.75",
                    help="comma-separated fractions of the recording to sample")
    ap.add_argument("--clip-len", type=int, default=30, help="clip length in seconds")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--whisper-cli", default="whisper-cli")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.is_file():
        log(f"audio not found: {audio}")
        sys.exit(1)
    if not Path(args.model).is_file():
        log(f"model not found: {args.model}")
        sys.exit(1)

    fracs = []
    for tok in args.positions.split(","):
        tok = tok.strip()
        if tok:
            try:
                fracs.append(min(max(float(tok), 0.0), 1.0))
            except ValueError:
                pass
    fracs = fracs or [0.15, 0.45, 0.75]

    dur = audio_duration_s(args.ffprobe, audio)
    # Build distinct, in-bounds offsets. Short audio (< clip_len) → one clip at 0.
    offsets = []
    if dur is None or dur <= args.clip_len:
        offsets = [0]
        if dur is None:
            log("ffprobe gave no duration → single opening clip")
    else:
        for f in fracs:
            off = int(f * dur)
            off = min(off, int(dur) - args.clip_len)   # keep clip inside the file
            off = max(off, 0)
            if off not in offsets:
                offsets.append(off)

    votes = defaultdict(int)
    probsum = defaultdict(float)
    with tempfile.TemporaryDirectory() as td:
        for off in offsets:
            res = detect_one(args.ffmpeg, args.whisper_cli, args.model,
                             audio, off, args.clip_len, td)
            if res:
                lang, prob = res
                votes[lang] += 1
                probsum[lang] += prob

    if not votes:
        log("no clip detected a language — caller should fall back to whisper auto")
        sys.exit(1)

    # Winner: most votes, tie-break by summed probability.
    winner = max(votes, key=lambda l: (votes[l], probsum[l]))
    tally = ", ".join(f"{l}×{votes[l]}(p̄={probsum[l] / votes[l]:.2f})" for l in votes)
    log(f"vote: {tally} → {winner}")
    print(winner)


if __name__ == "__main__":
    main()
