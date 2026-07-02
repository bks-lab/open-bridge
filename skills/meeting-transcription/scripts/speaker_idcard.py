#!/usr/bin/env python3
"""
speaker_idcard.py — after diarization, print a compact "ID card" per speaker
cluster so a human who attended the meeting can map SPEAKER_NN → real name
WITHOUT listening to audio (content recognition).

For each cluster: total talk-time, segment count, and the N longest/most
representative quotes. The attendee reads the quotes, recognizes who said
what, and provides the mapping.

Usage:
  speaker_idcard.py --json teams_out/<file>.json [--quotes 4]

Output (stdout): human-readable cards, e.g.

  ── SPEAKER_00 ── 7.2 min, 41 segments
    "Alright, let's just get started. The migration itself is nothing new…"
    "I only asked Carol to prepare an example project…"
    …

Then the user says: 0=Alice 1=Bob 2=Carol  →  apply_speaker_names.py
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--quotes", type=int, default=4)
    ap.add_argument("--min-seg-len", type=float, default=4.0,
                    help="ignore segments shorter than this (s) when picking quotes")
    args = ap.parse_args()

    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    segs = data.get("segments", [])

    by_spk = defaultdict(list)
    talk = defaultdict(float)
    for s in segs:
        spk = s.get("speaker", "SPEAKER_??")
        dur = float(s.get("end", 0)) - float(s.get("start", 0))
        talk[spk] += dur
        text = (s.get("text") or "").strip()
        if text:
            by_spk[spk].append((dur, float(s.get("start", 0)), text))

    print(f"\n{'='*70}")
    print(f"SPEAKER ID CARDS — {len(by_spk)} clusters, {len(segs)} segments total")
    print(f"{'='*70}")
    for spk in sorted(by_spk):
        quotes = sorted(by_spk[spk], key=lambda r: r[0], reverse=True)
        quotes = [q for q in quotes if q[0] >= args.min_seg_len][: args.quotes]
        if not quotes:  # fall back to longest regardless of min-len
            quotes = sorted(by_spk[spk], key=lambda r: r[0], reverse=True)[: args.quotes]
        print(f"\n── {spk} ──  {talk[spk]/60:.1f} min talk, {len(by_spk[spk])} segments")
        for dur, start, text in quotes:
            mm, ss = divmod(int(start), 60)
            preview = text[:160] + ("…" if len(text) > 160 else "")
            print(f'  [{mm:02d}:{ss:02d}, {dur:.0f}s] "{preview}"')

    print(f"\n{'='*70}")
    print("→ Map clusters to names, e.g.:  SPEAKER_00=Alice SPEAKER_01=Bob SPEAKER_02=Carol")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
