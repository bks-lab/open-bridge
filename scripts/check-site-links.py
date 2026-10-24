#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Internal links on the docs/ site have to lead somewhere, and somewhere styled.

Two failures this catches, both of which shipped:

A relative link to a `.md` file. `docs/.nojekyll` is set, so GitHub Pages does
not render markdown, it serves the file. A reader clicking such a link gets raw
markdown with its YAML frontmatter, no stylesheet and no navigation, which looks
like the site broke. Eight of these were live, seven on one page, while every
other page linked the same documents as GitHub blob URLs. Deep links into repo
documents go to GitHub; only `.html` is linked relatively.

A link to a file that is not there at all.

Anchors are checked against ids in the markup AND against `id:"..."` in page
data, because two pages build their sections at runtime from a JS array, and
against the same in any local script a page loads (`<script src="assets/...">`),
because that array now lives in one shared file. A `<base href>` is not a link.
A check that cries wolf on a working link gets ignored, so it stays conservative.

Run: python3 scripts/check-site-links.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

HREF = re.compile(r'href="([^"]+)"')
BASE = re.compile(r'<base\s[^>]*$')
SCRIPT_SRC = re.compile(r'<script\b[^>]*\ssrc="([^":]+\.js)"')
STATIC_ID = re.compile(r'\sid="([^"]+)"')
DATA_ID = re.compile(r'["\']?id["\']?\s*:\s*["\']([A-Za-z0-9_-]+)["\']')
# hrefs assembled in JavaScript are not links, they are code
TEMPLATED = ("'+", '"+', "${", "+ ", " +")


def ids(text: str, docs: Path | None = None) -> set[str]:
    found = set(STATIC_ID.findall(text)) | set(DATA_ID.findall(text))
    for src in SCRIPT_SRC.findall(text) if docs else ():
        script = docs / src
        if script.is_file():
            found |= set(DATA_ID.findall(script.read_text(encoding="utf-8")))
    return found


def main() -> int:
    pages = sorted(p for p in DOCS.glob("*.html") if not p.name.startswith("_"))
    if not pages:
        print("check-site-links: no pages in docs/", file=sys.stderr)
        return 1

    text = {p.name: p.read_text(encoding="utf-8") for p in pages}
    anchors = {name: ids(t, DOCS) for name, t in text.items()}

    problems: list[str] = []
    checked = 0
    for name, body in text.items():
        for m in HREF.finditer(body):
            href = m.group(1)
            if any(t in href for t in TEMPLATED):
                continue
            if BASE.search(body[max(0, m.start() - 200): m.start()]):
                continue
            if href.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:", "#/")):
                continue
            line = body[: m.start()].count("\n") + 1
            checked += 1
            path, _, frag = href.partition("#")
            if not path:
                if frag and frag not in anchors[name]:
                    problems.append(f"{name}:{line}  anchor #{frag} exists nowhere on the page")
                continue
            if path.endswith(".md"):
                problems.append(
                    f"{name}:{line}  relative link to {path}: .nojekyll means Pages serves "
                    f"that raw. Link it as https://github.com/bks-lab/open-bridge/blob/main/docs/{path}"
                )
                continue
            target = DOCS / path
            if not target.exists():
                problems.append(f"{name}:{line}  link to a file that is not there: {href}")
            elif frag and path.endswith(".html") and frag not in anchors.get(path, set()):
                problems.append(f"{name}:{line}  anchor #{frag} exists nowhere in {path}")

    if problems:
        print(f"{len(problems)} broken internal link(s):\n", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    print(f"check-site-links: {checked} internal links across {len(pages)} pages all resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
