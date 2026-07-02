#!/usr/bin/env python3
"""
summarize.py — turn transcript-raw.md into structured transcript.md by calling
`claude -p` (Claude CLI), the house pattern for headless LLM work.

⚠️ RETIRED FROM THE WORKER PIPELINE. The worker no longer summarizes:
a headless worker-side `claude -p` is CONTEXT-BLIND (no name-conventions, board,
open issues, contexts, prior meetings) and its summary distorts names +
significance, then propagates as "the record". Summarizing is now the in-session
/debrief's job, where Bridge context is loaded. This script is kept only as a
MANUAL headless fallback (e.g. bulk re-summarize without a session) — it is NOT in
transcribe-worker.sh anymore. Prefer the context-aware /debrief summary.

No local LLM host: Claude is the summarizer. This mirrors the scheduler
house pattern (claude-bin discovery, --setting-sources). Quality > a local
32B model, and there's one less machine to keep awake.

Inputs:
  --raw         transcript-raw.md       (interleaved [HH:MM:SS] **Speaker:** text)
  --prompt-dir  dir with meeting-summary-{lang}.md  (language-selected)
  --prompt      explicit prompt file (overrides language selection)
  --out         transcript.md           (summary + transcript)
  --model       claude model (default: opus)

Language: read from raw frontmatter `language:` (written by merge_transcripts.py).
Picks meeting-summary-{lang}.md, falls back de → any.

Failure: if `claude -p` is unavailable or errors, exit non-zero so the worker
falls back to delivering the raw transcript (summary header omitted).
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# "Volltext" is the German-language section heading merge_transcripts.py emits
# for de-language meetings — both spellings must be recognized here.
TRANSCRIPT_HEADINGS = ("## volltext", "## full transcript")


def read_frontmatter_lang(raw_md):
    lines = raw_md.splitlines()
    if not lines or lines[0].strip() != "---":
        return "de"
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.strip().lower().startswith("language:"):
            return line.split(":", 1)[1].strip().lower()[:2]
    return "de"


def extract_transcript_section(raw_md):
    lines = raw_md.splitlines()
    fm_end = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i + 1
                break
    fm = "\n".join(lines[:fm_end])
    t_start = None
    for i, line in enumerate(lines[fm_end:], start=fm_end):
        if line.strip().lower() in TRANSCRIPT_HEADINGS:
            t_start = i + 1
            break
    if t_start is None:
        return fm, "\n".join(lines[fm_end:]), []
    header = "\n".join(lines[fm_end:t_start - 1])
    transcript = [ln for ln in lines[t_start:] if ln.strip()]
    return fm, header, transcript


def find_claude_bin():
    """House pattern: prefer ~/.claude/local/claude, then PATH."""
    local = Path.home() / ".claude" / "local" / "claude"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    found = shutil.which("claude")
    return found  # may be None


def call_claude(prompt, model):
    claude = find_claude_bin()
    if not claude:
        raise RuntimeError("claude CLI not found (checked ~/.claude/local/claude + PATH)")
    # Prompt on stdin keeps long transcripts off argv. No tools needed for
    # pure text→text; --setting-sources matches the scheduler house pattern.
    proc = subprocess.run(
        [claude, "-p", "--model", model, "--setting-sources", "user,project"],
        input=prompt, text=True, capture_output=True, timeout=900,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exit {proc.returncode}: {proc.stderr[:300]}")
    return proc.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--prompt", help="explicit prompt file (overrides language selection)")
    ap.add_argument("--prompt-dir", help="dir with meeting-summary-{lang}.md")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="opus")
    args = ap.parse_args()

    raw = Path(args.raw).read_text(encoding="utf-8")
    lang = read_frontmatter_lang(raw)

    if args.prompt:
        prompt_path = Path(args.prompt)
    else:
        # Default: peer-folder ../prompts (skills/meeting-transcription/prompts/).
        # transcribe-worker.sh passes --prompt-dir explicitly on the worker host
        # (~/transcribe-pipeline/prompts/) so this default is only hit during
        # manual invocation from the source tree.
        pdir = Path(args.prompt_dir) if args.prompt_dir else Path(__file__).resolve().parent.parent / "prompts"
        prompt_path = pdir / f"meeting-summary-{lang}.md"
        if not prompt_path.exists():
            fb = pdir / "meeting-summary-de.md"
            prompt_path = fb if fb.exists() else next(pdir.glob("meeting-summary-*.md"))
    print(f"language={lang} → prompt={prompt_path.name} model={args.model}", file=sys.stderr)
    template = prompt_path.read_text(encoding="utf-8")

    fm, header, transcript_lines = extract_transcript_section(raw)
    transcript_block = "\n".join(transcript_lines)
    full_label = "Full Transcript" if lang == "en" else "Volltext"

    prompt = template.replace("{{TRANSCRIPT}}", transcript_block)
    print(f"calling claude -p ({len(prompt)} chars, {len(transcript_lines)} transcript lines)",
          file=sys.stderr)

    try:
        summary = call_claude(prompt, args.model)
    except Exception as e:
        sys.exit(f"FATAL: {type(e).__name__}: {e}")
    if not summary:
        sys.exit("FATAL: empty response from claude -p")

    fm_final = fm.replace("type: meeting-transcript-raw", "type: meeting-transcript")
    parts = [
        fm_final, "", header.strip() if header.strip() else "", "",
        summary.strip(), "", f"## {full_label}", "", transcript_block, "",
    ]
    Path(args.out).write_text("\n".join(p for p in parts if p is not None), encoding="utf-8")
    print(f"wrote {args.out}: {len(summary)} chars summary + {len(transcript_lines)} transcript lines",
          file=sys.stderr)


if __name__ == "__main__":
    main()
