#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""check-kernel.py: hold kernel/manifest.yaml to the tree it describes.

The kernel is everything a session reads before its first answer, plus the
files that define that set. `kernel/manifest.yaml` names each piece once: where
it lives and at which tier, when it is read, which file links or instructs it,
and whether a sub-agent sees it. The specification is docs/kernel.md. This
script checks every promise in it against the sources that decide them:

  where     the file exists (or stays absent), the scope router puts it at the
            tier the manifest says, a CORE checkout holds no instance file, and
            kernel/ holds nothing the manifest does not describe
  when      every `@`-import and every item measure-context.py counts as
            always-on has an entry, every always-on entry is measured, and no
            file read at session start lies in a folder docs/data-model.yaml
            says is read only when named
  how       each `via:` file exists and names what it links: an `@`-line for an
            import, the path or command for the rest
  who       an import and a listing reach sub-agents; Phase 0/1 reads never do

A contradiction the project knows about is not hidden: the entry carries a
`debt:` with a reason and an `until`, which this script prints on every run. A
debt whose contradiction is gone is itself a finding, so the list only shrinks.

Usage:
  python3 scripts/check-kernel.py            # report; exit 1 on a finding
  python3 scripts/check-kernel.py --quiet    # findings only
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import os
import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

HERE = Path(__file__).resolve().parent
MANIFEST = "kernel/manifest.yaml"
USER_BUDGET = "context-budget.user.yaml"

SUBJECTS = ("path", "glob", "command", "harness")
KEYS = set(SUBJECTS) | {"tier", "role", "read", "via", "reaches", "optional", "expect",
                        "exclude", "generated_by", "source", "debt", "note"}
TIERS = {"core", "org", "personal", "user", "mixed"}
READS = {"import", "harness", "start", "command", "named", "tool"}
ALWAYS_ON = {"import", "harness", "start", "command"}
PHASE_READS = {"start", "command"}
REACHES = {"session", "subagent"}
DEBT_KINDS = {"placement", "unmeasured", "uninstructed"}
HARNESS = "harness"


@dataclass
class Context:
    root: Path
    entries: list[dict]
    meter: dict[str, str]                 # always-on key -> source, as measure-context.py sees it
    instance_declared: set[str]           # keys the instance caps in context-budget.user.yaml
    imports: set[str]                     # every file an @-line reaches
    families: list[dict]                  # docs/data-model.yaml rows (path, read)
    tier_of: Callable[[str], str]         # the scope router
    kernel_files: list[str]               # every file under kernel/
    core_checkout: bool                   # no bridge-config.yaml: the CORE repo itself


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    debts: list[str] = field(default_factory=list)


# ------------------------------------------------------------- helpers --

def _subject(entry: dict) -> tuple[str, str] | None:
    present = [k for k in SUBJECTS if k in entry]
    return (present[0], str(entry[present[0]])) if len(present) == 1 else None


def _meter_key(kind: str, value: str) -> str:
    return f"cmd:{value}" if kind == "command" else value


def _glob_match(pattern: str, key: str) -> bool:
    """Segment-wise: `a/*.md` matches `a/x.md`, never `a/b/x.md`."""
    pat, parts = pattern.split("/"), key.split("/")
    return len(pat) == len(parts) and all(fnmatch.fnmatchcase(p, q) for p, q in zip(parts, pat))


def _covers(entry: dict, key: str) -> bool:
    subject = _subject(entry)
    if subject is None:
        return False
    kind, value = subject
    if kind == "glob":
        return _glob_match(value, key) and key not in (entry.get("exclude") or [])
    return _meter_key(kind, value) == key


def _literal(kind: str, value: str) -> str:
    """What a via file must name: the path, the command, or a glob's literal prefix."""
    if kind == "glob":
        return re.split(r"[*?\[]", value, maxsplit=1)[0]
    return value


def _glob_files(root: Path, pattern: str, exclude: list[str] | None = None) -> list[str]:
    skip = set(exclude or [])
    return sorted(rel for rel in (p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file())
                  if rel not in skip)


def _has_import_line(text: str, via: str, target: str) -> bool:
    rel = posixpath.relpath(target, posixpath.dirname(via) or ".")
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence and line.rstrip() in (f"@{rel}", f"@./{rel}"):
            return True
    return False


def _family(families: list[dict], path: str) -> dict | None:
    best = None
    for row in families:
        prefix = str(row.get("path", "")).rstrip("/") + "/"
        if path.startswith(prefix) and (best is None or len(prefix) > len(str(best["path"]).rstrip("/")) + 1):
            best = row
    return best


def _read(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ----------------------------------------------------------- the checks --

def _schema(entry: dict) -> list[str]:
    found = []
    if _subject(entry) is None:
        found.append("needs exactly one of path, glob, command, harness")
    unknown = sorted(set(entry) - KEYS)
    if unknown:
        found.append(f"unknown key(s) {', '.join(unknown)}")
    if entry.get("tier") not in TIERS:
        found.append(f"tier must be one of {', '.join(sorted(TIERS))}, not {entry.get('tier')!r}")
    elif entry.get("tier") == "mixed" and ("path" in entry or "glob" in entry):
        found.append("tier mixed is only for a listing or a command's output, assembled from "
                     "several tiers at run time; a file has exactly one tier, so split the entry")
    if entry.get("read") not in READS:
        found.append(f"read must be one of {', '.join(sorted(READS))}, not {entry.get('read')!r}")
    reaches = entry.get("reaches")
    if not isinstance(reaches, list) or set(reaches) - REACHES:
        found.append(f"reaches must be a list drawn from {', '.join(sorted(REACHES))}")
    via = entry.get("via")
    if not isinstance(via, list) or not via or not all(isinstance(v, str) and v for v in via):
        found.append("needs via: the file(s) that link or instruct it, or `harness`")
    if not isinstance(entry.get("role"), str) or not entry.get("role"):
        found.append("needs role: what it is, in a few words")
    if entry.get("expect") not in (None, "absent"):
        found.append("expect may only be `absent`")
    exclude = entry.get("exclude")
    if exclude is not None and ("glob" not in entry or not isinstance(exclude, list)
                                or not all(isinstance(x, str) for x in exclude)):
        found.append("exclude is a list of paths, and only a glob entry has one")
    debt = entry.get("debt")
    if debt is not None:
        if not isinstance(debt, dict) or debt.get("kind") not in DEBT_KINDS:
            found.append(f"debt.kind must be one of {', '.join(sorted(DEBT_KINDS))}")
        else:
            for key in ("reason", "until"):
                if not str(debt.get(key) or "").strip():
                    found.append(f"debt needs a {key}")
    return found


def _check_entry(ctx: Context, entry: dict) -> tuple[list[str], dict[str, str]]:
    """Plain problems, and the debt-able ones keyed by kind."""
    kind, value = _subject(entry)  # type: ignore[misc]
    root, read, tier = ctx.root, entry["read"], entry["tier"]
    plain: list[str] = []
    debtable: dict[str, str] = {}

    # where
    present = False
    if kind == "path":
        present = (root / value).is_file()
        alias = present and (root / "AGENTS.md").is_file() and (root / value).samefile(root / "AGENTS.md")
        if entry.get("expect") == "absent":
            # A link to AGENTS.md is one manual for both tools, not a shadow
            # (measure-context.py and migrate-entry-file.py read it the same way).
            if present and not alias:
                plain.append("must stay absent, and it exists")
        elif not present and not entry.get("optional"):
            plain.append("is missing")
        if tier != "mixed" and ctx.tier_of(value) != tier:
            plain.append(f"the manifest says {tier}, the scope router says {ctx.tier_of(value)}")
        if present and not alias and ctx.core_checkout and tier not in ("core", "mixed"):
            plain.append(f"is a {tier}-tier file present in a CORE checkout")
    elif kind == "glob":
        matches = _glob_files(root, value, entry.get("exclude"))
        present = bool(matches)
        for rel in matches:
            if tier != "mixed" and ctx.tier_of(rel) != tier:
                plain.append(f"matches {rel}, which the scope router puts at {ctx.tier_of(rel)}")
            if ctx.core_checkout and tier not in ("core", "mixed"):
                plain.append(f"matches {rel}, a {tier}-tier file present in a CORE checkout")
    else:
        present = True

    # who
    reaches = set(entry["reaches"])
    if read in PHASE_READS and "subagent" in reaches:
        plain.append("a sub-agent runs no Phase 0 or 1, so a start/command read never reaches it")
    if read in ("import", "harness") and entry.get("expect") != "absent" and "subagent" not in reaches:
        plain.append("an import or a listing reaches every sub-agent; say so in reaches")

    # when
    if read in ALWAYS_ON and entry.get("expect") != "absent":
        if kind == "glob":
            measured = any(_covers(entry, k) for k in ctx.meter) or not present
        elif kind == "path" and not present and entry.get("optional"):
            measured = True   # nothing to count until the instance has the file
        else:
            measured = _meter_key(kind, value) in ctx.meter
        if not measured:
            debtable["unmeasured"] = (f"is read {read}, but measure-context.py does not count it, "
                                      "so no cap holds it")
    if read in ("import", "start") and kind in ("path", "glob"):
        row = _family(ctx.families, value)
        if row is not None and row.get("read") == "named":
            debtable["placement"] = (f"is read {read}, but lies in {row['path']}, which "
                                     "docs/data-model.yaml says is read only when named")

    # how
    for via in entry["via"]:
        if via == HARNESS:
            continue
        text = _read(root, via)
        if text is None:
            plain.append(f"via names {via}, which does not exist")
            continue
        if read == "import" and kind == "path":
            if not _has_import_line(text, via, value):
                plain.append(f"is read import via {via}, which has no @-line for it")
        elif _literal(kind, value) not in text:
            debtable["uninstructed"] = f"{via} never names {_literal(kind, value)}"
    if read == "import" and kind == "path" and present and HARNESS not in entry["via"] \
            and value not in ctx.imports:
        plain.append("is declared read import, but no @-line imports it (measure-context.py "
                     "does not see it)")
    return plain, debtable


def evaluate(ctx: Context) -> Report:
    report = Report()
    described: set[str] = {MANIFEST}
    for entry in ctx.entries:
        subject = _subject(entry)
        label = f"{subject[0]} {subject[1]}" if subject else repr(entry)
        if subject and subject[0] == "path":
            described.add(subject[1])
        schema = _schema(entry)
        if schema:
            report.problems += [f"{label}: {p}" for p in schema]
            continue
        plain, debtable = _check_entry(ctx, entry)
        report.problems += [f"{label}: {p}" for p in plain]
        debt = entry.get("debt") or {}
        for kind, message in debtable.items():
            if debt.get("kind") == kind:
                report.debts.append(f"{label}: {kind}: {message}. Debt: {debt['reason']} "
                                    f"(until {debt['until']})")
            else:
                report.problems.append(f"{label}: {kind}: {message}")
        if debt and debt["kind"] not in debtable:
            report.problems.append(f"{label}: stale debt ({debt['kind']}): the contradiction it "
                                   "excuses is gone, remove the debt")

    for key, source in sorted(ctx.meter.items()):
        if key in ctx.instance_declared or any(_covers(e, key) for e in ctx.entries if _subject(e)):
            continue
        report.problems.append(f"{key}: measure-context.py counts it always-on ({source}), but no "
                               f"entry in {MANIFEST} says where it lives and when it is read")
    for rel in sorted(ctx.imports):
        if rel in ctx.instance_declared:
            continue  # an instance's own import, capped in context-budget.user.yaml
        if not any(_covers(e, rel) and e.get("read") == "import" for e in ctx.entries if _subject(e)):
            report.problems.append(f"{rel}: an @-line imports it, but {MANIFEST} has no "
                                   "read: import entry for it")
    for rel in ctx.kernel_files:
        if rel not in described:
            report.problems.append(f"{rel}: kernel/ is CORE and holds only what {MANIFEST} "
                                   "describes; an instance file belongs in identity/agent/")
    return report


# -------------------------------------------------------- the real tree --

def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, HERE / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"error: scripts/{rel} not found")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _meter(root: Path) -> dict[str, str]:
    mc = _load("measure_context_for_kernel", "measure-context.py")
    budget = mc.load_budget(root)
    keys: dict[str, str] = {}
    for rel in mc.resolve_entries(root):
        keys.setdefault(rel, "import")
    for rel in mc.discover_imports(root):
        keys.setdefault(rel, "import")
    for rel in mc.discover_registries(root):
        keys.setdefault(rel, "phase1")
    for rel in mc.discover_standing_orders(root):
        keys.setdefault(rel, "standing-order")
    for rel in mc.discover_listings(root):
        keys.setdefault(rel, "listing")
    for rel in mc.discover_harness(root):
        keys.setdefault(rel, "harness")
    for key, item in (budget.get("items") or {}).items():
        keys.setdefault(key, str((item or {}).get("source") or "budget"))
    return keys


def gather(root: Path) -> Context:
    root = Path(root).resolve()
    manifest = yaml.safe_load((root / MANIFEST).read_text(encoding="utf-8")) or {}
    mc = _load("measure_context_for_kernel", "measure-context.py")
    dm = _load("data_model_for_kernel", "data-model.py")
    router = _load("categorize_commits_for_kernel", "categorize-commits.py")
    user_budget = root / USER_BUDGET
    declared: set[str] = set()
    if user_budget.is_file():
        declared = set(((yaml.safe_load(user_budget.read_text(encoding="utf-8")) or {})
                        .get("items") or {}).keys())

    def tier_of(rel: str) -> str:
        here = os.getcwd()
        try:
            os.chdir(root)
            return router.classify_file(rel)
        finally:
            os.chdir(here)

    kernel = root / "kernel"
    kernel_files = sorted(p.relative_to(root).as_posix() for p in kernel.rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts) if kernel.is_dir() else []
    return Context(
        root=root,
        entries=list(manifest.get("entries") or []),
        meter=_meter(root),
        instance_declared=declared,
        imports=set(mc.discover_imports(root)),
        families=[{"path": r.get("path"), "read": r.get("read")} for r in dm.load_model(root)["families"]],
        tier_of=tier_of,
        kernel_files=kernel_files,
        core_checkout=not (root / "bridge-config.yaml").exists(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hold kernel/manifest.yaml to the tree (docs/kernel.md)")
    parser.add_argument("--repo-root", default=str(HERE.parent))
    parser.add_argument("--quiet", action="store_true", help="findings only")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    if not (root / MANIFEST).is_file():
        print(f"error: {MANIFEST} not found in {root}", file=sys.stderr)
        return 2
    ctx = gather(root)
    report = evaluate(ctx)
    for problem in report.problems:
        print(f"  FAIL  {problem}")
    if not args.quiet:
        for debt in report.debts:
            print(f"  debt  {debt}")
    verdict = "clean" if not report.problems else f"{len(report.problems)} finding(s)"
    print(f"check-kernel: {len(ctx.entries)} entries, {verdict}, {len(report.debts)} open debt(s) "
          f"(docs/kernel.md)")
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
