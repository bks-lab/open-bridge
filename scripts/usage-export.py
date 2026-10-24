#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The token use of this machine as one stamped file, for the cockpit of another machine.

    usage-export.py --out FILE [--root R] [--days 90] [--host H]

Runs the same scan as the cockpit's overview page (scripts/lib/bridge_cockpit/usage.py) over the Claude Code
transcripts here, Bridges taken from R's infra/instances/, and writes {schema, kind: usage-export, host, at,
...view, rows} atomically. Declared as a workload on the machine; the other cockpit reads it as
`ssh:<host>:<file>` (cockpit.usage.remotes, cockpit.usage.remote_file). It never reads other machines itself,
so no machine reads a chain of others. Only reads transcripts; writes the file and R's usage history.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from bridge_cockpit import usage  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--host", default=None)
    args = ap.parse_args(argv)
    u = usage.Usage(root=args.root.resolve(), host=args.host, remotes=False)
    data = u.export(days=args.days)
    out = args.out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name("." + out.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)
    print(f"usage-export: {data['host']}, {data['range']} days, {data['total']['output']} output tokens, "
          f"{len(data['bridges'])} bridge row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
