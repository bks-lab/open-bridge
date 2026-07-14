#!/usr/bin/env python3
"""
anchor_transcript.py — add stable per-utterance anchors + relative timestamps to
a naked meeting transcript, so a summary can deep-link to the exact statement.

The worker (meeting-transcription) emits a naked transcript whose absolute
[HH:MM:SS] timestamps are processing/delivery-anchored (NOT real meeting time)
and whose lines carry NO addressable anchor. This bridge-side transform rewrites
each utterance line

    [HH:MM:SS] **Speaker:** text

into

    <a name="<prefix>-NNN"></a>**[+MM:SS] Speaker:** text

Each utterance is separated from the next by a blank line, so adjacent
utterances render as their own lines on GitHub/Markdown instead of collapsing
into one soft-wrapped paragraph (single newlines between lines are merged).

where the time is RELATIVE to the first segment, and writes a sidecar index
(<file>.index.tsv: anchor<TAB>rel<TAB>speaker<TAB>text) for the summary's
evidence-link lookup. The worker's own merge step stays untouched; this runs on
the bridge side (called by /debrief when materialising the meeting home).

Idempotent: lines already starting with `<a name=` are left as-is, so re-running
is safe — already-anchored lines are parsed back into the sidecar index, so a
rerun regenerates (never empties) <file>.index.tsv.

Usage:
  anchor_transcript.py transcript-call.md --prefix c
  anchor_transcript.py transcript-call.md transcript-internal.md --prefix c i
  # last --prefix value repeats if fewer prefixes than files are given
"""
import re
import os
import argparse

UTT = re.compile(r'^\[(\d{2}):(\d{2}):(\d{2})\] \*\*([^:]+):\*\* (.*)$')
ALREADY = re.compile(r'^<a name=')
# Anchored line as written by this script — parsed back on rerun so the
# sidecar index can be regenerated instead of emptied.
ANCHORED = re.compile(r'^<a name="([^"]+)"></a>\*\*\[(\+\d+:\d{2})\] ([^:]+):\*\* (.*)$')


def _emit_utterance(out, line):
    """Append an utterance line preceded by exactly one blank line, so adjacent
    utterances render as separate lines (not a single merged paragraph). Idempotent
    on rerun: if the previous line is already blank, no extra blank is inserted."""
    if out and out[-1] != "":
        out.append("")
    out.append(line)


def anchor(path, prefix):
    lines = open(path, encoding="utf-8").read().split("\n")
    out, idx, n, base = [], [], 0, None
    for ln in lines:
        am = ANCHORED.match(ln)
        if am:                           # already anchored -> keep line, re-index
            _emit_utterance(out, ln)
            aid, rel, spk, txt = am.groups()
            idx.append((aid, rel, spk, txt))
            nm = re.search(r'-(\d+)$', aid)
            if nm:                       # continue numbering after existing anchors
                n = max(n, int(nm.group(1)))
            continue
        if ALREADY.match(ln):            # anchored but non-standard -> no-op
            out.append(ln)
            continue
        m = UTT.match(ln)
        if not m:
            out.append(ln)
            continue
        n += 1
        aid = f"{prefix}-{n:03d}"
        hh, mm, ss, spk, txt = m.groups()
        t = int(hh) * 3600 + int(mm) * 60 + int(ss)
        if base is None:
            base = t
        rel = max(t - base, 0)
        rm, rs = divmod(rel, 60)
        _emit_utterance(out, f'<a name="{aid}"></a>**[+{rm:02d}:{rs:02d}] {spk}:** {txt}')
        idx.append((aid, f"+{rm:02d}:{rs:02d}", spk, txt))
    open(path, "w", encoding="utf-8").write("\n".join(out))
    ipath = re.sub(r'\.md$', '.index.tsv', path)
    with open(ipath, "w", encoding="utf-8") as f:
        for row in idx:
            f.write("\t".join(row) + "\n")
    return len(idx), ipath


def main():
    ap = argparse.ArgumentParser(description="Anchor a naked transcript for deep-linkable evidence.")
    ap.add_argument("files", nargs="+", help="transcript .md file(s)")
    ap.add_argument("--prefix", nargs="+", default=["t"],
                    help="anchor prefix per file (e.g. c i); last value repeats")
    a = ap.parse_args()
    for i, f in enumerate(a.files):
        pre = a.prefix[i] if i < len(a.prefix) else a.prefix[-1]
        n, ipath = anchor(f, pre)
        print(f"{os.path.basename(f)}: {n} segments anchored -> {os.path.basename(ipath)}")


if __name__ == "__main__":
    main()
