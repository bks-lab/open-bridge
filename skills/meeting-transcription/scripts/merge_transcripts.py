#!/usr/bin/env python3
"""
merge_transcripts.py — interleave WhisperX mic-track + named-teams-track JSON
into a single chronological raw-Markdown transcript.

Inputs:
  --mic          mic_out/mic.json        (no speakers; everything is the mic speaker)
  --teams        teams-named.json        (speaker field is either real name or SPEAKER_NN)
  --manifest     manifest.yaml           (recorded_at, duration_s, channels...)
  --out          transcript-raw.md
  --mic-speaker  name for the mic-track speaker (default: manifest mic_speaker, else "Me")

Output format:
  ---
  type: meeting-transcript-raw
  date: 2026-05-24
  recorded_at: 2026-05-24T14:30:15Z
  duration_min: 47
  participants: [Alice, Bob, Carol]     # auto-derived from speakers seen
  unknown_speakers: [SPEAKER_02]        # if any cluster not named
  source: audio-hijack-2track-splitchannels
  ---

  # Meeting Transcript — 2026-05-24 14:30

  ## Full Transcript
  [14:30:12] **Alice:** Let's get started.
  [14:30:18] **Bob:** Right — about the cloud account.
  [14:30:25] **Carol:** Yes, I've got the account.
  ...

This file is intermediate. summarize.py post-processes it into the final
structured MD with TL;DR / Decisions / Action Items / Topics.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load_yaml(path):
    # Tiny YAML reader — manifest has flat keys only, no need for PyYAML
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.rstrip()
        if not line or line.startswith("#") or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def fmt_clock(base_dt, offset_s):
    return (base_dt + timedelta(seconds=offset_s)).strftime("%H:%M:%S")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mic", required=True)
    ap.add_argument("--teams", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mic-speaker", default=None,
                    help="name for the mic-track speaker (default: manifest mic_speaker, else 'Me')")
    args = ap.parse_args()

    mic = json.loads(Path(args.mic).read_text(encoding="utf-8"))
    teams = json.loads(Path(args.teams).read_text(encoding="utf-8"))
    manifest = load_yaml(args.manifest)

    # Mic-track speaker name: CLI arg > manifest key mic_speaker > "Me".
    mic_speaker = args.mic_speaker or manifest.get("mic_speaker") or "Me"

    # Detected language drives section labels + downstream summary-prompt choice.
    lang = (teams.get("language") or mic.get("language") or "de").lower()[:2]
    L = {
        "de": {"title": "Meeting Transcript", "full": "Volltext",
               "note": "Hinweis", "unknown_msg": "Sprecher-Cluster konnten nicht "
               "automatisch gelabelt werden", "lib_hint": "Voice-Library erweitern "
               "für künftige Auto-Erkennung."},
        "en": {"title": "Meeting Transcript", "full": "Full Transcript",
               "note": "Note", "unknown_msg": "speaker cluster(s) could not be "
               "auto-labelled", "lib_hint": "Extend the voice library for future "
               "auto-recognition."},
    }.get(lang, None)
    if L is None:
        L = {"title": "Meeting Transcript", "full": "Full Transcript", "note": "Note",
             "unknown_msg": "speaker cluster(s) could not be auto-labelled",
             "lib_hint": "Extend the voice library for future auto-recognition."}

    recorded_at = manifest.get("recorded_at", "")
    try:
        base = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError:
        base = datetime.now(timezone.utc)
    base_local = base.astimezone()   # display in local tz

    duration_s = int(manifest.get("duration_s", "0"))
    duration_min = max(1, round(duration_s / 60))

    # Collect segments — annotate source so we can tag the speaker.
    segments = []
    for s in mic.get("segments", []):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "start": float(s["start"]),
            "speaker": mic_speaker,
            "text": text,
        })
    for s in teams.get("segments", []):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        speaker = s.get("speaker", "SPEAKER_??")
        # WhisperX raw labels look like "SPEAKER_00"; speaker_naming.py replaces
        # matched ones with real names. Anything that still starts SPEAKER_ is unknown.
        segments.append({
            "start": float(s["start"]),
            "speaker": speaker,
            "text": text,
        })

    segments.sort(key=lambda x: x["start"])

    # Participants — order by first appearance for stable header
    seen = []
    unknown = []
    for s in segments:
        sp = s["speaker"]
        if sp.startswith("SPEAKER_"):
            if sp not in unknown:
                unknown.append(sp)
        elif sp not in seen:
            seen.append(sp)

    date_str = base_local.strftime("%Y-%m-%d")
    time_str = base_local.strftime("%H:%M")

    lines = []
    lines.append("---")
    lines.append("type: meeting-transcript-raw")
    lines.append(f"date: {date_str}")
    lines.append(f"recorded_at: {recorded_at}")
    lines.append(f"duration_min: {duration_min}")
    lines.append(f"language: {lang}")
    lines.append(f"participants: [{', '.join(seen) if seen else mic_speaker}]")
    if unknown:
        lines.append(f"unknown_speakers: [{', '.join(unknown)}]")
    # Honor the manifest's source if present (e.g. single-track downmix); the
    # bundler writes audio-hijack-2track-splitchannels for real 2-track captures.
    lines.append(f"source: {manifest.get('source') or 'audio-hijack-2track-splitchannels'}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {L['title']} — {date_str} {time_str}")
    lines.append("")
    if unknown:
        lines.append(f"> {L['note']}: {len(unknown)} {L['unknown_msg']} "
                     f"({', '.join(unknown)}). {L['lib_hint']}")
        lines.append("")
    lines.append(f"## {L['full']}")
    lines.append("")
    for s in segments:
        clock = fmt_clock(base_local, s["start"])
        lines.append(f"[{clock}] **{s['speaker']}:** {s['text']}")
        lines.append("")   # blank line between utterances → don't collapse into one
                            # soft-wrapped paragraph on GitHub/Markdown (single newlines
                            # are merged). Mirrors anchor_transcript.py._emit_utterance.

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}: {len(segments)} segments, "
          f"{len(seen)} named speakers, {len(unknown)} unknown clusters",
          file=sys.stderr)


if __name__ == "__main__":
    main()
