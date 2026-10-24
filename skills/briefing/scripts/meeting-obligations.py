#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Meeting obligations, derived from the artifact instead of a declared status field.

Step 5b of the briefing asks: which captured meeting still owes a wiki protocol?
Answering that from the `wiki.status:` field in a meeting's summary frontmatter
fails in both directions, because the field is written by hand: meetings without
frontmatter are invisible, a value the rule does not know (`draft`) falls through,
and meetings whose protocol was written long ago keep claiming `pending`.

This script asks the wiki instead. For every meeting folder that belongs to a
declared series (`workflow/meetings/<id>.yaml`), it checks whether the protocol
file exists in the series' wiki clone. The frontmatter is consulted only for a
deliberate opt-out (`n/a`, `skipped`), never as proof of completion. No path,
series or repository name is hardcoded here.

Usage:
    python3 skills/briefing/scripts/meeting-obligations.py [--json] [--all] [--root DIR]

Exit code is 0 when nothing is owed, 1 when at least one series meeting has no
protocol. `--all` also lists the fulfilled meetings.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys

DATE = r"\d{4}-\d{2}-\d{2}"
# Only these two are a decision. `done` is a claim and gets verified like any other.
OPT_OUTS = {"n/a", "skipped"}
SERIES_DIR = "workflow/meetings"
OPEN = {"open", "open_frontmatter_claims_done", "open_without_series"}


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def load_config(root: pathlib.Path) -> dict:
    """`bridge-config.yaml`, or {} on a fresh clone: every key read here has a default."""
    import yaml

    path = root / "bridge-config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_series(root: pathlib.Path) -> tuple[dict, list[str]]:
    """Every declared meeting series, keyed by id.

    `_`-prefixed files are the CORE template and schema and are skipped, per the
    cluster-wrapper discovery rule. The wiki target is read from `outputs.wiki`.
    """
    import yaml

    folder = root / SERIES_DIR
    if not folder.is_dir():
        return {}, []
    series, warnings = {}, []
    for path in sorted(folder.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as error:  # noqa: BLE001 - one broken file must not blind the rest
            warnings.append(f"{path.name}: unreadable ({error.__class__.__name__})")
            continue
        series[data.get("id") or path.stem] = data
    return series, warnings


def wiki_target(series: dict) -> dict:
    return ((series.get("outputs") or {}).get("wiki") or {})


def frontmatter(path: pathlib.Path) -> dict:
    """The leading YAML block. A file without one yields {}, not an error."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"\A---\s*$(.*?)^---\s*$", text, re.S | re.M)
    if not match:
        return {}
    import yaml

    try:
        data = yaml.safe_load(match.group(1)) or {}
    except Exception:  # noqa: BLE001 - malformed frontmatter reads as none
        return {}
    return data if isinstance(data, dict) else {}


def series_pattern(series: dict) -> re.Pattern | None:
    """`folder_match` wins; otherwise derive a prefix match from `folder_pattern`.

    Folder names carry free suffixes (`{date}-weekly-planning-2`), so an exact
    match would miss most of them. A series whose folders diverge more than a
    prefix allows sets `folder_match`.
    """
    raw = series.get("folder_match")
    if raw:
        return re.compile(raw)
    pattern = series.get("folder_pattern")
    if not pattern:
        return None
    parts = [re.escape(p) for p in pattern.split("{date}")]
    return re.compile("^" + f"(?P<date>{DATE})".join(parts))


def wiki_root(series: dict, config: dict) -> pathlib.Path | None:
    """The local clone of the series' wiki: `local_path`, else found under projects_root."""
    wiki = wiki_target(series)
    explicit = wiki.get("local_path")
    if explicit:
        # A declared clone that is not there is uncheckable, not "every protocol missing".
        path = pathlib.Path(os.path.expanduser(str(explicit)))
        return path if path.is_dir() else None
    repo = wiki.get("repo")
    if not repo:
        return None
    base = pathlib.Path(os.path.expanduser(str(
        (config.get("identity") or {}).get("projects_root") or "~/Developer")))
    org, _, name = repo.partition("/")
    # <projects_root>/<org>/<repo> first, then the flat form, then one level down.
    candidates = [base / org / name, base / name]
    if base.is_dir():
        candidates += [p / name for p in base.iterdir() if p.is_dir()]
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return None


def collect(root: pathlib.Path, config: dict) -> tuple[list[dict], list[str]]:
    meetings = (config.get("work") or {}).get("meetings") or {}
    home = root / meetings.get("home_dir", "work/tasks/_meetings")
    summary_name = meetings.get("summary_file", "summary.md")
    obligations = meetings.get("tracked_obligations") or {}
    scopes = set(((obligations.get("wiki_protocol") or {}).get("required_for_scopes")) or [])

    series, warnings = load_series(root)
    if not home.is_dir():
        return [], warnings

    compiled = []
    for name, entry in series.items():
        pattern = series_pattern(entry)
        if not pattern:
            warnings.append(f"series {name}: neither folder_match nor folder_pattern")
            continue
        wroot = wiki_root(entry, config)
        if not wroot:
            warnings.append(f"series {name}: no local clone of its wiki found")
        compiled.append((name, entry, pattern, wroot))

    today = datetime.date.today().isoformat()
    results = []
    for folder in sorted(p for p in home.iterdir() if p.is_dir()):
        fm = frontmatter(folder / summary_name)
        wiki_fm = fm.get("wiki") if isinstance(fm.get("wiki"), dict) else {}
        declared = str(wiki_fm.get("status") or "").strip().lower()

        def row(series_name, state, target=None):
            return dict(folder=folder.name, series=series_name, state=state,
                        declared=declared or "(none)", target=target)

        matched = False
        for name, entry, pattern, wroot in compiled:
            hit = pattern.match(folder.name)
            if not hit:
                continue
            matched = True
            date = hit.groupdict().get("date") or folder.name[:10]
            if date > today:
                # A skeleton for a meeting that has not happened yet owes nothing;
                # the obligation starts on the day itself.
                results.append(row(name, "upcoming"))
            elif scopes and str(fm.get("scope") or fm.get("context") or "").strip() not in scopes | {""}:
                # An explicit scope outside the required set opts the meeting out.
                results.append(row(name, "out_of_scope"))
            elif declared in OPT_OUTS:
                results.append(row(name, "opted_out"))
            elif not wroot:
                results.append(row(name, "uncheckable"))
            else:
                wiki = wiki_target(entry)
                target = wroot / wiki.get("dir", "") / wiki.get("file_pattern", "{date}.md").format(date=date)
                exists = target.exists()
                state = "done" if exists else "open"
                if exists and declared in {"pending", "draft", "backlog"}:
                    state = "done_frontmatter_stale"
                if not exists and declared == "done":
                    state = "open_frontmatter_claims_done"
                results.append(row(name, state, str(target.relative_to(wroot))))
            break

        if not matched and declared == "pending":
            # Meetings outside any series keep the declared-field behaviour.
            results.append(row(None, "open_without_series"))

    return results, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--all", action="store_true", help="also list the fulfilled meetings")
    ap.add_argument("--root", type=pathlib.Path, default=None, help="Bridge root (default: this repo)")
    args = ap.parse_args(argv)

    root = args.root or repo_root()
    results, warnings = collect(root, load_config(root))
    open_rows = [r for r in results if r["state"] in OPEN]
    # Two classes, kept apart on purpose: checked against the wiki, and only declared.
    # One list would drown the checked ones in old declarations.
    checked = [r for r in open_rows if r["state"] != "open_without_series"]
    declared_only = [r for r in open_rows if r["state"] == "open_without_series"]
    stale = [r for r in results if r["state"] == "done_frontmatter_stale"]

    if args.json:
        print(json.dumps(dict(open=open_rows, stale=stale, all=results, warnings=warnings),
                         ensure_ascii=False, indent=2))
        return 1 if checked else 0

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    if checked:
        print(f"Wiki protocol missing ({len(checked)}), checked in the wiki:")
        for r in checked:
            note = "  [frontmatter says done]" if r["state"] == "open_frontmatter_claims_done" else ""
            print(f"  - {r['folder']}  ->  {r['target'] or 'no target resolvable'}{note}")
    else:
        print("Wiki protocols of the declared series: nothing owed.")

    if declared_only:
        names = ", ".join(r["folder"] for r in declared_only[:4])
        rest = f", and {len(declared_only) - 4} more" if len(declared_only) > 4 else ""
        print(f"\nOutside any series, open only by their own frontmatter ({len(declared_only)}): {names}{rest}")

    if stale:
        print(f"\nFrontmatter lags behind ({len(stale)}), the protocol exists:")
        for r in stale:
            print(f"  - {r['folder']}  (wiki.status: {r['declared']})")

    if args.all:
        print("\nEvery assessed folder:")
        for r in results:
            print(f"  {r['state']:30} {r['folder']}")

    return 1 if checked else 0


if __name__ == "__main__":
    sys.exit(main())
