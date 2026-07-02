#!/usr/bin/env python3
"""
diarize_assign.py — diarize a track on the GPU (Apple MPS) and stitch the
speaker turns + 256-d voice embeddings onto an ASR transcript (from
asr_whispercpp.py / asr_mlx.py), emitting the SAME JSON shape the old
`whisperx --diarize --speaker_embeddings` call produced. The speaker half of
the hybrid pipeline.

WHY this and not raw pyannote: the per-context voice library
(speaker-library/<ctx>/*.npy) was built from WhisperX's `--speaker_embeddings`
block. WhisperX's DiarizationPipeline(...).(return_embeddings=True) is the EXACT
same code path / vector space — so the existing library keeps matching (verified:
a speaker enrolled via the old path matched at 0.90 against the unchanged
library). A separately-instantiated embedding model would be a different space
and never match (see speaker_naming.py header).

Only the DEVICE changes vs the old path: pyannote runs on MPS instead of CPU
(~4 min for a 38-min track vs the old CPU diarize). CTranslate2 (the old ASR)
had no Metal backend and forced CPU; pyannote is PyTorch → supports MPS.
PYTORCH_ENABLE_MPS_FALLBACK=1 lets any op without an MPS kernel fall back to CPU.

Assignment: each ASR segment gets the speaker of the diarization turn it
overlaps most, then consecutive same-speaker segments are coalesced into one
readable turn. Phrase-level ASR segments (asr_whispercpp.py -ml 50) keep this
accurate even with several speakers on the track.

Runs in ~/venvs/whisperx (whisperx 3.8.5 + pyannote.audio 4.x), UNCHANGED.

Output JSON (consumed unchanged by speaker_naming.py → merge_transcripts.py):
  {"language": "de",
   "segments": [{"start","end","text","speaker": "SPEAKER_00"}],
   "speaker_embeddings": {"SPEAKER_00": [...256 floats...], ...}}

Usage:
  diarize_assign.py --asr teams_out/teams_asr.json --audio teams.wav \
      --out teams_out/teams.json [--hf-token <tok>] [--device mps] \
      [--diar-cache teams_out/teams_diar.json]   # reuse diarization across re-runs
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Must be set before torch is imported (via whisperx) so MPS-missing ops fall
# back to CPU instead of raising.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

DEFAULT_DIARIZE_MODEL = "pyannote/speaker-diarization-community-1"


def resolve_token(cli_token):
    if cli_token:
        return cli_token
    f = Path.home() / ".config/open-bridge/hf-token"
    if f.is_file():
        return f.read_text(encoding="utf-8").strip()
    return os.environ.get("HF_TOKEN") or None


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def run_diarization(audio, model, token, device):
    """Return (turns, embeddings) where turns=[(start,end,speaker)] and
    embeddings={speaker: [floats]}. Uses WhisperX's DiarizationPipeline so the
    embedding space matches the library exactly."""
    from whisperx.diarize import DiarizationPipeline  # import after env set
    dp = DiarizationPipeline(model_name=model, token=token, device=device)
    # str path → whisperx.load_audio (ffmpeg) → in-memory waveform to pyannote,
    # which sidesteps the broken torchcodec in the venv.
    diarize_df, embeddings = dp(audio, return_embeddings=True)
    turns = []
    for row in diarize_df.itertuples(index=False):
        d = row._asdict()
        turns.append((float(d["start"]), float(d["end"]), str(d["speaker"])))
    turns.sort(key=lambda t: t[0])
    emb = {}
    if isinstance(embeddings, dict):
        for spk, vec in embeddings.items():
            try:
                emb[str(spk)] = [float(x) for x in list(vec)]
            except TypeError:
                pass
    return turns, emb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asr", required=True, help="ASR JSON (segments + language)")
    ap.add_argument("--audio", required=True, help="the same wav that was transcribed")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hf-token", default=None)
    ap.add_argument("--device", default="mps", help="mps|cpu (mps = use the GPU)")
    ap.add_argument("--diarize-model", default=DEFAULT_DIARIZE_MODEL)
    ap.add_argument("--diar-cache", default=None,
                    help="cache file for diarization turns+embeddings; loaded if "
                         "present (skip re-diarize), written otherwise")
    args = ap.parse_args()

    asr = json.loads(Path(args.asr).read_text(encoding="utf-8"))
    segments = asr.get("segments", [])
    lang = asr.get("language", "de")

    # Diarization: from cache if available, else run + persist.
    turns, embeddings = None, None
    if args.diar_cache and Path(args.diar_cache).is_file():
        c = json.loads(Path(args.diar_cache).read_text(encoding="utf-8"))
        turns = [tuple(t) for t in c["turns"]]
        embeddings = c["embeddings"]
        print(f"diarize_assign: loaded diarization from cache {args.diar_cache}",
              file=sys.stderr)
    else:
        token = resolve_token(args.hf_token)
        if not token:
            sys.exit("diarize_assign: no HF token (--hf-token / ~/.config/open-bridge/hf-token / $HF_TOKEN)")
        turns, embeddings = run_diarization(args.audio, args.diarize_model, token, args.device)
        if args.diar_cache:
            Path(args.diar_cache).write_text(
                json.dumps({"turns": turns, "embeddings": embeddings}, ensure_ascii=False),
                encoding="utf-8")

    # Assign each ASR segment the speaker whose turn it overlaps most (segment
    # level — phrase-length segments keep this accurate; merge never used words).
    fallback = turns[0][2] if turns else "SPEAKER_00"
    assigned = []
    for s in segments:
        st, en = float(s.get("start", 0.0)), float(s.get("end", 0.0))
        best_spk, best_ov = None, 0.0
        for (ts, te, spk) in turns:
            if ts > en:
                break
            ov = overlap(st, en, ts, te)
            if ov > best_ov:
                best_ov, best_spk = ov, spk
        assigned.append({"start": st, "end": en, "text": s.get("text", ""),
                         "speaker": best_spk or fallback})

    # NB: do NOT coalesce consecutive same-speaker segments. merge_transcripts.py
    # interleaves the mic and teams tracks by per-segment start time; collapsing a
    # speaker's segments into one block would give that block a single start time
    # and scramble the chronological interleave (a single-speaker teams track
    # would otherwise become one giant line). Keep phrase-level granularity.
    out = {"language": lang, "segments": assigned, "speaker_embeddings": embeddings or {}}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n_clusters = len({t[2] for t in turns})
    print(f"diarize_assign: {len(segments)} segments, {n_clusters} clusters, "
          f"{len(embeddings or {})} embeddings, device={args.device}", file=sys.stderr)


if __name__ == "__main__":
    main()
