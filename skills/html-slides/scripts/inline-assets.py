#!/usr/bin/env python3
"""Fold a deck's local files into the deck so it runs as one offline file.

A thin wrapper: the work is done by the shared bundler in the html-canvas skill
(skills/html-canvas/scripts/bundle.py), which this script finds relative to its
own location. Local images, stylesheets, scripts, fonts, iframes (as UTF-8 safe
base64 payloads) and, with --pages, linked local pages are inlined; remote
resources are refused unless --allow-remote; a sha256 per inlined source is
printed to stderr (or written with --manifest).

Usage:
    python3 inline-assets.py <input.html> <output.html> [bundle.py options]

Options after the two paths go to bundle.py unchanged (--pages, --allow-remote,
--manifest FILE, --design DESIGN.md, --font-dir DIR). Exit codes: 0 done,
1 a reference could not be resolved or the input is missing, 2 wrong usage.

Decks generated before fonts were self-hosted may link fonts.bunny.net. The
bundler refuses that remote link; regenerate the deck with new-deck.py (which
embeds its fonts) or pass --allow-remote to keep the link.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[2] / "html-canvas" / "scripts" / "bundle.py"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0].startswith("-") or argv[1].startswith("-"):
        print("Usage: inline-assets.py <input.html> <output.html> [bundle.py options]", file=sys.stderr)
        return 2
    src, dst, extra = Path(argv[0]), Path(argv[1]), argv[2:]
    if not src.exists():
        print(f"ERROR: input file does not exist: {src}", file=sys.stderr)
        return 1
    if not BUNDLE.is_file():
        print(f"ERROR: shared bundler not found at {BUNDLE}; html-slides needs the html-canvas skill next to it",
              file=sys.stderr)
        return 1
    spec = importlib.util.spec_from_file_location("html_canvas_bundle", BUNDLE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    code = mod.main([str(src), "--out", str(dst), *extra])
    if code and "fonts.bunny.net" in src.read_text(encoding="utf-8", errors="replace"):
        print("hint: this deck links fonts.bunny.net; regenerate it with new-deck.py or pass --allow-remote",
              file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
