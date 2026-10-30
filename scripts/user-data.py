#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Instance data: out of a public clone by default, backed up by a private one, never a secret.

WHY THIS EXISTS. An instance's config (personas, accounts, secret stores,
channels, workloads, `bridge-config.yaml`, ...) and its `work/memory/` are the
part of a Bridge that no upstream can give back. Until 2026-09-25 the shipped
`.gitignore` ignored them family by family, with no way back for a private
instance short of editing a CORE file: a file already tracked stayed tracked, a
NEW one was left out of every commit and every backup without a word. A leak
attempt fails loudly at the push guard; a lost backup fails silently.

THE MODEL, three layers:

1. The shipped `.gitignore` carries the block `shipped_patterns()` prints. It
   is GENERIC (`/identity/*/*.yaml`), so a family added tomorrow is covered,
   and it protects a clone before anything at all has run in it.
2. On a PRIVATE origin, `arm` writes `identity/.gitignore`, `infra/.gitignore`,
   `workflow/.gitignore` and `work/.gitignore`, which negate those patterns: a
   deeper .gitignore wins over the root one. They are USER files and get
   committed with the instance, so a fresh clone of the private repo is right
   before setup ran there. The root files (`bridge-config.yaml`, ...) cannot be
   negated below the root, so `arm` stages them once with `git add -f` on a
   user/* branch; once tracked, being ignored no longer matters. `arm` never
   deletes a negation file: gh being offline makes a private origin look
   unknown, and deleting then would drop the backup.
3. What enters a commit is scanned. `scan-staged` reads the INDEX of every
   instance file and template and refuses a credential, so the backup can
   never be the leak. Personal data is not a credential: a persona carries a
   tax id by design.

The origin is classified by `scripts/lib/remote-class.sh`, the classifier the
push guard sources, so the two never disagree about the same remote.

    python3 scripts/user-data.py patterns      # the block the shipped .gitignore carries
    python3 scripts/user-data.py arm           # private origin: write negations, stage root files
    python3 scripts/user-data.py check         # private origin, instance data still ignored? (exit 1)
    python3 scripts/user-data.py scan-staged   # 0 clean · 1 credential · 2 unreadable · 3 not scanned
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent            # the scripts/ this file ships in
CLASSIFIER = HERE / "lib" / "remote-class.sh"
PATTERNS_MODULE = HERE.parent / "skills" / "secrets" / "engine" / "patterns.py"

WRAPPERS = ("identity", "infra", "workflow")
#: Root instance files. Held to the scope router's USER_PATTERNS by
#: scripts/tests/test_user_data.py, and to the push guard by test_push_guard_paths.py.
ROOT_FILES = ("bridge-config.yaml", "bridge-deck.config.yaml", "ecosystem.yaml",
              "overlays.lock.yaml", "workspaces.lock.yaml", "context-budget.user.yaml",
              "edges.yaml", "reachability-scenarios.yaml")
BEGIN = "# >>> user-data (managed by scripts/user-data.py, do not edit) >>>"
END = "# <<< user-data <<<"

#: What a private origin writes, relative to the repo root, and the negations in it.
NEGATIONS = {
    "identity/.gitignore": ["!/*/*.yaml", "!/agent/*.md", "!/designs/*.md"],
    "infra/.gitignore": ["!/*/*.yaml"],
    "workflow/.gitignore": ["!/*/*.yaml"],
    "work/.gitignore": ["!/memory/"],
}
NEGATION_FILES = tuple(NEGATIONS)


def shipped_patterns() -> list:
    """The block in the shipped .gitignore. Generic on purpose: no family is named."""
    lines = [f"/{name}" for name in ROOT_FILES]
    lines += ["/ecosystem.*.yaml", "!/ecosystem.example.yaml"]
    lines += [f"/{w}/*/*.yaml" for w in WRAPPERS]
    lines += [f"!/{w}/*/_*.yaml" for w in WRAPPERS]
    lines += ["/identity/agent/*.md", "!/identity/agent/README.md",
              "!/identity/agent/_*.md",
              # a design is a Markdown file (identity/designs/<id>.md), not a .yaml
              "/identity/designs/*.md", "!/identity/designs/_*.md", "/work/memory/"]
    return lines


# ── which path is instance data ───────────────────────────────────────────────

def is_instance_path(path: str) -> bool:
    """Instance data by path. The ONE predicate: scan, check and the tests use it.

    Inside a cluster wrapper every path is instance data except a `_`-prefixed
    name at any depth (templates, schemas, shipped fixtures) and a family's own
    type-level README.md. That includes nested data such as
    infra/channels/bots/<client>/bot.yaml, which no ignore pattern ever covered
    and which is therefore the more likely to be committed.
    """
    parts = path.split("/")
    name = parts[-1]
    if len(parts) == 1:
        return name in ROOT_FILES or (name.startswith("ecosystem.") and name.endswith(".yaml")
                                      and name != "ecosystem.example.yaml")
    if path in NEGATIONS:
        return True
    if parts[:2] == ["work", "memory"] and len(parts) > 2:
        return True
    if parts[0] not in WRAPPERS or len(parts) < 3:
        return False
    if any(seg.startswith("_") for seg in parts[1:]):
        return False
    return not (len(parts) == 3 and name == "README.md")


def covered(path: str) -> bool:
    """What the shipped block ignores, and so what only a private origin re-allows.

    `check` asks about these alone. Anything else an instance ignores (a
    .DS_Store, a cache, a firmware blob) is ignored by a rule of its own, on
    purpose, and a warning about it on every commit teaches its reader to skip
    the warning.
    """
    parts = path.split("/")
    if len(parts) == 1 or parts[:2] == ["work", "memory"]:
        return is_instance_path(path)
    if parts[:2] in (["identity", "agent"], ["identity", "designs"]) and len(parts) == 3 \
            and parts[2].endswith(".md"):
        return is_instance_path(path)
    return (len(parts) == 3 and parts[0] in WRAPPERS and parts[2].endswith(".yaml")
            and is_instance_path(path))


def scanned(path: str) -> bool:
    """What scan-staged reads: instance data plus the templates every clone receives.

    A value in a template reaches every Bridge ever set up, which is worse than
    one in an instance file, not better. Shipped fixtures (`_tests/`) are left
    alone: a fake key there is the point of the file.
    """
    parts = path.split("/")
    if (len(parts) == 3 and parts[0] in WRAPPERS and parts[2].startswith("_")
            and not parts[1].startswith("_")):
        return True
    return is_instance_path(path) or path == "ecosystem.example.yaml"


# ── git ───────────────────────────────────────────────────────────────────────

def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("user-data: not inside a git repository")
    return Path(out.stdout.strip())


def _git(root: Path, *args, **kw):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, **kw)


def _sh():
    """A POSIX sh, including the one Git for Windows bundles but keeps off PATH."""
    found = shutil.which("sh")
    if found:
        return found
    out = subprocess.run(["git", "--exec-path"], capture_output=True, text=True)
    base = Path(out.stdout.strip())
    for up in list(base.parents)[:3]:
        for rel in ("usr/bin/sh.exe", "bin/sh.exe"):
            if (up / rel).is_file():
                return str(up / rel)
    return None


def classify(root: Path, *, offline: bool = False) -> str:
    """private | public | unknown, from the push guard's own classifier.

    Anything that prevents asking it (no classifier, no sh) is unknown, the
    same fail-closed answer the push guard gives. `offline` skips the gh step,
    for the per-commit check that must not wait on the network.
    """
    sh = _sh()
    if not CLASSIFIER.is_file() or sh is None:
        return "unknown"
    env = dict(os.environ)
    if offline:
        env["REMOTE_CLASS_OFFLINE"] = "1"
    out = subprocess.run([sh, str(CLASSIFIER)], cwd=root, env=env,
                         capture_output=True, text=True)
    state = out.stdout.strip()
    return state if state in ("private", "public", "unknown") else "unknown"


def instance_files(root: Path) -> list:
    """Instance files present in the working tree, whether ignored or not."""
    found = [n for n in ROOT_FILES if (root / n).is_file()]
    found += sorted(p.name for p in root.glob("ecosystem.*.yaml") if is_instance_path(p.name))
    for top in (*WRAPPERS, "work/memory"):
        base = root / top
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                rel = p.relative_to(root).as_posix()
                if p.is_file() and is_instance_path(rel) and rel not in NEGATIONS:
                    found.append(rel)
    return found


def ignored(root: Path, paths: list) -> list:
    """(path, source:line pattern) for each path git ignores, by any rule."""
    if not paths:
        return []
    out = _git(root, "check-ignore", "-v", "--no-index", "--stdin", "-z",
               input=("\0".join(paths) + "\0").encode("utf-8", "surrogateescape"))
    fields = out.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    hits = []
    for i in range(0, len(fields) - 3, 4):
        source, line, pattern, path = fields[i:i + 4]
        if pattern and not pattern.startswith("!"):
            hits.append((path, f"{source}:{line} {pattern}"))
    return hits


# ── arm ───────────────────────────────────────────────────────────────────────

def _strip_block(text: str) -> str:
    kept, inside = [], False
    for line in text.splitlines(keepends=True):
        if line.rstrip("\n") == BEGIN:
            inside = True
            continue
        if inside:
            if line.rstrip("\n") == END:
                inside = False
            continue
        kept.append(line)
    return "".join(kept)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".user-data-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_negations(root: Path) -> list:
    changed = []
    for rel, rules in NEGATIONS.items():
        path = root / rel
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        after = _strip_block(before)
        if after and not after.endswith("\n"):
            after += "\n"
        after += "\n".join([
            BEGIN,
            "# This repo's origin is private, so its instance data is committed and",
            "# backed up. USER tier: the push guard keeps this file off public remotes.",
            *rules, END]) + "\n"
        if after != before:
            _write(path, after)
            changed.append(rel)
    return changed


def command_arm(root: Path) -> int:
    state = classify(root)
    present = [rel for rel in NEGATION_FILES if (root / rel).is_file()
               and BEGIN in (root / rel).read_text(encoding="utf-8")]
    if state != "private":
        if present:
            print(f"user-data: origin {state}, not confirmed private, yet {len(present)} "
                  "negation file(s) say this repo backs up its instance data.")
            print("  Left as they are. The push guard still refuses USER content to any")
            print("  remote that is not confirmed private.")
        else:
            print(f"user-data: origin {state} → instance data stays out of git (shipped .gitignore)")
        if state == "unknown":
            print("  If origin IS your private repo, say so and re-run bin/setup: add its")
            print("  owner/repo to push_guard.private_remotes in bridge-config.yaml, or let")
            print("  `gh` see it (gh auth login). Until then nothing here is backed up.")
        return 0

    changed = write_negations(root)
    print("user-data: origin private → instance data is committed and backed up")
    if changed:
        print(f"  wrote {', '.join(changed)} (commit them: they carry the backup to every clone)")
    branch = _git(root, "symbolic-ref", "--short", "HEAD", text=True).stdout.strip()
    roots = [p for p, _ in ignored(root, [n for n in instance_files(root) if "/" not in n])
             if _git(root, "ls-files", "--error-unmatch", "--", p).returncode != 0]
    if roots and branch.startswith("user/"):
        _git(root, "add", "-f", "--", *roots)
        print(f"  staged {', '.join(roots)} (root files cannot be negated, so they are added once)")
    elif roots:
        print(f"  not staged on {branch or 'a detached HEAD'}: {', '.join(roots)}.")
        print("  On your user/* branch: git add -f " + " ".join(roots))
    return 0


# ── check ─────────────────────────────────────────────────────────────────────

def command_check(root: Path) -> int:
    """A private instance whose own data is still ignored: the silent backup gap."""
    if classify(root, offline=True) != "private":
        return 0
    tracked = set(_git(root, "ls-files", "-z").stdout.decode("utf-8", "surrogateescape")
                  .split("\0"))
    candidates = [p for p in instance_files(root) if covered(p) and p not in tracked]
    hits = ignored(root, candidates)
    if not hits:
        return 0
    print("user-data: this repo's origin is private, and these instance files are ignored.")
    print("  They are left out of every commit and every backup:")
    for path, rule in hits:
        print(f"  {path}  ← {rule}")
    print("  Run bin/setup (writes the negation files, stages the root files), then commit.")
    return 1


# ── scan-staged ───────────────────────────────────────────────────────────────

def _load_patterns():
    if not PATTERNS_MODULE.is_file():
        return None
    spec = importlib.util.spec_from_file_location("ob_user_data_patterns", PATTERNS_MODULE)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def command_scan_staged(root: Path) -> int:
    out = _git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT")
    names = out.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    staged = [p for p in names if p and scanned(p)]
    if not staged:
        return 0
    module = _load_patterns()
    if module is None:
        print("user-data: skills/secrets is missing, so these staged instance files were "
              f"NOT scanned for credentials: {', '.join(staged)}")
        return 3
    hits, unreadable = [], []
    for path in staged:
        blob = subprocess.run([b"git", b"-C", os.fsencode(str(root)), b"cat-file", b"blob",
                               b":" + path.encode("utf-8", "surrogateescape")],
                              capture_output=True)
        if blob.returncode != 0:
            unreadable.append(path)
            continue
        if b"\0" in blob.stdout[:8192]:
            continue                                   # binary: no line to read
        text = blob.stdout.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            for pattern, excerpt in module.scan_line(line, include_pii=False):
                hits.append(f"  {path}:{number}  {pattern.name}  [{excerpt}]")
    if hits:
        print("user-data: a staged instance file carries a credential:")
        print("\n".join(hits))
        print("  Put the value in a secret store and write its reference instead,")
        print("  e.g. keychain://<service>/<account> (rules/secret-placement.md, skills/secrets).")
        print("  A deliberate fixture: end the line with  # pragma: allowlist secret")
        return 1
    if unreadable:
        print(f"user-data: could not read the staged content of {', '.join(unreadable)}")
        return 2
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Instance data: out of a public clone, backed up by a private one.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("patterns", "arm", "check", "scan-staged"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    if args.command == "patterns":
        print("\n".join(shipped_patterns()))
        return 0
    root = repo_root()
    return {"arm": command_arm, "check": command_check,
            "scan-staged": command_scan_staged}[args.command](root)


if __name__ == "__main__":
    sys.exit(main())
