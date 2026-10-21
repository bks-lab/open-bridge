#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One writer and checker for the learning loop's state.

A proposal's state lives in three places: the folder its file sits in
(`work/_learning/proposals/`, `accepted/`, `rejected/`), the `status:` in its
own frontmatter, and its rows in `work/_learning/audit-trail.md`. Nothing held
those together while an agent typed the trail by hand. This script is the
mechanical part `/bridge-learn` calls instead; the human decision and its
reason stay exactly where `rules/learning-autonomy.md` puts them.

    python3 scripts/learning-ledger.py fingerprint <id>
    python3 scripts/learning-ledger.py recurrences [--json]
    python3 scripts/learning-ledger.py prior-rejections <target.path> [--json]
    python3 scripts/learning-ledger.py record <id> --to <state> [--reason R] [--until U]
    python3 scripts/learning-ledger.py check [--provenance]

`record` appends the audit-trail row after the human decided and the file was
moved and its status set: the timestamp is the clock, the previous state is
the proposal's last row, and for `implemented` the commit cell is HEAD's short
SHA plus its diffstat (it also stores `implemented_commit` and the recurrence
fingerprint). It refuses when folder or status do not match the transition
yet, when the proposal is already recorded in that state (except a repeated
defer), and for `implemented` when HEAD touches neither the proposal nor its
target. `check` compares folder, frontmatter status and last trail row for
every proposal, and flags unparseable proposal files, one id in two folders,
short or self-transition rows, placeholder timestamps, implemented rows
without a commit and rows without a file; it reports and exits 1, never fixes.

For a proposal with `target.type: skill`, `record --to implemented` also
appends one provenance line (format: skills/bridge-learn/SKILL.md, accept
step 8) to `work/_learning/provenance/<name>.md`, created on first use. The
record is instance data, so it lives under `work/`, never inside the (possibly
CORE) skill folder; `SKILL.md` is never touched. `check --provenance` is the
opt-in cross-check of those lines against the trail's implemented rows, in both
directions.

`fingerprint` stores `recurrence_fingerprint: <target.path>#<id without its
date>` on an implemented proposal. `recurrences` lists implemented proposals
whose target.path comes back after the day the fix landed (its implemented
trail row): a newer proposal on the same path, or a postmortem, audit-history
file or closed task's STATUS.md naming the whole path. A file without a date
in its name is dated by its last commit. Evidence only; it never changes a
status.

`prior-rejections` is step 0 for every proposal writer: rejected proposals on
exactly the same target.path, with their reason, so a new candidate either
cites them in `prior_rejections:` or is dropped. It never blocks a write.

Contract: `scripts/tests/test_learning_ledger.py`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

LEARNING = Path("work") / "_learning"
FOLDERS = {"": "proposals", "accepted": "proposals/accepted", "rejected": "proposals/rejected"}
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


# ---------------------------------------------------------------------------
# Proposal files
# ---------------------------------------------------------------------------


@dataclass
class Proposal:
    path: Path
    folder: str          # "", "accepted" or "rejected"
    data: dict

    @property
    def id(self) -> str:
        return str(self.data.get("id") or self.path.stem)

    @property
    def status(self) -> str:
        return str(self.data.get("status", ""))

    @property
    def target_path(self) -> str:
        return norm_path(str((self.data.get("target") or {}).get("path") or ""))


def norm_path(path: str) -> str:
    """`./skills/x/` and `skills/x` name the same target."""
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/")


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """(frontmatter, rest) for a file opening with a `---` fence, else None."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[3:end].strip("\n"), text[end:]


def read_proposal(path: Path, folder: str) -> Proposal | None:
    parts = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    if parts is None:
        return None
    try:
        data = yaml.safe_load(parts[0]) or {}
    except yaml.YAMLError:
        return None
    return Proposal(path, folder, data if isinstance(data, dict) else {})


def all_proposals(root: Path) -> list[Proposal]:
    found: list[Proposal] = []
    for folder, rel in FOLDERS.items():
        directory = root / LEARNING / rel
        for path in sorted(directory.glob("*.md")):
            prop = read_proposal(path, folder)
            if prop is not None:
                found.append(prop)
    return found


def broken_proposals(root: Path) -> list[Path]:
    """Proposal files whose frontmatter does not parse: every reader skips
    them, so `check` has to name them."""
    broken: list[Path] = []
    for rel in FOLDERS.values():
        for path in sorted((root / LEARNING / rel).glob("*.md")):
            prop = read_proposal(path, "")
            if prop is None or not prop.data:
                broken.append(path)
    return broken


def find_proposal(root: Path, pid: str) -> Proposal | None:
    return next((p for p in all_proposals(root) if p.id == pid or p.path.stem == pid), None)


def set_frontmatter_key(path: Path, key: str, value: str) -> bool:
    """Add or replace one top-level scalar key by text, keeping every other
    line (comments, order, quoting) exactly as written. False if unchanged."""
    text = path.read_text(encoding="utf-8")
    parts = split_frontmatter(text)
    if parts is None:
        return False
    head, rest = parts
    line = f"{key}: {json.dumps(value, ensure_ascii=False)}"
    # the key's own line plus any indented continuation (a folded or block value)
    pattern = re.compile(rf"^{re.escape(key)}:.*(?:\n[ \t]+.*)*", re.M)
    if pattern.search(head):
        new_head = pattern.sub(lambda _match: line, head, count=1)
    else:
        new_head = head + "\n" + line
    if new_head == head:
        return False
    path.write_text("---\n" + new_head + rest, encoding="utf-8")
    return True


def gap_slug(pid: str) -> str:
    return DATE_PREFIX_RE.sub("", pid).lstrip("-") or pid


def fingerprint_for(prop: Proposal) -> str:
    return f"{prop.target_path}#{gap_slug(prop.id)}"


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


def cmd_fingerprint(args) -> int:
    root = Path(args.root)
    prop = find_proposal(root, args.id)
    if prop is None:
        print(f"no proposal {args.id!r} under {root / LEARNING}", file=sys.stderr)
        return 2
    if prop.status != "implemented":
        print(f"{prop.id} is {prop.status or 'without status'}, not implemented; "
              "a fingerprint marks a fix that landed", file=sys.stderr)
        return 2
    set_frontmatter_key(prop.path, "recurrence_fingerprint", fingerprint_for(prop))
    return 0


# ---------------------------------------------------------------------------
# recurrences
# ---------------------------------------------------------------------------


def _fixed_on(prop: Proposal, rows: list["TrailRow"]) -> str:
    """The day the fix landed: its `implemented` trail row, else accepted_at,
    else created. Evidence has to be dated after that day to count."""
    landed = [r for r in rows if r.id == prop.id and r.to_state == "implemented"]
    if landed and TIMESTAMP_RE.match(landed[-1].timestamp):
        return landed[-1].timestamp[:10]
    return str(prop.data.get("accepted_at") or prop.data.get("created") or "")


def _file_date(root: Path, path: Path) -> str:
    """A signal file's date: its name's date prefix, else the day git last
    committed it, else its modification day. Postmortems are named by slug."""
    match = DATE_PREFIX_RE.match(path.name)
    if match:
        return match.group(1)
    committed = _git(root, "log", "-1", "--format=%cs", "--", str(path.relative_to(root)))
    if committed:
        return committed
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def _names_path(text: str, target: str) -> bool:
    """The whole path, not a substring: `x/skills/a/SKILL.md.bak` is not
    `skills/a/SKILL.md`."""
    return re.search(rf"(?<![\w./-]){re.escape(target)}(?![\w/-]|\.\w)", text) is not None


def build_recurrences(root: Path) -> list[dict]:
    proposals = all_proposals(root)
    rows = read_trail(root)
    files: list[Path] = []
    for sub in ("postmortems", "audit-history"):
        files += [p for p in sorted((root / LEARNING / sub).rglob("*")) if p.is_file()]
    files += sorted(root.glob("work/done/*/*/STATUS.md"))
    signals = [(_file_date(root, path), str(path.relative_to(root)),
                path.read_text(encoding="utf-8", errors="replace")) for path in files]

    found: list[dict] = []
    for prop in proposals:
        fingerprint = prop.data.get("recurrence_fingerprint")
        if prop.status != "implemented" or not fingerprint or not prop.target_path:
            continue
        since = _fixed_on(prop, rows)
        hits = [(str(other.data.get("created") or ""), str(other.path.relative_to(root)))
                for other in proposals
                if other.path != prop.path and other.target_path == prop.target_path]
        hits += [(date, rel) for date, rel, text in signals
                 if _names_path(text, prop.target_path)]
        hits = sorted(h for h in hits if h[0] > since)
        if hits:
            found.append({"id": prop.id, "fingerprint": fingerprint,
                          "recurred": hits[0][0], "evidence": hits[0][1]})
    return found


def cmd_recurrences(args) -> int:
    found = build_recurrences(Path(args.root))
    if args.json:
        print(json.dumps(found, indent=2))
        return 0
    if not found:
        print("no implemented proposal has recurred")
    for item in found:
        print(f"{item['id']}  recurred: {item['recurred']}  ({item['evidence']})")
    return 0


# ---------------------------------------------------------------------------
# audit-trail.md rows
# ---------------------------------------------------------------------------


@dataclass
class TrailRow:
    lineno: int
    timestamp: str
    id: str
    transition: str
    reason: str
    commit: str

    @property
    def from_state(self) -> str:
        return re.split(r"→|->", self.transition)[0].strip()

    @property
    def to_state(self) -> str:
        """`pending → deferred (phase-3)` → `deferred`."""
        after = re.split(r"→|->", self.transition)[-1].strip()
        return after.split("(")[0].strip()


def trail_path(root: Path) -> Path:
    return root / LEARNING / "audit-trail.md"


def parse_trail(root: Path) -> tuple[list[TrailRow], list[int]]:
    """(rows, line numbers of table rows too short to be a transition)."""
    path = trail_path(root)
    if not path.is_file():
        return [], []
    rows: list[TrailRow] = []
    malformed: list[int] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in ("Timestamp", "") or set(cells[0]) <= {"-", ":"}:
            continue
        if len(cells) < 5:
            malformed.append(lineno)
            continue
        timestamp, pid, transition, *middle, commit = cells
        reason = "|".join(middle).strip().strip('"')
        rows.append(TrailRow(lineno, timestamp, pid, transition, reason, commit))
    return rows, malformed


def read_trail(root: Path) -> list[TrailRow]:
    return parse_trail(root)[0]


# ---------------------------------------------------------------------------
# prior-rejections
# ---------------------------------------------------------------------------


def build_prior_rejections(root: Path, target_path: str) -> list[dict]:
    """Rejected proposals on exactly this target.path, oldest first. Matching
    on task_slug or topic would cite unrelated proposals, so it never does."""
    trail = read_trail(root)
    target_path = norm_path(target_path)
    found: list[dict] = []
    for prop in all_proposals(root):
        if prop.folder != "rejected" and prop.status != "rejected":
            continue
        if prop.target_path != target_path:
            continue
        reason = str(prop.data.get("reject_reason") or "")
        if not reason:
            rows = [r for r in trail if r.id == prop.id and r.to_state == "rejected"]
            reason = rows[-1].reason if rows else ""
        found.append({"id": prop.id, "reason": reason})
    return found


def cmd_prior_rejections(args) -> int:
    found = build_prior_rejections(Path(args.root), args.target_path)
    if args.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))
        return 0
    if not found:
        print(f"no rejected proposal targets {args.target_path}")
    for item in found:
        print(f"{item['id']}  reason: {item['reason'] or '(none recorded)'}")
    return 0


# ---------------------------------------------------------------------------
# record / check
# ---------------------------------------------------------------------------

# Which statuses may live in which folder (review-workflow.md § File move).
STATUSES_BY_FOLDER = {
    "": {"pending", "deferred", "superseded"},
    "accepted": {"accepted", "implemented"},
    "rejected": {"rejected"},
}
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}\b")


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args],
                                capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _head_commit_cell(root: Path) -> str | None:
    """`<short sha> (<n> files, +<a>/-<d>)` for HEAD, measured by git."""
    sha = _git(root, "rev-parse", "--short", "HEAD")
    if not sha:
        return None
    stat = _git(root, "show", "--shortstat", "--format=", "HEAD") or ""
    files = re.search(r"(\d+) files? changed", stat)
    plus = re.search(r"(\d+) insertions?", stat)
    minus = re.search(r"(\d+) deletions?", stat)
    summary = (f"{files.group(1) if files else 0} files, "
               f"+{plus.group(1) if plus else 0}/-{minus.group(1) if minus else 0}")
    return f"{sha} ({summary})"


def _head_touches(root: Path, paths: list[Path]) -> bool:
    top = _git(root, "rev-parse", "--show-toplevel")
    changed = _git(root, "show", "--name-only", "--format=", "HEAD")
    if not top or changed is None:
        return False
    names = {line.strip() for line in changed.splitlines() if line.strip()}
    for path in paths:
        try:
            rel = path.resolve().relative_to(Path(top).resolve())
        except ValueError:
            continue
        if str(rel) in names:
            return True
    return False


def _body_summary(prop: Proposal) -> str:
    """First prose line of the proposal body, when nobody typed a reason."""
    parts = split_frontmatter(prop.path.read_text(encoding="utf-8", errors="replace"))
    body = parts[1].split("\n", 2)[-1] if parts else ""
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "---", "```", "|", ">")):
            return line[:120]
    return ""


def folder_problem(prop: Proposal) -> str | None:
    allowed = STATUSES_BY_FOLDER[prop.folder]
    if prop.status in allowed:
        return None
    where = f"proposals/{prop.folder}/" if prop.folder else "proposals/"
    return f"folder and status disagree: status {prop.status or '(none)'} in {where}"


PROVENANCE_HEADER = """# Provenance

One line per accepted proposal that changed the skill of this name, appended by
`scripts/learning-ledger.py record <id> --to implemented`, never by hand. The
line format is defined in skills/bridge-learn/SKILL.md, accept step 8.

"""
PROVENANCE_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · (\S+) · (.*)$")


def provenance_file(root: Path, target_path: str) -> Path | None:
    """`work/_learning/provenance/<name>.md` for a skill target, else None."""
    parts = Path(target_path).parts
    if len(parts) < 2 or parts[0] != "skills":
        return None
    return root / LEARNING / "provenance" / f"{parts[1]}.md"


def append_provenance(root: Path, prop: Proposal, why: str) -> Path | None:
    if (prop.data.get("target") or {}).get("type") != "skill":
        return None
    record = provenance_file(root, prop.target_path)
    if record is None:
        return None
    record.parent.mkdir(parents=True, exist_ok=True)
    text = record.read_text(encoding="utf-8") if record.is_file() else PROVENANCE_HEADER
    if not text.endswith("\n"):
        text += "\n"
    line = f"- {datetime.now().strftime('%Y-%m-%d')} · {prop.id} · {why or '(no reason recorded)'}"
    record.write_text(text + line + "\n", encoding="utf-8")
    return record


def cmd_record(args) -> int:
    root = Path(args.root)
    prop = find_proposal(root, args.id)
    if prop is None:
        print(f"no proposal {args.id!r} under {root / LEARNING}", file=sys.stderr)
        return 2
    if prop.status != args.to:
        print(f"{prop.id} has status {prop.status or '(none)'}, not {args.to}: set the "
              "frontmatter first, then record what happened", file=sys.stderr)
        return 2
    problem = folder_problem(prop)
    if problem:
        print(f"{prop.id}: {problem}; move the file first (git mv)", file=sys.stderr)
        return 2
    trail = trail_path(root)
    if not trail.is_file():
        print(f"{trail} is missing", file=sys.stderr)
        return 2

    earlier = [r for r in read_trail(root) if r.id == prop.id]
    source = earlier[-1].to_state if earlier else "pending"
    if source == args.to and args.to != "deferred":
        print(f"{prop.id} is already recorded as {args.to}; a second row would claim a "
              "transition that did not happen", file=sys.stderr)
        return 2
    transition = f"{source} → {args.to}"
    if args.to == "deferred" and args.until:
        transition += f" ({args.until})"

    commit = "—"
    if args.to == "implemented":
        cell = _head_commit_cell(root)
        if cell is None:
            print("implemented needs the commit that landed it, and git has no HEAD here",
                  file=sys.stderr)
            return 2
        if not _head_touches(root, [prop.path, root / prop.target_path]):
            print(f"HEAD does not touch {prop.path.relative_to(root)} or {prop.target_path}: "
                  "commit the change first, then record it", file=sys.stderr)
            return 2
        commit = cell
        set_frontmatter_key(prop.path, "implemented_commit", cell.split()[0])
        set_frontmatter_key(prop.path, "recurrence_fingerprint", fingerprint_for(prop))

    reason = (args.reason or "").replace("\\|", "/").replace("|", "/").replace("\n", " ").strip()
    if args.to == "implemented":
        accepted = [r for r in earlier if r.to_state == "accepted"]
        why = reason or (accepted[-1].reason if accepted else "") or _body_summary(prop)
        append_provenance(root, prop, why)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = trail.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    trail.write_text(text + f"| {timestamp} | {prop.id} | {transition} | {reason} | {commit} |\n",
                     encoding="utf-8")
    return 0


def build_check(root: Path) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    everything = all_proposals(root)
    proposals = {p.id: p for p in everything}
    rows, malformed = parse_trail(root)

    for path in broken_proposals(root):
        problems.append((path.stem, f"{path.relative_to(root)}: frontmatter does not parse, "
                                    "every reader skips this file"))
    seen: dict[str, list[str]] = {}
    for prop in everything:
        seen.setdefault(prop.id, []).append(prop.folder or "proposals")
    for pid, folders in sorted(seen.items()):
        if len(folders) > 1:
            problems.append((pid, f"exists in more than one folder: {', '.join(folders)}"))
    for lineno in malformed:
        problems.append(("audit-trail", f"audit-trail.md:{lineno} has fewer than five cells"))

    for pid, prop in sorted(proposals.items()):
        problem = folder_problem(prop)
        if problem:
            problems.append((pid, problem))
        own = [r for r in rows if r.id == pid]
        if own and own[-1].to_state != prop.status:
            problems.append((pid, f"trail says {own[-1].to_state}, frontmatter says "
                                  f"{prop.status or '(none)'}"))
        if not own and prop.status not in ("", "pending"):
            problems.append((pid, f"status {prop.status} but no audit-trail row"))

    for row in rows:
        if row.from_state == row.to_state and row.to_state != "deferred":
            problems.append((row.id, f"audit-trail.md:{row.lineno} records "
                                     f"{row.transition}, which is no transition"))
        if not TIMESTAMP_RE.match(row.timestamp):
            problems.append((row.id, f"audit-trail.md:{row.lineno} timestamp "
                                     f"{row.timestamp!r} is not a measured YYYY-MM-DD HH:MM"))
        if row.to_state == "implemented" and not COMMIT_RE.match(row.commit):
            problems.append((row.id, f"audit-trail.md:{row.lineno} implemented without a "
                                     "commit hash"))
        if row.id not in proposals:
            problems.append((row.id, f"audit-trail.md:{row.lineno} has no proposal file "
                                     "in any folder"))
    return problems


def build_provenance_check(root: Path) -> list[tuple[str, str]]:
    """Implemented skill proposals in the trail against provenance lines, both
    ways. Opt-in: the convention starts at zero adoption."""
    problems: list[tuple[str, str]] = []
    proposals = {p.id: p for p in all_proposals(root)}
    implemented = {r.id for r in read_trail(root) if r.to_state == "implemented"}

    recorded: dict[str, Path] = {}
    for record in sorted((root / LEARNING / "provenance").glob("*.md")):
        for line in record.read_text(encoding="utf-8").splitlines():
            match = PROVENANCE_LINE_RE.match(line)
            if match:
                recorded[match.group(2)] = record

    for pid in sorted(implemented):
        prop = proposals.get(pid)
        if prop is None or (prop.data.get("target") or {}).get("type") != "skill":
            continue
        expected = provenance_file(root, prop.target_path)
        if expected is not None and recorded.get(pid) != expected:
            problems.append((pid, f"implemented skill proposal has no line in "
                                  f"{expected.relative_to(root)} (provenance)"))
    for pid, record in sorted(recorded.items()):
        if pid not in implemented:
            problems.append((pid, f"{record.relative_to(root)} names it, but the audit "
                                  "trail has no implemented row (provenance)"))
    return problems


def cmd_check(args) -> int:
    problems = build_check(Path(args.root))
    if args.provenance:
        problems += build_provenance_check(Path(args.root))
    for pid, problem in problems:
        print(f"{pid}: {problem}")
    if problems:
        print(f"learning-ledger check: {len(problems)} finding(s)")
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="learning-ledger",
        description="Write and check the learning loop's proposal state.",
    )
    parser.add_argument("--root", default=".", help="Bridge repo root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    fp = sub.add_parser("fingerprint", help="store recurrence_fingerprint on an implemented proposal")
    fp.add_argument("id")
    fp.set_defaults(func=cmd_fingerprint)

    rc = sub.add_parser("recurrences", help="implemented proposals whose target came back")
    rc.add_argument("--json", action="store_true")
    rc.set_defaults(func=cmd_recurrences)

    pr = sub.add_parser("prior-rejections",
                        help="rejected proposals on the same target.path, before writing a new one")
    pr.add_argument("target_path")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_prior_rejections)

    re_ = sub.add_parser("record", help="append one audit-trail row, measured from git")
    re_.add_argument("id")
    re_.add_argument("--to", required=True,
                     choices=["accepted", "implemented", "rejected", "deferred", "superseded"])
    re_.add_argument("--reason", default="", help="the human's reason, passed through as typed")
    re_.add_argument("--until", default="", help="for --to deferred: date or marker")
    re_.set_defaults(func=cmd_record)

    ch = sub.add_parser("check", help="folder, status and trail agree for every proposal")
    ch.add_argument("--provenance", action="store_true",
                    help="also cross-check work/_learning/provenance/*.md (opt-in)")
    ch.set_defaults(func=cmd_check)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
