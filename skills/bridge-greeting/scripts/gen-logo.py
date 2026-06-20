#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate an ANSI-Shadow terminal logo for a Bridge instance.

Renders one or two words into block-letter art (figlet "ansi_shadow" font)
and emits it with fastfetch ``$1``/``$2`` colour placeholders so the colours
stay theme-driven (set at render time via ``--logo-color-1/2``).

Why this exists: figlet silently drops non-ASCII glyphs, so a naive umlaut
("Ü") would be lost. This script renders the ASCII skeleton and re-adds a
diaeresis row above a chosen letter.

Usage:
    uv run --with pyfiglet python gen-logo.py --top ACME --bottom CORP > acme.txt
    uv run --with pyfiglet python gen-logo.py --top ACME --umlaut 1 > acme.txt
        # --umlaut N puts a diaeresis over the N-th letter (0-based) of --top

Colour split mirrors a two-word logo: top word alternates $1/$2 per letter,
bottom word is all $2. Override with --top-colors / --bottom-color.
"""
import argparse
import sys


def block(fig, ch):
    raw = [l for l in fig.renderText(ch).split("\n") if l.strip("")][:6]
    w = max((len(l) for l in raw), default=0)
    return [l.ljust(w) for l in raw], w


def diaeresis(width):
    marks = list(" " * width)
    for c in (1, 2, width - 3, width - 2):
        if 0 <= c < width:
            marks[c] = "▀"
    return "".join(marks)


def render_word(fig, word, colors):
    """Return (lines, widths) — each row is colour-split per letter."""
    blocks = [block(fig, c) for c in word]
    rows = []
    for i in range(6):
        row = ""
        for j, (blk, _) in enumerate(blocks):
            row += f"${colors[j % len(colors)]}" + blk[i]
        rows.append(row)
    return rows, [w for _, w in blocks]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", required=True)
    ap.add_argument("--bottom", default="")
    ap.add_argument("--umlaut", type=int, default=-1,
                    help="0-based index of a --top letter to mark with ¨")
    ap.add_argument("--top-colors", default="1,2",
                    help="comma list of colour ids cycled per top letter")
    ap.add_argument("--bottom-color", default="2")
    args = ap.parse_args()

    try:
        from pyfiglet import Figlet
    except ImportError:
        sys.exit("pyfiglet missing — run via: uv run --with pyfiglet python gen-logo.py ...")

    fig = Figlet(font="ansi_shadow")
    top_colors = args.top_colors.split(",")

    out = []
    top_rows, widths = render_word(fig, args.top, top_colors)

    if 0 <= args.umlaut < len(args.top):
        # build an umlaut row: blanks for every letter, diaeresis over target
        row = ""
        for j, w in enumerate(widths):
            cid = top_colors[j % len(top_colors)]
            seg = diaeresis(w) if j == args.umlaut else " " * w
            row += f"${cid}" + seg
        out.append(row)

    out.extend(top_rows)

    if args.bottom:
        bottom_rows, _ = render_word(fig, args.bottom, [args.bottom_color])
        out.extend(bottom_rows)

    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
