#!/usr/bin/env python3
"""Put the PDF and PowerPoint of a deck into the deck, as download buttons.

Run it after render-pdf.cjs and render-pptx.py. Each file goes into the deck as
base64 inside a <script type="application/x-deck-download"> element, between the
markers <!-- deck-downloads:start --> and <!-- deck-downloads:end --> before
</body>. The engine turns each one into a button in the deck view toolbar
(data-view="deck", reference/slide-types.md § Engine Contract) and into a Blob
only when it is clicked, so the download works offline and inside a sandboxed
frame that allows downloads. A data-deck="download:pdf" button on a slide works
in any deck.

A deck hosted next to its files can link them instead (--pdf-url, --pptx-url):
nothing is embedded, the button points at the address.

Size guard: the finished deck may not grow above --max-total (default 14 MiB,
the whole HTML file with everything embedded). Above it the PowerPoint is
skipped first, and said so; a PDF that alone does not fit is refused (exit 1):
link it with --pdf-url, or render it smaller.

File names come from the deck's <title> ("Quarterly review" gives
Quarterly-review.pdf), or from --name.

Usage:
    python3 embed-downloads.py deck.html --pdf deck.pdf [--pptx deck.pptx] [--out send.html]
    python3 embed-downloads.py deck.html --pdf-url deck.pdf --pptx-url deck.pptx
    python3 embed-downloads.py deck.html --remove

Running it again replaces the region, so a refreshed PDF is embedded the same
way. Exit codes: 0 written (a skipped PowerPoint says so on stderr), 1 refused
or a file is missing, 2 wrong usage.
"""
from __future__ import annotations

import argparse
import base64
import html
import re
import sys
from pathlib import Path

START, END = "<!-- deck-downloads:start -->", "<!-- deck-downloads:end -->"
REGION_RE = re.compile(r"\n?" + re.escape(START) + r".*?" + re.escape(END) + r"\n?", re.S)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.I | re.S)
DECK_VIEW_RE = re.compile(r"""\bdata-view\s*=\s*["']?deck\b""", re.I)
MIME = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MIB = 1024 * 1024
DEFAULT_MAX = 14 * MIB


class Refused(Exception):
    pass


def size_arg(text: str) -> int:
    """14MiB, 14M, 500k or plain bytes."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(k|kb|kib|m|mb|mib)?\s*", text, re.I)
    if not m:
        raise argparse.ArgumentTypeError("a size such as 14MiB, 500k or 1048576")
    unit = (m.group(2) or "").lower()
    factor = MIB if unit.startswith("m") else 1024 if unit.startswith("k") else 1
    return int(float(m.group(1)) * factor)


def base_name(doc: str) -> str:
    """The file name stem from the deck's <title>: words joined by hyphens."""
    m = TITLE_RE.search(doc)
    title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""
    stem = re.sub(r"[^\w.]+", "-", title, flags=re.UNICODE).strip("-.")
    return stem[:80] or "deck"


def element(kind: str, file: str, payload: bytes | None = None, href: str | None = None) -> str:
    attrs = 'type="application/x-deck-download" data-kind="%s" data-file="%s" data-mime="%s"' % (
        kind, html.escape(file, quote=True), MIME[kind])
    if href is not None:
        return '<script %s data-href="%s"></script>' % (attrs, html.escape(href, quote=True))
    text = base64.b64encode(payload or b"").decode("ascii")
    lines = "\n".join(text[i:i + 76] for i in range(0, len(text), 76))
    return "<script %s>\n%s\n</script>" % (attrs, lines)


def region(parts: list[str]) -> str:
    return "\n" + START + "\n" + "\n".join(parts) + "\n" + END + "\n"


def splice(doc: str, block: str) -> str:
    doc = REGION_RE.sub("\n", doc, count=1) if START in doc else doc
    if not block:
        return doc
    i = doc.lower().rfind("</body>")
    if i < 0:
        raise Refused("the deck has no </body>")
    return doc[:i].rstrip("\n") + block + doc[i:]


def build(doc: str, args, say=lambda m: print(m, file=sys.stderr)) -> str:
    """The deck with its download region; `say` reports what was skipped."""
    stem = args.name or base_name(doc)
    if args.remove:
        return splice(doc, "")
    wanted = []  # (kind, element text) in button order
    for kind in ("pdf", "pptx"):
        path, url = getattr(args, kind), getattr(args, kind + "_url")
        if path and url:
            raise Refused("give --%s or --%s-url, not both" % (kind, kind))
        if url:
            wanted.append((kind, element(kind, stem + "." + kind, href=url)))
        elif path:
            p = Path(path)
            if not p.is_file():
                raise Refused("%s does not exist" % p)
            wanted.append((kind, element(kind, stem + "." + kind, payload=p.read_bytes())))
    if not wanted:
        raise Refused("nothing to embed: give --pdf, --pptx, --pdf-url or --pptx-url (or --remove)")
    out = splice(doc, region([e for _, e in wanted]))
    total = len(out.encode("utf-8"))
    if total > args.max_total and any(k == "pptx" for k, _ in wanted):
        kept = [(k, e) for k, e in wanted if k != "pptx"]
        say("embed-downloads: the PowerPoint is skipped: with it the deck would be %.1f MiB, above "
            "--max-total %.1f MiB; link it with --pptx-url or raise --max-total" % (total / MIB, args.max_total / MIB))
        if not kept:
            raise Refused("nothing left to embed within --max-total")
        out = splice(doc, region([e for _, e in kept]))
        total = len(out.encode("utf-8"))
    if total > args.max_total:
        raise Refused("the deck would be %.1f MiB, above --max-total %.1f MiB; link the PDF with --pdf-url "
                      "or raise --max-total" % (total / MIB, args.max_total / MIB))
    if not DECK_VIEW_RE.search(doc):
        say("embed-downloads: note: the deck has no data-view=\"deck\", so no toolbar shows the buttons; "
            "a data-deck=\"download:pdf\" button on a slide still works")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Embed a deck's PDF and PowerPoint as download buttons")
    ap.add_argument("deck", help="the deck HTML")
    ap.add_argument("--pdf", help="the PDF to embed (render-pdf.cjs)")
    ap.add_argument("--pptx", help="the PowerPoint to embed (render-pptx.py)")
    ap.add_argument("--pdf-url", dest="pdf_url", help="link a PDF hosted next to the deck instead of embedding it")
    ap.add_argument("--pptx-url", dest="pptx_url", help="link a PowerPoint hosted next to the deck instead")
    ap.add_argument("--name", help="file name stem for the downloads (default: from <title>)")
    ap.add_argument("--max-total", dest="max_total", type=size_arg, default=DEFAULT_MAX,
                    help="largest the finished deck may be (default 14MiB); above it the PowerPoint is skipped, "
                         "then the run is refused")
    ap.add_argument("--remove", action="store_true", help="take the download region out again")
    ap.add_argument("--out", help="write here instead of in place")
    args = ap.parse_args(argv)
    src = Path(args.deck)
    if not src.is_file():
        print("embed-downloads: %s does not exist" % src, file=sys.stderr)
        return 1
    try:
        out = build(src.read_text(encoding="utf-8"), args)
    except Refused as exc:
        print("embed-downloads: refused: %s" % exc, file=sys.stderr)
        return 1
    dst = Path(args.out) if args.out else src
    dst.write_text(out, encoding="utf-8")
    print("embed-downloads: wrote %s (%.1f MiB)" % (dst, len(out.encode("utf-8")) / MIB))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
