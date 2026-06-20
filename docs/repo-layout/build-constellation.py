#!/usr/bin/env python3
"""build-constellation.py — generate the network.html data block from regions.yaml.

Single source of truth for the constellation ("Network v7") is the
`constellation:` section of docs/repo-layout/regions.yaml (meta + hub + nodes
+ edges + flows). This script renders that into the JS data arrays
(RING_RADIUS / SECTORS / NODES / HUB_NODE / FILTERED / EDGES / FLOWS) and
injects them into network.html between the CONSTELLATION-DATA markers.

Run after editing regions.yaml:
    python3 docs/repo-layout/build-constellation.py

Idempotent. On the first run (no markers yet) it replaces the legacy
hand-authored `const RING_RADIUS … const FLOWS = {…};` span and wraps the
result in markers; afterwards it only replaces between the markers.

Wire into your deploy pipeline (e.g. a post-pull hook) so the generated HTML
never drifts from regions.yaml by hand.again.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

HERE = Path(__file__).resolve().parent
REGIONS = HERE / "regions.yaml"
HTML = HERE / "network.html"

START = "// <<<CONSTELLATION-DATA"
END = "// <<<END CONSTELLATION-DATA>>>"


def js(obj) -> str:
    """JSON is valid JS object/array syntax; keep UTF-8 (ä ö ü € …) literal."""
    return json.dumps(obj, ensure_ascii=False)


def render(c: dict) -> str:
    meta = c["meta"]
    out = [
        f"{START} — GENERATED from docs/repo-layout/regions.yaml `constellation:` "
        f"by build-constellation.py. DO NOT EDIT BY HAND; edit regions.yaml + rerun.>>>",
        f"const RING_RADIUS = {js(meta['ring_radius'])};",
        "",
        "const SECTORS = {",
    ]
    for k, v in meta["sectors"].items():
        out.append(f"  {k}: {js(v)},")
    out += ["};", "", "const NODES = ["]
    for n in c["nodes"]:
        out.append("  " + js(n) + ",")
    out += [
        "];",
        "",
        f"const HUB_NODE = {js(c['hub'])};",
        "const FILTERED = NODES;",
        "",
        "const EDGES = [",
    ]
    for e in c["edges"]:
        out.append("  " + js(e) + ",")
    out += ["];", "", "const FLOWS = {"]
    for k, v in c["flows"].items():
        out.append(f"  {js(k)}: {js(v)},")
    out += ["};", END]
    return "\n".join(out)


def main() -> int:
    if not HTML.exists():
        print("network.html not found — render it via /bridge-explorer first; "
              "this script only refreshes the data block of an existing render.")
        sys.exit(1)
    data = yaml.safe_load(REGIONS.read_text(encoding="utf-8"))
    if "constellation" not in data:
        sys.exit("regions.yaml has no `constellation:` section")
    c = data["constellation"]
    block = render(c)
    html = HTML.read_text(encoding="utf-8")

    if START in html and END in html:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END),
                     lambda _m: block, html, flags=re.S)
        mode = "marker-replace"
    else:
        # First run: swap the legacy hand-authored data span for the marker block.
        pat = re.compile(r"const RING_RADIUS = .*?\nconst FLOWS = \{.*?\n\};", re.S)
        if not pat.search(html):
            sys.exit("Could not find legacy data span and no markers present — aborting.")
        new = pat.sub(lambda _m: block, html, count=1)
        mode = "first-run (legacy span replaced + markers inserted)"

    # Bump version badge whenever generated.
    new = new.replace("Network v6", "Network v7")

    if new == html:
        print("network.html already up to date.")
        return 0
    HTML.write_text(new, encoding="utf-8")
    print(f"network.html regenerated [{mode}] — "
          f"{len(c['nodes'])} nodes, {len(c['edges'])} edges, {len(c['flows'])} flows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
