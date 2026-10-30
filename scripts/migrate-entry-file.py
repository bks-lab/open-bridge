#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""migrate-entry-file.py: move a fork off its root CLAUDE.md, once, dry run first.

Upstream no longer ships a root CLAUDE.md. Claude Code (2.1.281 or newer) reads
AGENTS.md natively, and a root CLAUDE.md, CLAUDE.local.md or .claude/CLAUDE.md
beside it makes Claude Code load only that file and never AGENTS.md. A fork that
edited CLAUDE.md (onboarding imports, overlay imports, its own prose) meets a
modify/delete conflict on the next `git merge upstream/main`. This script settles
it in one command:

  * import lines CORE no longer needs are dropped (`@AGENTS.md`, the identity
    files the AGENTS.md in force imports itself, `@ecosystem*.yaml`, which
    Phase 1 indexes)
  * every other import is carried, rewritten relative to the target's folder
  * paragraphs equal to any CORE version of the file are dropped
  * everything else is carried to identity/agent/INSTANCE.md under a dated heading
  * a `CLAUDE.md:` item in context-budget.user.yaml is removed
  * the file is removed (`git rm`, which also resolves the modify/delete conflict)

A second mode, `--file AGENTS.md`, does the same for a fork that edited AGENTS.md:
the lines it added or changed (not whole blocks) go to INSTANCE.md, each under
the CORE heading it sat beneath, and AGENTS.md is restored to the CORE version
the rest of the tree is on (the merge base; mid-merge: the fork's lines are
HEAD's against `git merge-base HEAD MERGE_HEAD`, the restore is MERGE_HEAD). CORE history
is read from the ref and from every remote with the same URL, so a stale
`upstream/main` beside a fresher `open-bridge/main` is no false verdict.

The AGENTS.md in force (MERGE_HEAD's while merging, else the working tree's;
in AGENTS.md mode the version being restored) must import
identity/agent/INSTANCE.md, or the carried lines would land in a file nothing
loads. On a fork still on an older AGENTS.md, --write refuses: merge upstream
first, then migrate mid-merge. A CLAUDE.md that is a link to AGENTS.md (one
manual for both tools) is left alone.

Stdlib only and no imports from scripts/, so it also runs from stdin mid-merge:
  git show MERGE_HEAD:scripts/migrate-entry-file.py | python3 - --repo-root .

Usage:
  python3 scripts/migrate-entry-file.py            # dry run: print the plan, change nothing
  python3 scripts/migrate-entry-file.py --write    # carry the lines, edit the budget, git rm CLAUDE.md
  python3 scripts/migrate-entry-file.py --check    # exit 1 while a root CLAUDE.md exists
                                                   # (AGENTS.md: a warning; exit 1 only with --file AGENTS.md)
    --file PATH          migrate only this file (CLAUDE.md, CLAUDE.local.md,
                         .claude/CLAUDE.md or AGENTS.md); default: the three shadow files
    --to PATH            where carried prose goes (default identity/agent/INSTANCE.md)
    --upstream-ref REF   where CORE's history lives (default: MERGE_HEAD while
                         merging, else upstream/main, else origin/main)
    --repo-root DIR

Exit: 0 done or nothing to do; 1 --check found a shadow file (or, with
--file AGENTS.md, an edited AGENTS.md); 2 usage error, a missing target, a target
an overlay owns, CORE refs whose merge bases do not line up, or (--write) an
AGENTS.md in force that does not import identity/agent/INSTANCE.md.

Docs: docs/updating.md
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import os
import re
import subprocess
import sys

SHADOW_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")
DEFAULT_TARGET = "identity/agent/INSTANCE.md"
ONBOARDED_MARKER = "identity/agent/IDENTITY.md"
USER_BUDGET = "context-budget.user.yaml"
CORE_BUDGET = "context-budget.yaml"
OVERLAY_LOCK = "overlays.lock.yaml"

IMPORT_RE = re.compile(r"^@(\S+)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
DROP_RULES = (
    (re.compile(r"^AGENTS\.md$"), "AGENTS.md is the entry now"),
    (re.compile(r"^ecosystem(\.[a-z][a-z0-9-]*)?\.yaml$"),
     "indexed by Phase 1: context-index.py --registries"),
)
IN_FORCE = "AGENTS.md imports it"
MERGE_FIRST = "merge upstream first, then migrate mid-merge (docs/updating.md)"
SUPERSEDED = "context-index.py ecosystem"

# The final CORE CLAUDE.md, verbatim (a quotation: its dashes are CORE's own).
# History from the upstream ref covers every earlier version; this constant
# covers a fork that migrates with no upstream ref at hand.
LAST_CORE_CLAUDE_MD = """\
@AGENTS.md

# Claude Code specifics

The canonical, tool-agnostic operating manual for this repo is
**[`AGENTS.md`](AGENTS.md)**
(Linux-Foundation convention, read natively by Codex/Cursor/Copilot/Gemini). Its size, and
that of everything else a session loads, is reported by `python3 scripts/measure-context.py`
rather than written down here, where it would go stale. AGENTS.md is inlined
above via `@AGENTS.md`, so the full manual — session-start gate, rules, task management, agents,
standing orders, commands — is already in your context. This file only adds the
Claude-Code-specific bits.

The project registry (`ecosystem.yaml`, created at onboarding, per instance) is no longer
`@`-imported. It is **indexed**: Phase 1 runs
`python3 scripts/context-index.py ecosystem.yaml`, which emits the settings verbatim and one
line per repo, customer and workspace; the entry itself arrives with `--get <name>` when
somebody names one. The registry is the always-on file that grows with the instance rather
than with this repo, and reading it whole meant carrying a paragraph about every project in
order to know that the project exists. Details: [`docs/context-index.md`](docs/context-index.md).

That trade has a real cost worth naming: an `@`-import is resident for the whole session,
while a Phase 1 read is ordinary conversation and can be compacted away later. The card is
small enough to re-run, and `--get` is always available; a file large enough to matter here is
too large to keep resident on that argument alone. Keeping the `@`-import beside a `card:` gets
neither: `measure-context.py` fails it as `contradiction`, since the import loads the file whole.

Onboarding appends further `@`-imports here as it seeds the live USER files
(e.g. `identity/agent/SOUL.md` + `IDENTITY.md`).

**Run the Phase-0 session-start gate before responding.** Belt-and-suspenders, so the gate
survives even if the import above fails to resolve:
Do not answer the first user message (even "hi", "status", "what can you do") before running Phase 0.
Phase 0 mechanic, inlined here so it works even if `@AGENTS.md` is silently dropped: detect the
current branch + whether a `user/*` branch exists + whether `bridge-config.yaml` is present, and
route accordingly — on the core branch with no `user/*` and no `bridge-config.yaml`, trigger the
NEW USER path (`/bridge-onboard`); otherwise route to the matching state (wrong-branch, orphan,
broken-config, or normal task-management load).

If `@AGENTS.md` does not resolve in your harness, read `AGENTS.md` manually before responding.
"""


# ------------------------------------------------------------------ git --

class Repo:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def git(self, *args, check=False, text=True, stdin=None):
        return subprocess.run(["git", "-C", self.root, *args], capture_output=True,
                              text=text, input=stdin)

    def ok(self, *args) -> bool:
        return self.git(*args).returncode == 0

    def path(self, rel: str) -> str:
        return os.path.join(self.root, rel)

    def exists(self, rel: str) -> bool:
        return os.path.isfile(self.path(rel))

    def read(self, rel: str) -> str:
        with open(self.path(rel), encoding="utf-8") as f:
            return f.read()

    def unmerged_ours(self, rel: str):
        """Our side of an unmerged path (stage 2), or None."""
        out = self.git("ls-files", "-u", "--", rel).stdout
        if any(line.split()[2] == "2" for line in out.splitlines() if line.strip()):
            p = self.git("show", f":2:{rel}")
            if p.returncode == 0:
                return p.stdout
        return None

    def local_text(self, rel: str):
        ours = self.unmerged_ours(rel)
        if ours is not None:
            return ours
        if self.exists(rel):
            return self.read(rel)
        return None

    def tracked(self, rel: str) -> bool:
        return bool(self.git("ls-files", "-s", "--", rel).stdout.strip())

    def ignored(self, rel: str) -> bool:
        return self.ok("check-ignore", "-q", "--", rel)

    def merging(self) -> bool:
        return self.ok("rev-parse", "-q", "--verify", "MERGE_HEAD")

    def resolve_ref(self, wanted):
        if wanted:
            return wanted if self.ok("rev-parse", "-q", "--verify", wanted) else None
        for ref in ("MERGE_HEAD", "upstream/main", "origin/main"):
            if self.ok("rev-parse", "-q", "--verify", ref):
                return ref
        return None

    def remote_of(self, ref: str):
        """(remote, branch) for a remote-tracking ref such as upstream/main."""
        remotes = self.git("remote").stdout.split()
        for r in sorted(remotes, key=len, reverse=True):
            if ref.startswith(r + "/"):
                return r, ref[len(r) + 1:]
        return None, None

    def core_refs(self, ref) -> list:
        """`ref` plus the same branch on every remote with the same URL.

        Only that branch: a fork's own remote also holds user/* branches, and
        those must never count as CORE.
        """
        if not ref:
            return []
        refs = [ref]
        probe = ref
        if ref == "MERGE_HEAD":
            probe = next((r for r in ("upstream/main", "origin/main")
                          if self.ok("rev-parse", "-q", "--verify", r)), None)
            if probe:
                refs.append(probe)
        remote, branch = self.remote_of(probe) if probe else (None, None)
        if not remote:
            return refs
        url = self.git("remote", "get-url", remote).stdout.strip()
        for r in self.git("remote").stdout.split():
            cand = f"{r}/{branch}"
            if (cand not in refs and url
                    and self.git("remote", "get-url", r).stdout.strip() == url
                    and self.ok("rev-parse", "-q", "--verify", cand)):
                refs.append(cand)
        return refs

    def show(self, rev: str, rel: str):
        p = self.git("show", f"{rev}:{rel}")
        return p.stdout if p.returncode == 0 else None

    def newest_base(self, refs: list):
        """The newest merge base of HEAD with any CORE ref: the CORE version the
        tree is on. ("", why) when the bases do not form one line."""
        bases = []
        for r in refs:
            p = self.git("merge-base", "HEAD", r)
            if p.returncode == 0 and p.stdout.strip():
                b = p.stdout.strip()
                if b not in bases:
                    bases.append(b)
        if not bases:
            return None, None
        best = bases[0]
        for b in bases[1:]:
            if self.ok("merge-base", "--is-ancestor", best, b):
                best = b
            elif not self.ok("merge-base", "--is-ancestor", b, best):
                return "", "the CORE refs " + ", ".join(refs) + " have diverged merge bases"
        return best, None

    def versions(self, ref, rel: str) -> list:
        """Every version of `rel` reachable from `ref` (a ref or a list), newest first."""
        if not ref:
            return []
        refs = ref if isinstance(ref, list) else [ref]
        shas = self.git("log", "--format=%H", *refs, "--", rel).stdout.split()
        if not shas:
            return []
        req = "".join(f"{s}:{rel}\n" for s in shas).encode()
        out = self.git("cat-file", "--batch", text=False, stdin=req).stdout
        found, i = [], 0
        while i < len(out):
            nl = out.index(b"\n", i)
            head = out[i:nl].split()
            i = nl + 1
            if len(head) == 3 and head[1] == b"blob":
                size = int(head[2])
                found.append(out[i:i + size].decode("utf-8", "replace"))
                i += size + 1
        return found


# --------------------------------------------------------------- blocks --

def split_blocks(text: str) -> list:
    """Paragraphs split by blank lines; a fenced block is never split.

    Each block is a list of (line, is_import) with trailing whitespace stripped.
    """
    blocks, cur, fence = [], [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = FENCE_RE.match(line)
        if fence:
            cur.append((line, False))
            if m and m.group(1) == fence:
                fence = None
            continue
        if m:
            fence = m.group(1)
            cur.append((line, False))
            continue
        if not line:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append((line, bool(IMPORT_RE.match(line))))
    if cur:
        blocks.append(cur)
    return blocks


def imports_of(text, src_rel: str = "AGENTS.md") -> set:
    """Repo paths a file `@`-imports, file-relative (split_blocks never marks a
    fenced line as an import)."""
    return {resolve_import(src_rel, IMPORT_RE.match(line).group(1))
            for block in split_blocks(text or "") for line, imp in block if imp}


def drop_reason(repo_path: str, in_force: set):
    reason = next((why for rx, why in DROP_RULES if rx.match(repo_path)), None)
    if reason is None and repo_path in in_force:
        reason = IN_FORCE
    return reason


def resolve_import(src_rel: str, target: str) -> str:
    """An import as a repo path (file-relative, as Claude Code resolves it)."""
    if target.startswith("~/") or target.startswith("/"):
        return target
    return os.path.normpath(os.path.join(os.path.dirname(src_rel), target)).replace(os.sep, "/")


def core_baseline(versions: list, src_rel: str):
    """Prose blocks and import targets of every CORE version."""
    prose, imports = set(), set()
    for text in versions:
        for b in split_blocks(text):
            rest = tuple(line for line, imp in b if not imp)
            if rest:
                prose.add(rest)
            for line, imp in b:
                if imp:
                    imports.add(resolve_import(src_rel, IMPORT_RE.match(line).group(1)))
    return prose, imports


# ----------------------------------------------------------------- plan --

class Plan:
    def __init__(self):
        self.notes = []          # (verb, text)
        self.warns = []
        self.carry = []          # (source, [block text])
        self.remove = []         # source paths
        self.restore = []        # (path, ref)
        self.budget_keys = []


def classify(src_rel, text, versions, dest, plan, target_text, in_force):
    prose, core_imports = core_baseline(versions, src_rel)
    carried, dropped_core = [], 0
    for block in split_blocks(text):
        imports, rest = [], []
        for line, imp in block:
            if not imp:
                rest.append(line)
                continue
            repo_path = resolve_import(src_rel, IMPORT_RE.match(line).group(1))
            reason = drop_reason(repo_path, in_force)
            if reason is None and repo_path in core_imports:
                reason = "CORE import"
            if reason:
                plan.notes.append(("drop", f"{line}  ({reason})"))
                continue
            if repo_path.startswith(("~/", "/")):
                new = line
            else:
                new = "@" + os.path.relpath(repo_path, os.path.dirname(dest) or ".").replace(os.sep, "/")
            plan.notes.append(("carry", f"{line} -> {new}"))
            imports.append(new)
            rest.append(("\0import", new))
        prose_only = tuple(x for x in rest if isinstance(x, str))
        if prose_only and prose_only in prose:
            dropped_core += 1
            lines = imports
        else:
            lines = [x[1] if isinstance(x, tuple) else x for x in rest]
        if not lines:
            continue
        body = "\n".join(lines)
        if body in target_text:
            plan.notes.append(("skip", f"a block already in {dest}: {lines[0][:60]}"))
            continue
        if SUPERSEDED in body:
            plan.warns.append(f"{src_rel}: a carried block runs `{SUPERSEDED}...`: "
                              "superseded by context-index.py --registries; edit it after the move")
        carried.append(body)
    if dropped_core:
        plan.notes.append(("drop", f"{dropped_core} block(s) of CORE text"))
    if carried:
        plan.carry.append((src_rel, carried))


# --------------------------------------------------------------- budget --

def item_span(lines: list, key: str):
    """(start, end) of a top-level `items:` entry, or None."""
    key_re = re.compile(r"^  (['\"]?)" + re.escape(key) + r"\1:\s*$")
    in_items = False
    for i, line in enumerate(lines):
        if re.match(r"^items:\s*$", line):
            in_items = True
            continue
        if in_items and line.strip() and not line.startswith(" ") and not line.startswith("#"):
            in_items = False
        if in_items and key_re.match(line):
            j = i + 1
            while j < len(lines):
                cur = lines[j]
                if cur.strip() == "":
                    k = j
                    while k < len(lines) and lines[k].strip() == "":
                        k += 1
                    if k < len(lines) and indent(lines[k]) > 2:
                        j = k
                        continue
                    break
                if indent(cur) > 2:
                    j += 1
                    continue
                break
            return i, j
    return None


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def remove_item(text: str, key: str):
    lines = text.splitlines(keepends=True)
    span = item_span([l.rstrip("\n") for l in lines], key)
    if not span:
        return None
    return "".join(lines[:span[0]] + lines[span[1]:])


def cap_of(repo: Repo, key: str):
    """Effective max_bytes for `key`: the user file replaces an entry wholesale."""
    for name in (USER_BUDGET, CORE_BUDGET):
        if not repo.exists(name):
            continue
        lines = repo.read(name).splitlines()
        span = item_span(lines, key)
        if span:
            for line in lines[span[0] + 1:span[1]]:
                m = re.match(r"^\s+max_bytes:\s*(\d+)\s*$", line)
                if m:
                    return int(m.group(1)), name
            return None, name
    return None, None


def overlay_owns(repo: Repo, rel: str) -> bool:
    if not repo.exists(OVERLAY_LOCK):
        return False
    for line in repo.read(OVERLAY_LOCK).splitlines():
        m = re.match(r"^\s*(?:-\s+)?dest:\s*['\"]?([^'\"#]+?)['\"]?\s*(#.*)?$", line)
        if m and m.group(1).strip() == rel:
            return True
    return False


# ----------------------------------------------------------------- main --

def is_core_checkout(repo: Repo) -> bool:
    return not repo.exists("bridge-config.yaml")


def agents_md_diverged(repo: Repo, refs: list) -> bool:
    if not refs or is_core_checkout(repo) or not repo.exists("AGENTS.md"):
        return False
    versions = repo.versions(refs, "AGENTS.md")
    if not versions:
        return False
    text = repo.local_text("AGENTS.md")
    return text not in versions


def heading_before(lines: list, i: int):
    for j in range(min(i, len(lines)) - 1, -1, -1):
        if lines[j].startswith("#"):
            return lines[j].rstrip()
    return None


def classify_lines(text, base, dest, plan, target_text, in_force):
    """AGENTS.md mode: carry only the lines the fork added or changed against
    the CORE version it is on, each hunk under the heading it sat beneath."""
    a, b = base.splitlines(), text.splitlines()
    carried, dropped = [], 0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        dropped += i2 - i1
        new = [ln.rstrip() for ln in b[j1:j2]]
        out = []
        for ln in new:
            m = IMPORT_RE.match(ln)
            if not m:
                out.append(ln)
                continue
            repo_path = resolve_import("AGENTS.md", m.group(1))
            reason = drop_reason(repo_path, in_force)
            if reason:
                plan.notes.append(("drop", f"{ln}  ({reason})"))
                continue
            rel = repo_path if repo_path.startswith(("~/", "/")) else \
                os.path.relpath(repo_path, os.path.dirname(dest) or ".").replace(os.sep, "/")
            plan.notes.append(("carry", f"{ln} -> @{rel}"))
            out.append("@" + rel if not repo_path.startswith(("~/", "/")) else ln)
        while out and not out[0].strip():
            out.pop(0)
        while out and not out[-1].strip():
            out.pop()
        if not out:
            continue
        body = "\n".join(out)
        if body in target_text:
            plan.notes.append(("skip", f"lines already in {dest}: {out[0][:60]}"))
            continue
        where = heading_before(b, j1)
        carried.append((f"From AGENTS.md, under `{where}`:\n\n" if where else "") + body)
    if dropped:
        plan.notes.append(("note", f"{dropped} CORE line(s) your AGENTS.md changed or removed come back with the restore"))
    if carried:
        plan.carry.append(("AGENTS.md", carried))


def is_agents_alias(repo: Repo, rel: str) -> bool:
    """`rel` is the same file as AGENTS.md: one manual for both tools."""
    try:
        return (os.path.isfile(repo.path(rel)) and repo.exists("AGENTS.md")
                and os.path.samefile(repo.path(rel), repo.path("AGENTS.md")))
    except OSError:
        return False


def present_shadows(repo: Repo) -> list:
    return [f for f in SHADOW_FILES
            if repo.local_text(f) is not None and not is_agents_alias(repo, f)]


def parent_shadows(repo: Repo) -> list:
    found, d = [], os.path.dirname(repo.root)
    while True:
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                found.append(p)
        up = os.path.dirname(d)
        if up == d:
            return found
        d = up


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Move a fork off its root CLAUDE.md (docs/updating.md).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="apply the plan")
    mode.add_argument("--check", action="store_true", help="exit 1 while a shadow file exists")
    ap.add_argument("--file", choices=SHADOW_FILES + ("AGENTS.md",))
    ap.add_argument("--to")
    ap.add_argument("--upstream-ref")
    ap.add_argument("--repo-root", default=".")
    a = ap.parse_args(argv)

    repo = Repo(a.repo_root)
    if not repo.ok("rev-parse", "--git-dir"):
        print(f"error: {repo.root} is not a git repository", file=sys.stderr)
        return 2
    ref = repo.resolve_ref(a.upstream_ref)
    if a.upstream_ref and not ref:
        print(f"error: ref '{a.upstream_ref}' not found", file=sys.stderr)
        return 2

    for p in parent_shadows(repo):
        print(f"WARN  {p}: outside this repo; Claude Code loads it instead of AGENTS.md "
              "when started here. Review it by hand.")

    refs = repo.core_refs(ref)

    if a.check:
        red = [] if a.file == "AGENTS.md" else present_shadows(repo)
        if a.file and a.file != "AGENTS.md":
            red = [f for f in red if f == a.file]
        for f in red:
            print(f"{f}: present; Claude Code loads it and not AGENTS.md. "
                  "Run python3 scripts/migrate-entry-file.py --write (docs/updating.md)")
        if (not a.file or a.file == "AGENTS.md") and agents_md_diverged(repo, refs):
            names = ", ".join(refs)
            if a.file == "AGENTS.md":
                red.append("AGENTS.md")
                print(f"AGENTS.md: differs from every CORE version on {names}. "
                      "Run python3 scripts/migrate-entry-file.py --file AGENTS.md (dry run first)")
            else:
                print(f"WARN  AGENTS.md: differs from every CORE version on {names}. "
                      "A CORE change still waiting on /bridge-promote, or one these refs lack "
                      "(git fetch first), is fine. A local edit belongs in "
                      f"{DEFAULT_TARGET}: python3 scripts/migrate-entry-file.py --file AGENTS.md")
        if not red:
            print("entry file: AGENTS.md only, nothing to migrate")
        return 1 if red else 0

    dest = (a.to or DEFAULT_TARGET).replace(os.sep, "/")
    target_text = repo.read(dest) if repo.exists(dest) else ""
    plan = Plan()
    sources = [a.file] if a.file else list(SHADOW_FILES)
    merging = repo.merging()
    # The AGENTS.md that will be in force once this lands. AGENTS.md mode
    # replaces it with the version it restores, below.
    in_force_text = repo.show("MERGE_HEAD", "AGENTS.md") if merging else repo.local_text("AGENTS.md")
    in_force_label = "MERGE_HEAD's AGENTS.md" if merging else "AGENTS.md"

    for src in sources:
        text = repo.local_text(src)
        if text is None:
            continue
        if src != "AGENTS.md" and is_agents_alias(repo, src):
            plan.notes.append(("keep", f"{src} is a link to AGENTS.md: one manual for both tools"))
            continue
        if src == "AGENTS.md":
            if not ref:
                print("error: --file AGENTS.md needs an upstream ref to restore from", file=sys.stderr)
                return 2
            if merging:
                # Ours against the common ancestor: diffing ours against theirs
                # would count every line upstream rewrote as a fork change.
                text = repo.show("HEAD", "AGENTS.md") or text
            versions = repo.versions(refs, "AGENTS.md")
            if text in versions:
                continue
            if merging:
                mb = repo.git("merge-base", "HEAD", "MERGE_HEAD").stdout.strip()
                base_rev = mb if mb and repo.show(mb, "AGENTS.md") is not None else "MERGE_HEAD"
                restore_rev = "MERGE_HEAD"
            else:
                base_rev, why = repo.newest_base(refs)
                if base_rev == "":
                    print(f"error: {why}; git fetch them, or pass --upstream-ref", file=sys.stderr)
                    return 2
                if base_rev is None:
                    base_rev = ref
                restore_rev = base_rev
            base = repo.show(base_rev, "AGENTS.md")
            if base is None:
                print(f"error: {base_rev} has no AGENTS.md to restore", file=sys.stderr)
                return 2
            if not merging:
                own = repo.git("log", "--no-merges", "--format=%h %s",
                               f"{base_rev}..HEAD", "--", "AGENTS.md").stdout.splitlines()
                for line in own:
                    plan.warns.append(f"AGENTS.md changed here since CORE {base_rev[:8]}: {line}. "
                                      "If it is a CORE change headed upstream, promote it instead.")
            in_force_text = repo.show(restore_rev, "AGENTS.md")
            in_force_label = f"the AGENTS.md it restores ({restore_rev[:12]})"
            classify_lines(text, base, dest, plan, target_text, imports_of(in_force_text))
            plan.restore.append(("AGENTS.md", restore_rev))
            continue
        versions = repo.versions(ref, "CLAUDE.md") + [LAST_CORE_CLAUDE_MD]
        classify(src, text, versions, dest, plan, target_text, imports_of(in_force_text))
        plan.remove.append(src)
        plan.budget_keys.append(src)

    if not plan.remove and not plan.restore:
        for verb, text in plan.notes:
            print(f"  {verb:<6} {text}")
        print("nothing to migrate: Claude Code reads AGENTS.md here")
        return 0

    in_force = imports_of(in_force_text)
    unloaded = DEFAULT_TARGET not in in_force
    if unloaded:
        plan.warns.append(f"{in_force_label} does not import {DEFAULT_TARGET}, so the carried "
                          f"lines would load nowhere and identity imports would be lost: {MERGE_FIRST}")
    elif dest != DEFAULT_TARGET and dest not in in_force:
        plan.warns.append(f"{dest} loads only if {DEFAULT_TARGET} imports it: add "
                          f"`@{os.path.relpath(dest, os.path.dirname(DEFAULT_TARGET))}` there")

    would = "" if a.write else "would "
    new_target = target_text
    if plan.carry:
        if not repo.exists(dest) and not a.to and not repo.exists(ONBOARDED_MARKER):
            print(f"error: {ONBOARDED_MARKER} does not exist; "
                  "run /bridge-onboard D4 first or pass --to <file>")
            return 2
        if overlay_owns(repo, dest):
            print(f"error: {dest} is materialized by an org overlay ({OVERLAY_LOCK}); "
                  "an overlay sync would overwrite carried lines. Pass --to <file>.")
            return 2
        today = datetime.date.today().isoformat()
        parts = []
        if not new_target:
            parts.append("# Instance\n")
        elif not new_target.endswith("\n"):
            parts.append("\n")
        for src, blocks in plan.carry:
            sep = "\n" if new_target or parts else ""
            parts.append(f"{sep}## Carried over from {src} ({today})\n\n" + "\n\n".join(blocks) + "\n")
        new_target = new_target + "".join(parts)

    budget_new = None
    if repo.exists(USER_BUDGET):
        budget_new = repo.read(USER_BUDGET)
        changed = False
        for key in plan.budget_keys:
            out = remove_item(budget_new, key)
            if out is not None:
                budget_new, changed = out, True
                print(f"budget: {would}remove item {key} from {USER_BUDGET}")
        if not changed:
            budget_new = None

    # ---- report ----
    for verb, text in plan.notes:
        print(f"  {verb:<6} {text}")
    for w in plan.warns:
        print(f"WARN  {w}")
    if plan.carry:
        n = sum(len(b) for _, b in plan.carry)
        print(f"{would}carry {n} block(s) to {dest}")
        cap, where = cap_of(repo, dest)
        size = len(new_target.encode("utf-8"))
        if cap is None:
            print(f"  {dest}: {len(target_text.encode('utf-8'))} -> {size} bytes, no cap declared")
        else:
            over = "  over the cap: raise it or shorten the text" if size > cap else ""
            print(f"  {dest}: {len(target_text.encode('utf-8'))} -> {size} bytes, cap {cap} ({where}){over}")
    else:
        print("nothing to carry: every line is CORE text or an import AGENTS.md covers")
    for src in plan.remove:
        print(f"{would}remove {src} ({'git rm' if repo.tracked(src) else 'untracked file'})")
    for path, r in plan.restore:
        label = "MERGE_HEAD (theirs)" if merging else f"{r[:12]} (the CORE version this tree is on)"
        print(f"{would}restore {path} from {label}")

    if not a.write:
        print("dry run: nothing changed. Apply with --write.")
        return 0
    if unloaded:
        print(f"error: refusing --write: {MERGE_FIRST}", file=sys.stderr)
        return 2

    # ---- apply ----
    if plan.carry:
        os.makedirs(os.path.dirname(repo.path(dest)) or ".", exist_ok=True)
        with open(repo.path(dest), "w", encoding="utf-8", newline="\n") as f:
            f.write(new_target)
    if budget_new is not None:
        with open(repo.path(USER_BUDGET), "w", encoding="utf-8", newline="\n") as f:
            f.write(budget_new)
    for src in plan.remove:
        if repo.tracked(src):
            p = repo.git("rm", "-q", "-f", "--", src)
            if p.returncode:
                print(f"error: git rm {src}: {p.stderr.strip()}", file=sys.stderr)
                return 2
        elif repo.exists(src):
            os.remove(repo.path(src))
    for path, r in plan.restore:
        p = repo.git("checkout", r, "--", path)
        if p.returncode:
            print(f"error: restoring {path}: {p.stderr.strip()}", file=sys.stderr)
            return 2

    add = []
    if plan.carry:
        if repo.ignored(dest):
            print(f"{dest}: kept locally; tracked after the private-home step")
        else:
            add.append(dest)
    if budget_new is not None and not repo.ignored(USER_BUDGET):
        add.append(USER_BUDGET)
    print("next:")
    if add:
        print(f"  git add {' '.join(add)}")
    print("  git commit" + ("   (concludes the merge)" if merging else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
