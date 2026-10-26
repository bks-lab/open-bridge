#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Org-overlay engine — subscribe to, sync, and materialize an org overlay.

An *org overlay* is a separate git repo (one per org) that mirrors a FLAT tree
of behavioural + config files into a Bridge consumer. The overlay never
block-merges the consumer's config: it copies files in, wires its ecosystem
fragment as an `@import`, and records every materialized file in
`overlays.lock.yaml` pinned to immutable hashes. Org content is `scope: org`
by path + inline tripwire — it routes to the org overlay, NEVER to open-bridge,
which keeps the weekly `git merge main` conflict-free.

This is the generic CORE engine: it ships to open-bridge carrying zero org
data. The only org referenced in tests/docs is the fictional `example-org`.

Commands (subcommands of `/overlay`):
  add     subscribe to an overlay repo, first materialize, write the lock
  sync    pull cache, recompute, 3-way vs lock, re-materialize, prune, bump SHA
  apply   OFFLINE re-materialize from cache+lock (no network); idempotent
  status  resolved_sha vs cache HEAD, staleness, per-file state counts
  diff    preview the next sync/apply (plan + per-file before/after); no writes
  remove  hash-verify + delete clean managed files, drop cache/lock/@import
  list    subscribed overlays from upstreams[] (role: org-overlay)

Contracts:
  overlay.manifest.yaml   docs/schemas/overlay-manifest.schema.yaml (overlay root)
  overlays.lock.yaml      docs/schemas/overlays-lock.schema.yaml    (generated)

Reused primitives (loaded from this script's own dir, not the consumer):
  categorize-commits.py   classify_file(path) -> core|org|user (CORE-refusal)
  no-scrub-leak.py        per-file leak gate (subprocess)

Safety model:
  - never materialize off a user/* branch (CORE branches stay clean)
  - HARD-REFUSE a dest that classifies CORE, is `_`-prefixed, is a wrapper
    README/_template/_schema, or path-escapes the repo root
  - the raw-secret regex runs BEFORE every write; the no-scrub-leak
    CORE-boundary scan runs ONLY when the materialize target is itself core
    (an org overlay never writes core — core-leak protection lives at the
    consumer's push boundary + scope tiering, not at materialization)
  - behavioural files (skill/agent/standing-order) force an explicit [y],
    asked once per skill FOLDER (all or none) and once per agent/order file;
    a run without a person withholds the whole unit and `status` counts it
  - the lock stores prompted-field PATHS only, never the user's values
  - writes are atomic COPIES (never symlinks); --dry-run stops before any write

Exit codes:
  0 — success           1 — refusal / error           2 — setup/usage error

Full design: docs/org-overlays.md
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML not installed. pip install pyyaml\n")
    sys.exit(2)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Reused primitives (hyphenated filenames → load via importlib, not import)
# ---------------------------------------------------------------------------

def _load_module(name: str, filename: str):
    path = os.path.join(SCRIPT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {filename}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

try:
    _categorize = _load_module("categorize_commits", "categorize-commits.py")
    classify_file = _categorize.classify_file
except Exception as exc:  # pragma: no cover - defensive
    sys.stderr.write(f"ERROR: cannot load categorize-commits.py: {exc}\n")
    sys.exit(2)

NO_SCRUB_LEAK = os.path.join(SCRIPT_DIR, "no-scrub-leak.py")


def card_declared(repo_root: str, rel_path: str) -> bool:
    """True when the context budget declares `rel_path` as a Phase 1 card.

    Read through scripts/lib/context_index.py, the same function the meter and
    the index use, so the three cannot disagree about what is indexed. Loaded
    lazily: a consumer without the library (or without PyYAML) falls back to
    the old behaviour, the @import, rather than failing the sync, and says so:
    a silent fallback would re-add an import the instance removed on purpose.
    """
    try:
        lib = _load_module("context_index", os.path.join("lib", "context_index.py"))
        return bool(lib.card_for(repo_root, rel_path))
    except Exception as exc:  # pragma: no cover - defensive
        sys.stderr.write(
            f"  WARN   cannot read the context budget ({type(exc).__name__}: {exc}); "
            f"treating {rel_path} as not indexed, the @import may be added\n")
        return False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BEHAVIOURAL_KINDS = {"skill", "agent", "standing-order"}
ALL_KINDS = {"config", "skill", "agent", "standing-order", "rule",
             "ecosystem-fragment"}
# A prune batch of clean orphans larger than this is treated as a likely
# `select:` misconfiguration (e.g. a glob narrowed instead of extended) rather
# than a genuine handful of upstream deletions, and gets an extra gate before
# any file is removed — see LARGE PRUNE GUARD below.
LARGE_PRUNE_THRESHOLD = 5
CACHE_BASE = ".bridge/overlays"
LOCK_FILE = "overlays.lock.yaml"
# Last outcome of each unattended sync, per overlay. Derived state beside the
# caches (gitignored), read by `status`: the lock records what was applied, this
# records what the last scheduled run DID, which includes holding back.
UNATTENDED_STATE = ".bridge/overlay-unattended.yaml"
DEFAULT_PULL_INTERVAL_DAYS = 7
# A daily job starts at roughly the same minute each day, so an interval of N
# days measured to the second would miss its slot by the few seconds the last
# run took and slip a whole day. An hour of slack keeps it on schedule.
DUE_SLACK = timedelta(hours=1)
MANIFEST_FILE = "overlay.manifest.yaml"
DEFAULT_SOURCE_ROOT = "tree/"
MAX_MANIFEST_BYTES = 256 * 1024  # an overlay manifest is small; anything bigger is suspect

# Secret material that must never be copied verbatim into a consumer file.
# Accounts reference secrets by URI only. The list is the one in
# rules/secret-placement.md, and scripts/check-secret-grammar.py fails CI when
# the two drift: this tuple had been missing keepass:// and file:// since the
# schemes were written down, so a keepass reference in a consumer file was read
# as an opaque string rather than as the locator it is.
SECRET_URI_PREFIXES = ("azure-keyvault://", "keychain://", "1password://",
                       "keepass://", "vault://", "op://", "file://")
RAW_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),                       # AWS temp key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),             # GitHub token
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),           # Slack token
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                    # OpenAI-style key
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"AccountKey=[A-Za-z0-9+/]{20,}={0,2}"),        # Azure conn-string key
    # Added 2026-09-20 with scripts/check-secret-patterns.py, which compares
    # this list with skills/secrets/engine/patterns.py and the table in
    # rules/promote-safety.md. These four were known to one of the three and
    # walked past by this one.
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),            # GitHub fine-grained token
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                   # Google API key
    re.compile(r"\bBearer [-A-Za-z0-9._~+/=]{20,}"),            # an Authorization header, pasted
]

# Opaque base64 credentials — Elastic Cloud ApiKey and the same shape used by
# several other services — carry NO distinctive prefix, so no format regex can
# separate them from ordinary data. They do have one checkable property: the
# blob base64-decodes to `<id>:<secret>`, two non-trivial opaque tokens. The
# decode is what makes this precise enough to run on CODE, where the key:value
# heuristic below is deliberately off — which is exactly the gap that let a live
# `API_KEY = "<base64>"` sit in a tracked .py file (see work/log.md 2026-08-01).
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_ID_SECRET = re.compile(r"\A[A-Za-z0-9_-]{12,}:[A-Za-z0-9_-]{12,}\Z")


def decoded_id_secret(line: str) -> str | None:
    """Return the offending blob if `line` carries a base64 `id:secret` credential.

    Public surface — scripts/tests/test_overlay_secret_scan.py pins the contract.
    Returns None for ordinary base64 payloads (binary, JSON, data URIs): those
    either fail strict base64 validation, fail the ASCII decode, or decode to
    something that is not two opaque colon-separated tokens.
    """
    for blob in _B64_BLOB.findall(line):
        if len(blob) % 4:
            continue
        try:
            decoded = base64.b64decode(blob, validate=True).decode("ascii")
        except (ValueError, UnicodeDecodeError):
            continue
        if _ID_SECRET.match(decoded):
            return blob
    return None


# The SAME credential written out in plaintext. decoded_id_secret above hunts
# base64 BLOBS, which makes it blind to its own quarry once someone pastes the
# decoded pair — and that is not hypothetical: an adversarial pre-publication
# review on 2026-08-01 found the live Elastic key sitting in plaintext in a
# comment in scripts/tests/test_overlay_secret_scan.py, the very test that pins
# this detector, in a file the router had marked publishable to the PUBLIC repo.
# It got there in the same commit that "removed" the key (80196d9): the base64
# form left the script and the plaintext form entered the test explaining it.
#
# No prefix to anchor on, so precision comes from ENTROPY: both halves must mix
# upper, lower and digit, and the pair must stand free (not part of a URL, a
# path, or a `host:port`). Measured over all 2896 tracked text files: exactly
# ONE hit, the synthetic fixture that is supposed to look like a credential —
# zero false positives on real content.
_PLAIN_PAIR = re.compile(
    r"(?<![A-Za-z0-9_./:-])([A-Za-z0-9_-]{16,}):([A-Za-z0-9_-]{16,})(?![A-Za-z0-9_./:-])"
)

#: Inline opt-out for deliberate synthetic fixtures. Standard practice
#: (detect-secrets spells it the same way) — a real secret never carries it.
ALLOWLIST_PRAGMA = "pragma: allowlist secret"


def _entropic(token: str) -> bool:
    return (
        any(c.isupper() for c in token)
        and any(c.islower() for c in token)
        and any(c.isdigit() for c in token)
    )


def plaintext_id_secret(line: str) -> str | None:
    """Return the offending `id:secret` pair if `line` carries one in plaintext.

    Public surface — scripts/tests/test_overlay_secret_scan.py pins the contract.
    """
    if ALLOWLIST_PRAGMA in line:
        return None
    for m in _PLAIN_PAIR.finditer(line):
        if _entropic(m.group(1)) and _entropic(m.group(2)):
            return m.group(0)
    return None
# password:/secret:/token: assignments to a literal that is NOT a URI ref
# Anchored to a YAML-key position (^\s*, optional list dash) so the heuristic
# fires on an actual assignment — not a secret word mid-prose or a trailing
# comment. NOTE the anchor deliberately leaves a secret inside a flow-map
# ({k: v}) or block scalar to the high-precision RAW_SECRET_PATTERNS above
# (which scan the whole line) — un-anchoring would false-positive on every doc
# comment. A placeholder/NAME value is NOT skipped by shape (an ALL-CAPS skip
# would pass base32 TOTP seeds + uppercase-hex keys); only a URI ref or ${var}
# is treated as a non-secret, so placeholders must be expressed as references.
RAW_ASSIGN = re.compile(
    r"(?i)^\s*(?:-\s+)?(password|passwd|passphrase|secret|api[_-]?key|"
    r"client[_-]?secret|token|bearer|credential|webhook[_-]?secret|sas[_-]?token|"
    r"totp[_-]?secret|mfa[_-]?seed|access[_-]?key|private[_-]?key)\b\s*[:=]\s*['\"]?([^\s'\"#]{8,})"
)


class OverlayError(Exception):
    """User-facing, fail-closed error — printed without a traceback."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


def _with_exec(mode: int) -> int:
    """Add x wherever r is set, as `chmod +x` would under the umask."""
    return mode | (((mode & 0o444) >> 2) & ~_umask())


def heal_exec_bit(dest: str, executable: bool) -> None:
    """Give an unchanged mirrored script its exec bit back without rewriting
    it: copies made before writes kept the mode sit at 0600 with the right
    bytes, so no write ever comes along to fix them."""
    if executable and os.path.exists(dest) and not os.access(dest, os.X_OK):
        os.chmod(dest, _with_exec(stat.S_IMODE(os.stat(dest).st_mode)))


def atomic_write_bytes(dest: str, data: bytes, executable: bool = False) -> None:
    """Write `data` to `dest` atomically (temp + os.replace). COPY, never link.

    mkstemp creates the temp file 0600, and os.replace carries that mode over,
    so every write used to land owner-only and a mirrored script lost its exec
    bit. The result now gets the mode a plain write would: an existing file
    keeps its own, a new one follows the umask, and `executable` adds x
    wherever the file is readable."""
    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    if os.path.exists(dest):
        mode = stat.S_IMODE(os.stat(dest).st_mode)
    else:
        mode = 0o666 & ~_umask()
    if executable:
        mode = _with_exec(mode)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".overlay-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_git(args: list[str], cwd: str | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise OverlayError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def load_yaml_file(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise OverlayError(f"malformed YAML in {path}: {exc}")


def dump_yaml(data) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=100)


def prompt_line(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def prompt_yes(msg: str) -> bool:
    return prompt_line(f"{msg} [y/N] ").lower() in ("y", "yes")


# ---------------------------------------------------------------------------
# Glob matching (supports ** across path segments)
# ---------------------------------------------------------------------------

_GLOB_CACHE: dict[str, re.Pattern] = {}


def _glob_to_regex(pattern: str) -> re.Pattern:
    cached = _GLOB_CACHE.get(pattern)
    if cached is not None:
        return cached
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
        elif c in ".[](){}+^$|\\":
            out.append("\\" + c)
        else:
            out.append(c)
        i += 1
    rx = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[pattern] = rx
    return rx


def glob_match(pattern: str, path: str) -> bool:
    return bool(_glob_to_regex(pattern).match(path))


def any_match(patterns, *paths) -> bool:
    """True if ANY pattern matches ANY of the candidate path spellings."""
    for pat in patterns or []:
        for p in paths:
            if glob_match(pat, p):
                return True
    return False


# ---------------------------------------------------------------------------
# JSONPath-lite ($.a.b and $.arr[*].c — whole-array wildcard only)
# ---------------------------------------------------------------------------

def _parse_jsonpath(path: str) -> list[tuple[str, bool]]:
    if not path.startswith("$."):
        raise OverlayError(f"invalid JSONPath-lite (must start with $.): {path}")
    tokens: list[tuple[str, bool]] = []
    for part in path[2:].split("."):
        if not part:
            raise OverlayError(f"invalid JSONPath-lite (empty segment): {path}")
        if part.endswith("[*]"):
            tokens.append((part[:-3], True))
        else:
            tokens.append((part, False))
    return tokens


def jsonpath_refs(data, path: str):
    """Yield (container, key, value) settable refs matched by a JSONPath-lite."""
    tokens = _parse_jsonpath(path)

    def walk(node, toks):
        name, wild = toks[0]
        if not isinstance(node, dict) or name not in node:
            return
        child = node[name]
        if len(toks) == 1:
            if wild and isinstance(child, list):
                for idx in range(len(child)):
                    yield (child, idx, child[idx])
            else:
                yield (node, name, child)
            return
        if wild and isinstance(child, list):
            for item in child:
                yield from walk(item, toks[1:])
        else:
            yield from walk(child, toks[1:])

    yield from walk(data, tokens)


# ---------------------------------------------------------------------------
# Repo / consumer context
# ---------------------------------------------------------------------------

class Consumer:
    """The Bridge instance we materialize INTO."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.config_path = os.path.join(self.root, "bridge-config.yaml")
        self.lock_path = os.path.join(self.root, LOCK_FILE)
        self.claude_md = os.path.join(self.root, "CLAUDE.md")

    # --- branch guard -----------------------------------------------------
    def current_branch(self) -> str | None:
        try:
            proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"],
                           cwd=self.root, check=False)
            if proc.returncode == 0:
                return proc.stdout.strip()
        except OverlayError:
            pass
        return None

    def require_user_branch(self) -> None:
        if os.environ.get("BRIDGE_OVERLAY_ALLOW_ANY_BRANCH") == "1":
            return
        branch = self.current_branch()
        if branch is None:
            raise OverlayError(
                "not a git repo (or detached HEAD) — overlays only materialize "
                "on a user/* branch; CORE branches must stay clean."
            )
        if not branch.startswith("user/"):
            raise OverlayError(
                f"refusing to materialize on '{branch}': overlays only apply on "
                f"a user/* branch (CORE branches never carry org material)."
            )

    # --- bridge-config ----------------------------------------------------
    def load_config(self) -> dict:
        cfg = load_yaml_file(self.config_path)
        if cfg is None:
            return {}
        if not isinstance(cfg, dict):
            raise OverlayError("bridge-config.yaml is not a mapping")
        return cfg

    def write_config(self, cfg: dict) -> None:
        if os.path.exists(self.config_path):
            shutil.copy2(self.config_path, self.config_path + ".bak")
        header = (
            "# yaml-language-server: $schema=./bridge-config.schema.yaml\n"
            "# NOTE: rewritten by scripts/overlay.py — inline comments may be\n"
            "# lost; the prior version is at bridge-config.yaml.bak.\n"
        )
        atomic_write_bytes(self.config_path,
                           (header + dump_yaml(cfg)).encode("utf-8"))

    def org_overlay_upstreams(self, cfg: dict | None = None) -> list[dict]:
        cfg = cfg if cfg is not None else self.load_config()
        return [u for u in (cfg.get("upstreams") or [])
                if isinstance(u, dict) and u.get("role") == "org-overlay"]

    # --- lockfile ---------------------------------------------------------
    def load_lock(self) -> dict:
        lock = load_yaml_file(self.lock_path)
        if lock is None:
            return {"schema_version": 1, "overlays": {}}
        if not isinstance(lock, dict) or "overlays" not in lock:
            raise OverlayError("overlays.lock.yaml is malformed")
        return lock

    def write_lock(self, lock: dict) -> None:
        header = (
            "# yaml-language-server: $schema=./docs/schemas/overlays-lock.schema.yaml\n"
            "# GENERATED by scripts/overlay.py — never hand-edit. scope: user\n"
            "# (gitignored in public forks; names local material paths).\n"
        )
        atomic_write_bytes(self.lock_path,
                           (header + dump_yaml(lock)).encode("utf-8"))

    # --- unattended-run state (derived, gitignored) ------------------------
    def load_unattended(self) -> dict:
        path = os.path.join(self.root, UNATTENDED_STATE)
        try:
            data = load_yaml_file(path)
        except OverlayError:
            return {}
        return data if isinstance(data, dict) else {}

    def write_unattended(self, state: dict) -> None:
        path = os.path.join(self.root, UNATTENDED_STATE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, dump_yaml(state).encode("utf-8"))

    # --- ecosystem @import in CLAUDE.md -----------------------------------
    def ensure_ecosystem_import(self, fragment: str, dry: bool) -> bool:
        token = f"@{fragment}"
        if not os.path.exists(self.claude_md):
            return False
        with open(self.claude_md, encoding="utf-8") as fh:
            text = fh.read()
        if token in text:
            return False
        if dry:
            return True
        lines = text.splitlines(keepends=True)
        out: list[str] = []
        inserted = False
        for ln in lines:
            out.append(ln)
            # Anchor on @AGENTS.md, the one import CLAUDE.md always has. It
            # used to be @ecosystem.yaml, which stopped being an import when
            # the registry became an index (docs/context-index.md); the insert
            # then fell through to its end-of-file fallback, which still works
            # and silently moves the import away from its neighbours. The
            # overlay suite now asserts the placement, so the next anchor to
            # outlive its line says so instead of degrading quietly.
            if not inserted and ln.strip() == "@AGENTS.md":
                out.append(token + "\n")
                inserted = True
        if not inserted:
            if out and not out[-1].endswith("\n"):
                out.append("\n")
            out.append(token + "\n")
        atomic_write_bytes(self.claude_md, "".join(out).encode("utf-8"))
        return True

    def drop_ecosystem_import(self, fragment: str) -> None:
        token = f"@{fragment}"
        if not os.path.exists(self.claude_md):
            return
        with open(self.claude_md, encoding="utf-8") as fh:
            lines = fh.readlines()
        kept = [ln for ln in lines if ln.strip() != token]
        if len(kept) != len(lines):
            atomic_write_bytes(self.claude_md, "".join(kept).encode("utf-8"))

    # --- git-exclude guard for managed dests ------------------------------
    def _exclude_markers(self, overlay_name: str) -> tuple[str, str]:
        return (f"# >>> overlay:{overlay_name} (managed by scripts/overlay.py — do not edit) >>>",
                f"# <<< overlay:{overlay_name} <<<")

    def _strip_marked_block(self, text: str, begin: str, end: str) -> str:
        if begin not in text:
            return text
        out: list[str] = []
        skip = False
        for ln in text.splitlines(keepends=True):
            s = ln.strip()
            if s == begin:
                skip = True
                continue
            if skip:
                if s == end:
                    skip = False
                continue
            out.append(ln)
        return "".join(out)

    def _git_exclude_path(self) -> str | None:
        # The LOCAL, UNTRACKED ignore file (.git/info/exclude) — resolved via
        # rev-parse so it stays correct under worktrees/submodules. We use this
        # rather than .gitignore on purpose: a TRACKED .gitignore would itself
        # publish the managed org filenames on a public fork.
        proc = run_git(["rev-parse", "--git-path", "info/exclude"],
                       cwd=self.root, check=False)
        if proc.returncode != 0:
            return None
        rel = proc.stdout.strip()
        if not rel:
            return None
        return rel if os.path.isabs(rel) else os.path.join(self.root, rel)

    def ensure_git_exclude_block(self, overlay_name: str, dests: list, dry: bool) -> bool:
        """Keep overlay-materialized org content OUT of git. Overlay dests can
        land in TRACKED paths (skills/, .claude/agents/) that no config pattern
        ignores, and a fork of a public repo is itself public — so a `git add -A`
        must not be able to stage them. We write the ignore rules to the LOCAL,
        UNTRACKED .git/info/exclude (never .gitignore): the dests are ignored all
        the same, but no tracked file is touched — so the managed filenames
        themselves can't be published either. Idempotent; dropped on remove."""
        path = self._git_exclude_path()
        if path is None:
            return False
        begin, end = self._exclude_markers(overlay_name)
        body = [begin,
                "# overlay-materialized org content — kept OUT of git so a fork",
                "# (public by default) can't publish it via `git add -A`. This is",
                "# the local, untracked exclude file; dropped on `overlay remove`.",
                *(f"/{d}" for d in sorted(set(dests))),
                end]
        block = "\n".join(body) + "\n"
        existing = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                existing = fh.read()
        stripped = self._strip_marked_block(existing, begin, end)
        if stripped and not stripped.endswith("\n"):
            stripped += "\n"
        new = stripped + ("\n" if stripped.strip() else "") + block
        if new == existing:
            return False
        if dry:
            return True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, new.encode("utf-8"))
        return True

    def drop_git_exclude_block(self, overlay_name: str, dry: bool = False) -> bool:
        path = self._git_exclude_path()
        if path is None or not os.path.exists(path):
            return False
        begin, end = self._exclude_markers(overlay_name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        new = self._strip_marked_block(text, begin, end)
        if new == text:
            return False
        if dry:
            return True
        atomic_write_bytes(path, new.encode("utf-8"))
        return True

    # --- fleet record -----------------------------------------------------
    def self_instance_path(self) -> str | None:
        inst_dir = os.path.join(self.root, "infra", "instances")
        if not os.path.isdir(inst_dir):
            return None
        for name in sorted(os.listdir(inst_dir)):
            if name.startswith("_") or not name.endswith(".yaml"):
                continue
            data = load_yaml_file(os.path.join(inst_dir, name))
            if isinstance(data, dict) and data.get("relationship") == "self":
                return os.path.join(inst_dir, name)
        return None

    def record_subscription(self, overlay_name: str, dry: bool) -> str | None:
        inst = self.self_instance_path()
        if inst is None:
            return None
        data = load_yaml_file(inst) or {}
        subs = data.get("subscribes_overlays")
        if not isinstance(subs, list):
            subs = []
        if overlay_name in subs:
            return inst
        subs.append(overlay_name)
        data["subscribes_overlays"] = subs
        if not dry:
            atomic_write_bytes(inst, dump_yaml(data).encode("utf-8"))
        return inst

    def unrecord_subscription(self, overlay_name: str) -> None:
        inst = self.self_instance_path()
        if inst is None:
            return
        data = load_yaml_file(inst) or {}
        subs = data.get("subscribes_overlays")
        if isinstance(subs, list) and overlay_name in subs:
            subs.remove(overlay_name)
            data["subscribes_overlays"] = subs
            atomic_write_bytes(inst, dump_yaml(data).encode("utf-8"))


# ---------------------------------------------------------------------------
# Cache (sparse partial clone with full-clone fallback)
# ---------------------------------------------------------------------------

def cache_dir(consumer: Consumer, name: str) -> str:
    return os.path.join(consumer.root, CACHE_BASE, name)


def ensure_cache(consumer: Consumer, name: str, url: str, ref: str,
                 source_root: str) -> str:
    """Clone (sparse, blob-filtered) or update the overlay cache. Returns path."""
    cache = cache_dir(consumer, name)
    if os.path.isdir(os.path.join(cache, ".git")):
        update_cache(cache, ref)
        return cache
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if os.path.exists(cache):
        shutil.rmtree(cache)
    # Try sparse partial clone first; fall back to a full clone if the remote
    # (or git build) does not support partial clone / sparse-checkout.
    proc = run_git(
        ["clone", "--filter=blob:none", "--sparse", "--no-checkout", url, cache],
        check=False,
    )
    if proc.returncode == 0:
        cone = source_root.rstrip("/") or "."
        sc = run_git(["sparse-checkout", "set", "--cone", cone],
                     cwd=cache, check=False)
        co = run_git(["checkout", ref], cwd=cache, check=False)
        if sc.returncode == 0 and co.returncode == 0:
            return cache
        # partial worked but sparse/checkout didn't — fall through to full
        shutil.rmtree(cache, ignore_errors=True)
    # Full-clone fallback.
    run_git(["clone", url, cache])
    run_git(["checkout", ref], cwd=cache, check=False)
    return cache


def update_cache(cache: str, ref: str) -> None:
    run_git(["fetch", "--all", "--prune"], cwd=cache, check=False)
    # widen sparse set defensively in case source_root changed
    co = run_git(["checkout", ref], cwd=cache, check=False)
    if co.returncode != 0:
        # ref may be remote-only
        run_git(["checkout", "-B", ref, f"origin/{ref}"], cwd=cache, check=False)
    run_git(["pull", "--ff-only"], cwd=cache, check=False)


def resolved_sha(cache: str) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=cache).stdout.strip()


def git_show_blob(cache: str, sha: str, src: str) -> bytes | None:
    """Recover a historical blob (3-way base). None if GC'd / unavailable."""
    proc = subprocess.run(
        ["git", "-C", cache, "show", f"{sha}:{src}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def merge_base_blob(cache: str, old_sha: str | None, src: str,
                    want_sha256: str | None = None) -> bytes | None:
    """The 3-way base for one file: its source at the version last applied.

    That is normally the blob at the overlay-wide pin. A file held at the
    behavioural gate keeps its old lock entry while the pin moves on, and the
    blob at the new pin is then the upstream side itself: merging against it
    returns the live file as a "clean" merge and drops the upstream change.
    The lock entry's source hash names the version that was applied, so when
    the pinned blob does not match it, the base is looked up in history."""
    base = git_show_blob(cache, old_sha, src) if old_sha else None
    if not want_sha256 or (base is not None and sha256_bytes(base) == want_sha256):
        return base
    proc = subprocess.run(
        ["git", "-C", cache, "log", "--format=%H", old_sha or "HEAD", "--", src],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    for sha in proc.stdout.split() if proc.returncode == 0 else []:
        blob = git_show_blob(cache, sha, src)
        if blob is not None and sha256_bytes(blob) == want_sha256:
            return blob
    return base


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def read_manifest(cache: str) -> tuple[dict, str]:
    path = os.path.join(cache, MANIFEST_FILE)
    if not os.path.exists(path):
        raise OverlayError(f"overlay has no {MANIFEST_FILE} at its root")
    size = os.path.getsize(path)
    if size == 0:
        raise OverlayError(f"{MANIFEST_FILE} is empty")
    if size > MAX_MANIFEST_BYTES:
        raise OverlayError(
            f"{MANIFEST_FILE} is suspiciously large ({size} bytes) — refusing"
        )
    manifest = load_yaml_file(path)
    if not isinstance(manifest, dict):
        raise OverlayError(f"{MANIFEST_FILE} is not a mapping")
    digest = sha256_file(path)
    return manifest, digest


FRAGMENT_NAME_RE = re.compile(r"^ecosystem\.[a-z][a-z0-9-]*\.yaml$")


def valid_fragment_name(frag: object) -> bool:
    """An ecosystem fragment must be a flat `ecosystem.<org>.yaml` at the repo
    root. This forecloses traversal / `_`-prefix / subdir / arbitrary-name writes
    that would otherwise reach `os.path.join(consumer.root, fragment)` plus a
    CLAUDE.md @import. Enforced in-engine so it holds even on a consumer WITHOUT
    the optional check-jsonschema. See test-overlay.sh §22."""
    return isinstance(frag, str) and bool(FRAGMENT_NAME_RE.match(frag))


def validate_manifest(cache: str) -> None:
    schema = os.path.join(SCRIPT_DIR, "..", "docs", "schemas",
                          "overlay-manifest.schema.yaml")
    schema = os.path.normpath(schema)
    manifest = os.path.join(cache, MANIFEST_FILE)
    # In-engine guard that must hold regardless of check-jsonschema availability:
    # a declared ecosystem_fragment must be a flat ecosystem.<org>.yaml name.
    _mdata = load_yaml_file(manifest)
    if isinstance(_mdata, dict):
        _frag = _mdata.get("ecosystem_fragment")
        if _frag is not None and not valid_fragment_name(_frag):
            raise OverlayError(
                f"ecosystem_fragment '{_frag}' is not a valid 'ecosystem.<org>.yaml' "
                f"name (no traversal / subdir / arbitrary names)")
    if shutil.which("check-jsonschema") and os.path.exists(schema):
        proc = subprocess.run(
            ["check-jsonschema", "--schemafile", schema, manifest],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if proc.returncode != 0:
            raise OverlayError(
                "overlay manifest failed schema validation:\n" + proc.stdout
            )
        return
    # Stdlib structural fallback.
    data = load_yaml_file(manifest)
    if not isinstance(data, dict):
        raise OverlayError("manifest is not a mapping")
    if data.get("schema_version") != 1:
        raise OverlayError("manifest schema_version must be 1")
    ov = data.get("overlay")
    if not isinstance(ov, dict) or not ov.get("name") or not ov.get("org"):
        raise OverlayError("manifest.overlay must carry name + org")
    if not re.match(r"^[a-z][a-z0-9-]*$", str(ov["name"])):
        raise OverlayError("manifest.overlay.name must be lowercase-kebab")


def manifest_defaults(manifest: dict) -> dict:
    d = (manifest.get("defaults") or {})
    return {
        "scope": d.get("scope", "org"),
        "source_root": d.get("source_root", DEFAULT_SOURCE_ROOT),
        "on_conflict": d.get("on_conflict", "prompt"),
    }


# ---------------------------------------------------------------------------
# Dest classification + refusal gate (step 5)
# ---------------------------------------------------------------------------

CLUSTER_WRAPPERS = ("identity/", "infra/", "workflow/")

# Paths where the framework treats frontmatter `scope:` as authoritative
# (classify_file reads frontmatter ONLY for these). Inline/resolved scope may
# RESCUE a core-classified dest here — and ONLY here. Everywhere else path
# classification is final, so a `scope: org` line in overlay-controlled content
# cannot smuggle a CORE file (rules/, docs/, scripts/, CLAUDE.md, themes/,
# protocols/standing-orders/*, …) past the gate. See test-overlay.sh §21.
FRONTMATTER_SCOPED = (
    re.compile(r"^skills/[^/]+/"),
    re.compile(r"^\.claude/agents/[^/]+\.md$"),
    re.compile(r"^identity/agent/(IDENTITY|SOUL)\.md$"),
)


def staged_scope(content: bytes) -> str | None:
    """Read inline scope (top-level or metadata.scope) from staged file bytes."""
    try:
        head = content[:4000].decode("utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r"^---\s*\n(.*?)\n---", head, re.DOTALL | re.MULTILINE)
    block = m.group(1) if m else head
    sm = re.search(r"^scope:\s*([a-z]+)", block, re.MULTILINE)
    if sm:
        return sm.group(1)
    mb = re.search(r"^metadata:[ \t]*\n((?:[ \t]+.*\n?)*)", block, re.MULTILINE)
    if mb:
        ms = re.search(r"^[ \t]+scope:\s*([a-z]+)", mb.group(1), re.MULTILINE)
        if ms:
            return ms.group(1)
    return None


def skill_dir_scope(cache: str, source_root: str, dest: str) -> str | None:
    """Tier of a file UNDER a skill dir, resolved from that skill's SOURCE
    SKILL.md. A skill's scripts/ + assets/ carry no inline scope, and
    classify_file reads the sibling SKILL.md relative to the CONSUMER root —
    absent during a fresh add — so it would default to CORE and the script would
    be refused, materializing the skill WITHOUT its scripts. The source SKILL.md
    (already in the overlay cache) carries the real scope, so a `scope:org` skill
    ships COMPLETE."""
    m = re.match(r"^skills/([^/]+)/(.+)$", dest)
    if not m or m.group(2) == "SKILL.md":
        return None
    md = os.path.join(cache, source_root.rstrip("/"), "skills", m.group(1), "SKILL.md")
    try:
        with open(md, "rb") as fh:
            return staged_scope(fh.read())
    except OSError:
        return None


def dest_refusal(dest: str, content: bytes, consumer: Consumer,
                 lock: dict, overlay_name: str, precedence: int,
                 resolved_scope: str | None = None) -> str | None:
    """Return a refusal reason for `dest`, or None if it may be materialized."""
    # Path traversal — dest must resolve strictly under the repo root.
    if os.path.isabs(dest) or dest.startswith("~"):
        return "absolute path"
    resolved = os.path.normpath(os.path.join(consumer.root, dest))
    if resolved != consumer.root and not resolved.startswith(consumer.root + os.sep):
        return "escapes repo root"
    base = os.path.basename(dest)
    # Reserved `_`-prefix (templates, schemas, state).
    if base.startswith("_"):
        return "reserved _-prefixed file"
    # Cluster-wrapper README is CORE.
    if base == "README.md" and dest.startswith(CLUSTER_WRAPPERS):
        return "cluster-wrapper README (CORE)"
    # Effective scope. Path classification is AUTHORITATIVE for a CORE dest:
    # inline/resolved scope may only rescue it on a frontmatter-bearing path
    # (skills/agents/identity), where the framework reads frontmatter anyway —
    # otherwise a `scope: org` line in overlay-controlled content could smuggle a
    # CORE file past the gate and overwrite it. (test-overlay.sh §21)
    path_class = classify_file(dest)
    if path_class == "core" and not any(p.match(dest) for p in FRONTMATTER_SCOPED):
        return "classifies CORE (org overlays never ship CORE files)"
    scope = staged_scope(content) or resolved_scope or path_class
    if scope == "core":
        return "classifies CORE (org overlays never ship CORE files)"
    # Ownership across overlays — a lower-precedence overlay cannot override a
    # dest already owned by a higher-precedence one.
    for other_name, entry in (lock.get("overlays") or {}).items():
        if other_name == overlay_name:
            continue
        other_prec = entry.get("precedence", 0)
        for f in entry.get("files", []):
            if f.get("dest") == dest and other_prec > precedence:
                return (f"owned by overlay '{other_name}' at higher precedence "
                        f"{other_prec} > {precedence}")
    return None


# ---------------------------------------------------------------------------
# Leak gate (step 9)
# ---------------------------------------------------------------------------

def leak_check(content: bytes, target_scope: str = "org", dest: str = "") -> list[str]:
    """Return a list of leak reasons; empty == clean.

    The no-scrub-leak scanner answers a CORE-boundary question ("would this leak
    into public core?"). That is the wrong layer for overlay materialization: an
    overlay legitimately lands org content — team names, org emails — into a
    consumer's org/user tier. The public-leak boundary is enforced where it
    belongs: at PUSH time (the consumer's pre-push guard) and by scope tiering
    (org/user never reach a core/public upstream); CORE dests are already refused
    upstream at Gate 1. So the core scanner runs ONLY when the materialize target
    is itself `core` (which overlays never do). The raw-secret regex runs
    unconditionally — a raw secret is never written to disk, even privately.
    """
    reasons: list[str] = []
    # 1) core-boundary scanner (no-scrub-leak) — only when writing a CORE file.
    if target_scope == "core":
        fd, tmp = tempfile.mkstemp(prefix="overlay-leak-", suffix=".yaml")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
            proc = subprocess.run(
                [sys.executable, NO_SCRUB_LEAK, tmp],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            if proc.returncode == 1:
                detail = (proc.stderr or proc.stdout).strip().splitlines()
                reasons.append("no-scrub-leak: " + "; ".join(
                    ln.strip() for ln in detail if ln.strip())[:400])
            elif proc.returncode not in (0, 1):
                reasons.append(f"no-scrub-leak gate errored (exit {proc.returncode})")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    # 2) raw-secret scan. High-precision format patterns scan the whole line (a
    #    real key is a leak even in a comment). The generic key:value heuristic
    #    only fires on an actual YAML assignment — never a prose mention, a
    #    trailing comment, a documented secret NAME, or an all-caps placeholder —
    #    which would otherwise false-positive on the doc comments that fill real
    #    org config.
    text = content.decode("utf-8", errors="ignore")
    # The generic key=value heuristic is for config (YAML/env/properties). Code
    # files assign secret-named variables from EXPRESSIONS (api_key = get_key(),
    # token = os.environ[...]) that are not literals — running the heuristic there
    # only false-positives. Code still gets the high-precision format scan, which
    # catches a real key (AKIA…, ghp_…) wherever it appears.
    is_code = dest.endswith((
        ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".go", ".rb", ".rs",
        ".java", ".kt", ".c", ".h", ".cpp", ".cs", ".php", ".sh", ".bash",
        ".zsh", ".ps1", ".psm1", ".lua", ".pl", ".swift", ".sql"))
    for raw_line in text.splitlines():
        hit = None
        for pat in RAW_SECRET_PATTERNS:
            if pat.search(raw_line):
                hit = raw_line.strip()[:60]
                break
        if hit is None:
            blob = decoded_id_secret(raw_line)
            if blob:
                hit = f"base64 id:secret credential {blob[:20]}…"
        if hit is None:
            # Deliberately on the RAW line, BEFORE the comment strip below: the
            # real find was inside a `#` comment, which the assignment heuristic
            # discards. Only the first 8 chars are echoed — a reason string that
            # quotes the whole pair re-materializes the secret in the log that
            # was supposed to stop it.
            pair = plaintext_id_secret(raw_line)
            if pair:
                hit = f"plaintext id:secret credential {pair[:8]}… (redacted)"
        if hit:
            reasons.append(f"raw secret material: {hit}")
        if is_code:
            continue                                # format scan only on code
        code = raw_line.split("#", 1)[0]            # drop trailing comment
        m = RAW_ASSIGN.search(code)
        if not m:
            continue
        value = m.group(2)
        # URI ref, ${var}, or a function-call/expression (has `(`) is not a literal.
        if value.startswith(SECRET_URI_PREFIXES) or "${" in value or "(" in value:
            continue
        reasons.append(f"raw secret assignment: {code.strip()[:60]}")
    return reasons


# ---------------------------------------------------------------------------
# Scope tripwire (step 10)
# ---------------------------------------------------------------------------

def inject_scope_tripwire(dest: str, content: bytes, kind: str,
                          scope: str = "org") -> bytes:
    """Ensure an inline scope marker is present. Returns possibly-edited bytes."""
    if staged_scope(content) is not None:
        return content
    text = content.decode("utf-8", errors="ignore")
    if kind == "skill":
        # skills carry metadata.scope — leave behavioural files to the human if
        # we cannot place it safely; only inject when a metadata: block exists.
        if re.search(r"^metadata:[ \t]*$", text, re.MULTILINE):
            text = re.sub(r"^(metadata:[ \t]*\n)",
                          r"\1  scope: " + scope + "\n", text, count=1,
                          flags=re.MULTILINE)
            return text.encode("utf-8")
        return content
    # YAML / frontmatter files: inject a top-level scope into a `---` block if
    # present, else prepend a top-level key for plain YAML.
    m = re.search(r"^---\s*\n", text)
    if m:
        text = text[:m.end()] + f"scope: {scope}\n" + text[m.end():]
        return text.encode("utf-8")
    if dest.endswith((".yaml", ".yml")) and "scope:" not in text:
        return (f"scope: {scope}\n" + text).encode("utf-8")
    return content


# ---------------------------------------------------------------------------
# Prompt-field injection (step 8)
# ---------------------------------------------------------------------------

def inject_prompt_fields(content: bytes, prompt_fields: list[dict],
                         interactive: bool,
                         existing: bytes | None = None) -> tuple[bytes, list[str]]:
    """Inject prompt-field values into the staged content.

    Interactive: prompt the human. Non-interactive (--yes / apply / re-sync):
    preserve any existing on-disk override at the field's path rather than
    reverting to the shipped source default — so a teammate's customized board
    number / recipient email survives a re-sync (Gate 2: never a silent clobber).
    A fresh add has no existing file, so the source default stands.

    Returns (possibly-edited bytes, list-of-prompted/preserved PATHS). The lock
    records PATHS only, never the value.
    """
    if not prompt_fields:
        return content, []
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return content, []  # not YAML — nothing to inject
    if not isinstance(data, (dict, list)):
        return content, []
    edata = None
    if existing is not None:
        try:
            ed = yaml.safe_load(existing)
            edata = ed if isinstance(ed, (dict, list)) else None
        except yaml.YAMLError:
            edata = None
    prompted: list[str] = []
    changed = False
    for pf in prompt_fields:
        path = pf.get("path")
        reason = pf.get("reason", "")
        pii = bool(pf.get("pii", False))
        if not path:
            continue
        try:
            refs = list(jsonpath_refs(data, path))
        except OverlayError:
            continue
        if not refs:
            continue
        if not interactive:
            # Non-interactive (--yes / apply / re-sync): preserve an existing
            # on-disk override at this path instead of reverting to the source
            # default (Gate 2 — no silent clobber). SCALAR paths ONLY: a path
            # that resolves to exactly one leaf can be recovered from disk
            # unambiguously. A wildcard [*] path resolves to many leaves whose
            # only cross-reference to the on-disk file is list POSITION, and the
            # lock stores PATHS only (never the value), so a reordered/resized
            # upstream list would map an override onto the WRONG element (e.g. a
            # recipient email onto the wrong person). A multi-valued override is
            # therefore NOT positionally restored: while the source is unchanged
            # the file is skipped untouched (discriminator), and a source-side
            # change resets it to the source value — re-run interactively to
            # re-apply. A fresh add has no existing file, so the default stands.
            if edata is not None and len(refs) == 1:
                try:
                    erefs = list(jsonpath_refs(edata, path))
                except OverlayError:
                    erefs = []
                if len(erefs) == 1:
                    container, key, current = refs[0]
                    _, _, eprev = erefs[0]
                    if eprev is not None and eprev != current:
                        container[key] = eprev
                        changed = True
                        prompted.append(path)
            continue
        recorded = False
        for container, key, current in refs:
            label = f"  overlay field {path}"
            print(f"{label}\n    reason: {reason}")
            if pii:
                new = getpass.getpass("    value (hidden, blank=keep): ").strip()
            else:
                new = prompt_line(f"    value (current={current!r}, blank=keep): ")
            if new:
                container[key] = new
                changed = True
                recorded = True
        if recorded:
            prompted.append(path)
    if not changed:
        return content, prompted
    return dump_yaml(data).encode("utf-8"), prompted


# ---------------------------------------------------------------------------
# File plan (steps 4–7)
# ---------------------------------------------------------------------------

#: The overlay's ecosystem fragment, planned like a tree file (step 13).
FRAGMENT_KIND = "ecosystem-fragment"


class PlanItem:
    __slots__ = ("src", "dest", "kind", "prompt_fields", "on_conflict",
                 "source_bytes", "source_sha", "state", "reason",
                 "staged_bytes", "materialized_sha", "prompted_fields",
                 "source_executable")

    def __init__(self, src, dest, kind, prompt_fields, on_conflict):
        self.src = src
        self.dest = dest
        self.kind = kind
        self.prompt_fields = prompt_fields
        self.on_conflict = on_conflict
        self.source_bytes = b""
        self.source_sha = ""
        self.state = "pending"
        self.reason = ""
        self.staged_bytes = b""
        self.materialized_sha = ""
        self.prompted_fields: list[str] = []
        self.source_executable = False


def gate_unit(dest: str) -> str:
    """The unit the behavioural gate confirms: a skill folder as a whole
    (`skills/<name>/`), any other behavioural file on its own."""
    parts = dest.split("/")
    if len(parts) >= 3 and parts[0] == "skills":
        return f"skills/{parts[1]}/"
    return dest


# Plan states that change a file on disk, and so can be held at the gate.
GATE_HELD_STATES = ("clean-new", "user-owned", "upstream-ahead", "local-edit")


def gated_units(items: list["PlanItem"], known: set[str]) -> dict[str, list["PlanItem"]]:
    """Behavioural units that need a person's [y] on this run.

    Maps each unit (see gate_unit) to every file of it the run would change. A
    unit is gated when one of its files arrives for the first time, i.e. is not
    in the lock (`known`). The unit's other changes are held with it: a skill is
    a folder, and its SKILL.md routes into references/, so asking per file let a
    run without a person apply a SKILL.md while it skipped the new reference
    the SKILL.md points at. All or none keeps a skill whole."""
    units: dict[str, list[PlanItem]] = {}
    for it in items:
        if it.kind in BEHAVIOURAL_KINDS and it.state in GATE_HELD_STATES:
            units.setdefault(gate_unit(it.dest), []).append(it)
    return {u: m for u, m in units.items() if any(it.dest not in known for it in m)}


def held_prune(prune: list[dict], units: dict[str, list["PlanItem"]]) -> dict[str, list[dict]]:
    """Prune entries that belong to a gated unit, by unit: they wait with it."""
    out: dict[str, list[dict]] = {}
    for pr in prune:
        u = gate_unit(pr["dest"])
        if u in units:
            out.setdefault(u, []).append(pr)
    return out


def infer_kind(dest: str) -> str:
    if dest.startswith("skills/"):
        return "skill"
    if re.match(r"^\.claude/agents/", dest):
        return "agent"
    if dest.startswith("protocols/standing-orders/"):
        return "standing-order"
    if dest.startswith("rules/"):
        return "rule"
    return "config"


def expand_selection(cache: str, source_root: str, manifest: dict,
                     materialize_select: list[str]) -> list[PlanItem]:
    sel = (manifest.get("selection") or {})
    include = sel.get("include") or ["**"]
    exclude = sel.get("exclude") or []
    files_exc = {f["dest"]: f for f in (manifest.get("files") or [])
                 if isinstance(f, dict) and f.get("dest")}
    src_dir = os.path.join(cache, source_root.rstrip("/"))
    if not os.path.isdir(src_dir):
        raise OverlayError(f"source_root '{source_root}' not found in overlay")
    items: list[PlanItem] = []
    seen: set[str] = set()
    sroot = source_root  # e.g. 'tree/'
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            abs_src = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_src, src_dir).replace(os.sep, "/")
            full = sroot + rel  # path-with-source_root spelling
            if not any_match(include, rel, full):
                continue
            if any_match(exclude, rel, full):
                continue
            if materialize_select and not any_match(materialize_select, rel, full):
                continue
            dest = rel  # strip source_root → dest relative to repo root
            if dest in seen:
                continue
            seen.add(dest)
            exc = files_exc.get(dest, {})
            kind = exc.get("kind") or infer_kind(dest)
            items.append(PlanItem(
                src=full,
                dest=dest,
                kind=kind,
                prompt_fields=exc.get("prompt_fields") or [],
                on_conflict=exc.get("on_conflict"),
            ))
    # files[] exceptions whose dest was not produced by the walk (explicit add
    # for a file the walk's include/exclude legitimately missed) — this must
    # NOT be a backdoor around materialize_select: a dest the walk saw but
    # explicitly excluded because the CONSUMER's own select doesn't cover it
    # (line 1147 above) still has a `files_exc` metadata entry (kind/
    # prompt_fields overrides are declared for most/all dests in a small
    # overlay), stays out of `seen`, and would slip back in here unfiltered —
    # silently ignoring a narrowed `select:` for exactly the files it was
    # narrowed to exclude. Apply the same three gates as the walk.
    for dest, exc in files_exc.items():
        if dest in seen:
            continue
        abs_src = os.path.join(src_dir, dest)
        if not os.path.exists(abs_src):
            continue
        full = sroot + dest
        if not any_match(include, dest, full):
            continue
        if any_match(exclude, dest, full):
            continue
        if materialize_select and not any_match(materialize_select, dest, full):
            continue
        seen.add(dest)
        items.append(PlanItem(
            src=sroot + dest,
            dest=dest,
            kind=exc.get("kind") or infer_kind(dest),
            prompt_fields=exc.get("prompt_fields") or [],
            on_conflict=exc.get("on_conflict"),
        ))
    items.sort(key=lambda it: it.dest)
    return items


def build_plan(consumer: Consumer, cache: str, manifest: dict, defaults: dict,
               materialize_select: list[str], overlay_name: str,
               precedence: int, lock: dict, old_resolved_sha: str | None,
               interactive: bool) -> tuple[list[PlanItem], list[dict]]:
    """Compute per-file plan + the prune list. Stages bytes but writes nothing."""
    source_root = defaults["source_root"]
    default_conflict = defaults["on_conflict"]
    scope = defaults.get("scope", "org")
    items = expand_selection(cache, source_root, manifest, materialize_select)

    # Step 13, the ecosystem fragment, is a managed file like any other: lock
    # entry, 3-way merge on a local edit, a line in diff and --dry-run, a
    # clean-only delete. It lives at the overlay ROOT rather than under
    # source_root, is copied verbatim and is not narrowed by `select:`. It used
    # to be copied outside the plan on every run, which silently dropped a
    # consumer's own registry entries.
    fragment = manifest.get("ecosystem_fragment")
    if (fragment and valid_fragment_name(fragment)
            and os.path.isfile(os.path.join(cache, fragment))
            and not any(it.dest == fragment for it in items)):
        items.append(PlanItem(src=fragment, dest=fragment, kind=FRAGMENT_KIND,
                              prompt_fields=[], on_conflict=None))

    lock_entry = (lock.get("overlays") or {}).get(overlay_name, {})
    lock_files = {f["dest"]: f for f in lock_entry.get("files", [])
                  if isinstance(f, dict) and f.get("dest")}
    # A lock written by an engine that plans the fragment says so. Without that
    # marker a missing fragment entry is ambiguous: a pre-fix lock (whose engine
    # wrote the fragment on every run) and a consumer's own registry that this
    # engine skipped as user-owned look exactly the same.
    legacy_fragment_lock = (bool(old_resolved_sha)
                            and not lock_entry.get("fragment_managed"))

    planned_dests: set[str] = set()

    for it in items:
        if it.kind == FRAGMENT_KIND:
            abs_src = os.path.join(cache, it.src)   # overlay root, not source_root
        else:
            abs_src = os.path.join(cache, source_root.rstrip("/"), it.dest)
        try:
            with open(abs_src, "rb") as fh:
                it.source_bytes = fh.read()
            it.source_executable = os.access(abs_src, os.X_OK)
        except OSError as exc:
            it.state = "error"
            it.reason = f"cannot read source: {exc}"
            continue
        it.source_sha = sha256_bytes(it.source_bytes)

        # Existing on-disk content — passed to prompt-field injection so a
        # non-interactive re-sync preserves a teammate's override instead of
        # reverting to the source default (only for an already-managed file;
        # a fresh add keeps the shipped default).
        dest_abs = os.path.join(consumer.root, it.dest)
        existing = None
        if it.dest in lock_files and os.path.exists(dest_abs):
            try:
                with open(dest_abs, "rb") as fh:
                    existing = fh.read()
            except OSError:
                existing = None
        # Stage: scope tripwire + prompt-field injection. The fragment stays
        # verbatim, as it always was: it is a registry, not a tiered config file.
        if it.kind == FRAGMENT_KIND:
            staged, prompted = it.source_bytes, []
        else:
            staged = inject_scope_tripwire(it.dest, it.source_bytes, it.kind, scope)
            staged, prompted = inject_prompt_fields(staged, it.prompt_fields,
                                                    interactive, existing)
        it.staged_bytes = staged
        it.materialized_sha = sha256_bytes(staged)
        it.prompted_fields = prompted

        # Step 5 — CORE / structural / ownership refusal. A skill's non-frontmatter
        # files (scripts/assets) inherit the tier of their source SKILL.md so a
        # scope:org skill ships COMPLETE, not just its markdown.
        refusal = dest_refusal(it.dest, staged, consumer, lock, overlay_name,
                               precedence, skill_dir_scope(cache, source_root, it.dest))
        if refusal:
            it.state = "core-refused"
            it.reason = refusal
            continue

        # Step 9 — leak gate (before any write). Org/user materialization keeps
        # only the raw-secret check; the core-boundary scan runs at push time.
        leaks = leak_check(staged, scope, it.dest)
        if leaks:
            it.state = "leak-refused"
            it.reason = "; ".join(leaks)[:300]
            continue

        planned_dests.add(it.dest)
        dest_abs = os.path.join(consumer.root, it.dest)
        on_disk = os.path.exists(dest_abs)
        in_lock = it.dest in lock_files

        if not in_lock:
            if (on_disk and it.kind == FRAGMENT_KIND and legacy_fragment_lock
                    and old_resolved_sha):
                # A lock from before the fragment was managed has no entry for
                # it, but that engine wrote the overlay's fragment verbatim at
                # the pinned SHA on every run. That blob is therefore the last
                # copy the overlay wrote: equal means untouched, different means
                # the consumer edited it. Adopt it on that basis instead of
                # treating the file as user-owned (which a non-interactive sync
                # would skip forever) or overwriting it (the original loss).
                base = git_show_blob(cache, old_resolved_sha, it.src)
                live_sha = sha256_file(dest_abs)
                if base is None:
                    # The pinned blob is gone (a force-pushed overlay, a
                    # re-cloned cache). Equal to the new source is untouched;
                    # anything else goes the local-edit way: with no base the
                    # 3-way step keeps the file and reports a conflict, and the
                    # lock takes the overlay's current version as the base.
                    it.state = "skip" if live_sha == it.source_sha else "local-edit"
                elif live_sha != sha256_bytes(base):
                    it.state = "local-edit"
                elif it.source_sha == sha256_bytes(base):
                    it.state = "skip"
                else:
                    it.state = "upstream-ahead"
                continue
            it.state = "user-owned" if on_disk else "clean-new"
            continue

        lf = lock_files[it.dest]
        prev_mat = lf.get("materialized_sha256")
        prev_src = lf.get("source_sha256")
        live_sha = sha256_file(dest_abs) if on_disk else None

        if not on_disk:
            it.state = "clean-new"  # was materialized, user deleted → restore
            continue
        if live_sha == prev_mat:
            # Source unchanged ⇒ nothing upstream to apply: keep the on-disk file
            # (which carries any prompt-field override) + the lock entry. We do
            # NOT also require materialized_sha == prev_mat: a non-interactive
            # re-sync does not re-inject prompts, so the recomputed materialized
            # hash reverts to the source default — treating that as upstream-ahead
            # would silently clobber a teammate's override (violates Gate 2).
            if it.source_sha == prev_src:
                it.state = "skip"            # idempotent — source unchanged
            else:
                it.state = "upstream-ahead"  # source moved, local untouched
            continue
        # live != materialized → local edit
        it.state = "local-edit"

    # Prune: in lock but absent from new plan.
    prune: list[dict] = []
    for dest, lf in lock_files.items():
        if dest in planned_dests:
            continue
        dest_abs = os.path.join(consumer.root, dest)
        clean = (os.path.exists(dest_abs)
                 and sha256_file(dest_abs) == lf.get("materialized_sha256"))
        prune.append({"dest": dest, "src": lf.get("src"),
                      "clean": clean, "present": os.path.exists(dest_abs)})
    return items, prune


# ---------------------------------------------------------------------------
# 3-way merge for local edits (step 7)
# ---------------------------------------------------------------------------

def three_way(consumer: Consumer, cache: str, it: PlanItem,
              old_sha: str | None, interactive: bool,
              base_source_sha: str | None = None) -> tuple[bytes | None, str]:
    """Resolve a locally-edited file against new upstream. Returns (bytes,state).

    `base_source_sha` is the file's lock-entry source hash; see merge_base_blob."""
    dest_abs = os.path.join(consumer.root, it.dest)
    with open(dest_abs, "rb") as fh:
        live = fh.read()
    base = merge_base_blob(cache, old_sha, it.src, base_source_sha)
    if base is not None:
        with tempfile.TemporaryDirectory() as td:
            p_live = os.path.join(td, "live")
            p_base = os.path.join(td, "base")
            p_new = os.path.join(td, "new")
            for p, b in ((p_live, live), (p_base, base),
                         (p_new, it.staged_bytes)):
                with open(p, "wb") as fh:
                    fh.write(b)
            proc = subprocess.run(
                ["git", "merge-file", "-p", p_live, p_base, p_new],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if proc.returncode == 0:
                return proc.stdout, "merged-clean"
            # conflict markers present
    # 2-way fallback / conflict: prompt.
    if not interactive:
        return None, "conflict"
    print(f"\n  CONFLICT on locally-modified {it.dest}")
    print("    [k] keep local   [u] take upstream   [s] skip")
    choice = prompt_line("    choose: ").lower()
    if choice == "u":
        return it.staged_bytes, "conflict-resolved-upstream"
    if choice == "k":
        return None, "conflict-kept-local"
    return None, "conflict-skipped"


# ---------------------------------------------------------------------------
# Materialize (write phase, steps 11–16)
# ---------------------------------------------------------------------------

def wire_ecosystem_import(consumer: Consumer, manifest: dict, items: list,
                          dry: bool):
    """Step 13: the @import for a declared ecosystem fragment, or why not.

    Shared by materialize and the --dry-run plan, so the plan reports the same
    decision the real run makes. Returns the validated fragment name (or None),
    which the git-exclude guard after it needs.
    """
    # The fragment's bytes went through the plan like any managed file; what
    # is left here is the @import wiring, and a warning
    # for a declared fragment the plan could not carry.
    fragment = manifest.get("ecosystem_fragment")
    if fragment and not valid_fragment_name(fragment):
        # Defense-in-depth: validate_manifest already rejects this at add, and
        # build_plan never plans it, but guard the @import too so sync/apply can
        # never wire an out-of-name fragment (traversal / arbitrary name).
        sys.stderr.write(
            f"  REFUSE ecosystem_fragment '{fragment}': not a valid "
            f"ecosystem.<org>.yaml name\n")
        fragment = None
    if fragment:
        # By dest, not by kind: an overlay that also ships the file under
        # source_root plans it as a tree file, and the @import is still due.
        frag_item = next((it for it in items if it.dest == fragment), None)
        if frag_item is None:
            sys.stderr.write(
                f"  WARN   manifest declares ecosystem_fragment '{fragment}' "
                f"but it is absent from the overlay\n")
        elif frag_item.state not in ("core-refused", "leak-refused", "error") and (
                dry or os.path.exists(os.path.join(consumer.root, fragment))):
            # A fragment the context budget declares as a Phase 1 card is read
            # as an index (docs/context-index.md). Importing it as well loads it
            # whole and makes measure-context.py report a contradiction, so the
            # declaration wins and the import is left out.
            if card_declared(consumer.root, fragment):
                print(f"  indexed, not imported: {fragment}")
            else:
                wired = consumer.ensure_ecosystem_import(fragment, dry)
                if wired:
                    print(f"  @import {fragment} → CLAUDE.md")
    return fragment


def materialize(consumer: Consumer, cache: str, manifest: dict, defaults: dict,
                items: list[PlanItem], prune: list[dict], overlay_name: str,
                url: str, ref: str, resolved: str, manifest_sha: str,
                precedence: int, lock: dict, old_sha: str | None,
                dry: bool, assume_yes: bool, interactive: bool,
                track_managed_dests: bool = False) -> dict:
    counts = {k: 0 for k in ("clean", "locally-modified", "upstream-ahead",
                             "conflict", "orphan", "orphan-blocked",
                             "core-refused", "leak-refused", "skipped",
                             "withheld")}
    file_locks: list[dict] = []
    # Carry forward prompted_fields PATHS from the prior lock for skipped files.
    prev_files = {f["dest"]: f for f in
                  (lock.get("overlays") or {}).get(overlay_name, {})
                  .get("files", []) if isinstance(f, dict) and f.get("dest")}

    # Behavioural gate (step 11), asked BEFORE any write and once per unit: a
    # skill folder is confirmed all or none, so no run leaves a skill whose
    # SKILL.md routes to a reference that was never written. A run without a
    # person withholds the whole unit; nothing of it is written and its lock
    # entries stay as they were, so the next sync (and `status`) sees it again.
    #
    # The one answer covers every file of the unit: a file the consumer already
    # has (user-owned, on_conflict=prompt) is listed and overwritten on the same
    # [y] instead of a second per-file question that could leave the folder half
    # applied, and a file upstream removed from the folder is pruned with it, or
    # kept with it. Only on_conflict=skip keeps a consumer's own file inside an
    # accepted unit, because the manifest declared exactly that.
    units = gated_units(items, set(prev_files))
    unit_prune = held_prune(prune, units)
    withheld_dests: set[str] = set()
    withheld_units: set[str] = set()
    overwrite_ok: set[str] = set()
    for unit, members in sorted(units.items()):
        new = [m for m in members if m.dest not in prev_files]
        gone = unit_prune.get(unit, [])
        owned = [m for m in members if m.state == "user-owned"
                 and (m.on_conflict or defaults["on_conflict"]) == "prompt"]
        is_folder = unit.endswith("/")
        label = "skill folder" if is_folder else members[0].kind
        if not interactive:
            sys.stderr.write(
                f"  WITHHELD {unit}: behavioural ({label}), {len(new)} new of "
                f"{len(members) + len(gone)} changed file(s) need one explicit "
                f"[y] for the whole unit; --yes is not valid for behavioural "
                f"files\n")
            withheld_dests.update(m.dest for m in members)
            withheld_units.add(unit)
            continue
        print(f"\n  Behavioural {label}: {unit}")
        for m in members:
            note = "  (overwrites your file)" if m in owned else ""
            print(f"    {m.state:14} {m.dest}{note}")
        for pr in gone:
            print(f"    {'removed':14} {pr['dest']}")
        shown = next((m for m in members if m.dest.endswith("/SKILL.md")), new[0])
        preview = shown.staged_bytes.decode("utf-8", errors="ignore")
        print(f"  --- preview of {shown.dest} (first 20 lines) ---")
        for ln in preview.splitlines()[:20]:
            print("   | " + ln)
        question = (f"  Materialize skill folder {unit} "
                    f"({len(members) + len(gone)} file(s), all or none)?"
                    if is_folder else f"  Materialize {label} {unit}?")
        if not prompt_yes(question):
            sys.stderr.write(f"  WITHHELD {unit}: declined at behavioural gate\n")
            withheld_dests.update(m.dest for m in members)
            withheld_units.add(unit)
            continue
        overwrite_ok.update(m.dest for m in owned)

    for it in items:
        if it.state in ("core-refused", "leak-refused"):
            counts[it.state] += 1
            sys.stderr.write(f"  REFUSE {it.dest}: {it.reason}\n")
            continue
        if it.state == "error":
            sys.stderr.write(f"  ERROR  {it.dest}: {it.reason}\n")
            continue

        if it.dest in withheld_dests:
            # Held at the gate above: file untouched, lock entry (if any) as it
            # was, so the unit still reads as pending on the next run.
            counts["withheld"] += 1
            prev = prev_files.get(it.dest)
            if prev:
                file_locks.append(dict(prev))
            continue

        if it.state == "skip":
            counts["skipped"] += 1
            if not dry:
                heal_exec_bit(os.path.join(consumer.root, it.dest),
                              it.source_executable)
            prev = prev_files.get(it.dest, {})
            file_locks.append({
                "src": it.src, "dest": it.dest,
                "source_sha256": it.source_sha,
                "materialized_sha256": it.materialized_sha,
                **({"prompted_fields": prev["prompted_fields"]}
                   if prev.get("prompted_fields") else {}),
            })
            continue

        write_bytes = it.staged_bytes
        record_state = "clean"

        if it.state == "local-edit":
            merged, st = three_way(
                consumer, cache, it, old_sha, interactive,
                prev_files.get(it.dest, {}).get("source_sha256"))
            if merged is None:
                # kept local / skipped — preserve live, and DO NOT launder the
                # consumer's own bytes into `materialized_sha256`.
                #
                # That field means "the bytes the overlay wrote". Recording the
                # live hash here made a hand-edited file compare EQUAL to it,
                # and `cmd_remove` reads exactly that comparison to decide
                # `clean` — so one routine conflict-then-keep turned the user's
                # edit into a pristine file that a later `remove` deletes
                # without asking. The orphan prune in this same function reads
                # the field the same way.
                #
                # Keep what the overlay last wrote when we know it; otherwise
                # omit the key, which makes every later comparison FALSE and
                # therefore prompts. A field that cannot be trusted is worse
                # than a field that is absent.
                counts["locally-modified" if "kept" in st else "conflict"] += 1
                prev = prev_files.get(it.dest, {})
                prev_mat_sha = prev.get("materialized_sha256")
                if not prev_mat_sha and it.dest not in prev_files:
                    # A fragment adopted from a pre-fix lock has no earlier
                    # entry. The schema requires the field, and the overlay's
                    # current version is the only base there is. The live file
                    # differs from it, so it keeps reading as a local edit and
                    # `remove` keeps it.
                    prev_mat_sha = it.materialized_sha
                file_locks.append({
                    "src": it.src, "dest": it.dest,
                    "source_sha256": it.source_sha,
                    **({"materialized_sha256": prev_mat_sha} if prev_mat_sha else {}),
                    **({"prompted_fields": prev["prompted_fields"]}
                       if prev.get("prompted_fields") else {}),
                })
                continue
            write_bytes = merged
            record_state = "conflict" if "conflict" in st else "locally-modified"

        elif it.state == "upstream-ahead":
            record_state = "upstream-ahead"
        elif it.state == "user-owned":
            policy = it.on_conflict or defaults["on_conflict"]
            if policy == "skip":
                counts["skipped"] += 1
                sys.stderr.write(f"  SKIP   {it.dest}: user-owned (on_conflict=skip)\n")
                continue
            if policy == "prompt":
                if not interactive:
                    counts["skipped"] += 1
                    sys.stderr.write(
                        f"  SKIP   {it.dest}: user-owned, prompt needed "
                        f"(non-interactive)\n")
                    continue
                if it.dest not in overwrite_ok and not prompt_yes(
                        f"  {it.dest} exists (user-owned). Overwrite?"):
                    counts["skipped"] += 1
                    continue
            # overlay-wins or confirmed prompt → write as a clean copy.

        # Write (step 12): atomic COPY. Bytes identical to the file on disk
        # (a clean merge of an edit whose upstream did not move) are not
        # rewritten, so an unchanged file is not touched on every sync.
        counts[record_state] += 1
        dest_abs = os.path.join(consumer.root, it.dest)
        if not dry and not (os.path.exists(dest_abs)
                            and sha256_file(dest_abs) == sha256_bytes(write_bytes)):
            atomic_write_bytes(dest_abs, write_bytes, it.source_executable)
        elif not dry:
            heal_exec_bit(dest_abs, it.source_executable)
        file_locks.append({
            "src": it.src, "dest": it.dest,
            "source_sha256": it.source_sha,
            # What the OVERLAY wrote. A clean 3-way merge writes the consumer's
            # edit plus the upstream change; recording those merged bytes made
            # the edited file compare equal on the next run, so the next
            # upstream change landed as a plain overwrite (step 6c) and the edit
            # was gone. The overlay's staged bytes keep it reading as an edit.
            "materialized_sha256": (it.materialized_sha if it.state == "local-edit"
                                    else sha256_bytes(write_bytes)),
            **({"prompted_fields": it.prompted_fields}
               if it.prompted_fields else {}),
        })

    # Prune (step 14). LARGE PRUNE GUARD: a batch of clean orphans bigger than
    # LARGE_PRUNE_THRESHOLD is far more often a `select:` misconfiguration
    # (narrowed instead of extended, dropping dozens of previously-materialized
    # files out of scope in one edit) than a genuine round of upstream
    # deletions — those tend to remove one or two files at a time. Gate the
    # WHOLE batch behind one explicit confirmation (interactive) or refuse it
    # outright (non-interactive/--yes) instead of silently `os.remove`-ing
    # every one, which is what let a bad `select:` edit come within one
    # keystroke of deleting ~75 unrelated files in a live incident — see
    # feedback_overlay_select_narrowing_orphans_everything_else.
    # A file upstream removed from a withheld unit stays with the unit: deleting
    # a reference the unchanged SKILL.md still routes to is a half skill too.
    # File and lock entry stay as they were until the unit is confirmed.
    held = [pr for pr in prune if gate_unit(pr["dest"]) in withheld_units]
    for pr in held:
        counts["withheld"] += 1
        prev = prev_files.get(pr["dest"])
        if prev:
            file_locks.append(dict(prev))
    prune = [pr for pr in prune if pr not in held]
    clean_orphans = [pr for pr in prune if pr["present"] and pr["clean"]]
    large_batch = len(clean_orphans) > LARGE_PRUNE_THRESHOLD
    allow_large_prune = False
    if large_batch:
        sample = ", ".join(pr["dest"] for pr in clean_orphans[:5])
        more = f" (+{len(clean_orphans) - 5} more)" if len(clean_orphans) > 5 else ""
        if not interactive:
            sys.stderr.write(
                f"  BLOCKED {len(clean_orphans)} files would be pruned as "
                f"orphans (e.g. {sample}{more}) — this usually means `select:` "
                f"was narrowed rather than an intentional upstream removal. "
                f"Non-interactive run: kept all, nothing deleted. Re-run "
                f"interactively to review, or fix `select:` if it was "
                f"narrowed by mistake.\n")
        else:
            print(f"\n  {len(clean_orphans)} files no longer match this "
                  f"overlay's `select:` and would be deleted as orphans:")
            print(f"    {sample}{more}")
            print("  This is usually a `select:` misconfiguration (narrowed "
                  "instead of extended), not an intentional bulk removal "
                  "upstream.")
            allow_large_prune = prompt_yes(
                f"  Really delete all {len(clean_orphans)} files?")
            if not allow_large_prune:
                sys.stderr.write(
                    f"  KEPT   {len(clean_orphans)} files: large-prune batch "
                    f"declined\n")
    if large_batch and not allow_large_prune:
        counts["orphan-blocked"] += len(clean_orphans)
        # Keep the original lock entries for the blocked files exactly as they
        # were — the physical files are untouched, so the lock must still
        # match them, or the NEXT sync (even with `select:` fixed) would see
        # them as unknown-on-disk ("user-owned") instead of recognizing them.
        for pr in clean_orphans:
            prev = prev_files.get(pr["dest"])
            if prev:
                file_locks.append(dict(prev))
    for pr in prune:
        if not pr["present"]:
            continue
        if pr["clean"]:
            if large_batch and not allow_large_prune:
                continue  # already counted + reported above
            counts["orphan"] += 1
            if not dry:
                os.remove(os.path.join(consumer.root, pr["dest"]))
                if valid_fragment_name(pr["dest"]):
                    consumer.drop_ecosystem_import(pr["dest"])
        else:
            if interactive and prompt_yes(
                    f"  upstream removed {pr['dest']} but it is modified. Delete?"):
                counts["orphan"] += 1
                if not dry:
                    os.remove(os.path.join(consumer.root, pr["dest"]))
                    if valid_fragment_name(pr["dest"]):
                        consumer.drop_ecosystem_import(pr["dest"])
            else:
                sys.stderr.write(f"  KEEP   {pr['dest']}: orphan but modified\n")

    fragment = wire_ecosystem_import(consumer, manifest, items, dry)

    # Git-exclude guard (step 14): keep overlay-materialized org content OUT of
    # git (via the LOCAL .git/info/exclude, never tracked .gitignore) so a fork
    # (public by default) can't publish it — nor its filenames — via `git add -A`.
    # This is the default and stays byte-identical when track_managed_dests is
    # unset. A user can opt this overlay OUT of the guard via the explicit,
    # off-by-default materialize.track_managed_dests: true knob in
    # bridge-config.yaml — the dests then become normal, `git add`-able tracked
    # files instead. Never auto-derived from the consumer repo's visibility.
    ig_dests = [fl["dest"] for fl in file_locks]
    if fragment and fragment not in ig_dests:
        ig_dests.append(fragment)
    if track_managed_dests:
        # Clean up a block a prior run may have written (e.g. the switch was
        # just flipped on) so it takes effect without a manual exclude edit.
        if consumer.drop_git_exclude_block(overlay_name, dry):
            print(f"  .git/info/exclude: dropped overlay:{overlay_name} block "
                  f"(track_managed_dests: true — {len(ig_dests)} dests now trackable)")
    elif ig_dests and consumer.ensure_git_exclude_block(overlay_name, ig_dests, dry):
        print(f"  .git/info/exclude ← {len(ig_dests)} managed dests (overlay:{overlay_name})")

    # Lockfile (step 15).
    if not dry:
        prev_entry = (lock.get("overlays") or {}).get(overlay_name)
        new_entry = {
            "url": url, "ref": ref, "resolved_sha": resolved,
            "manifest_sha256": manifest_sha, "precedence": precedence,
            "last_synced": now_iso(),
            # This engine plans the fragment (build_plan), so a fragment with
            # no files[] entry is the consumer's own, never a pre-fix lock.
            "fragment_managed": True,
            "files": file_locks,
        }
        # Idempotency: if nothing materially changed (same files, same pins),
        # preserve the prior last_synced so a clean re-apply leaves the lock
        # byte-identical instead of churning the timestamp.
        if prev_entry is not None:
            a = {k: v for k, v in new_entry.items() if k != "last_synced"}
            b = {k: v for k, v in prev_entry.items() if k != "last_synced"}
            if a == b:
                new_entry["last_synced"] = prev_entry.get("last_synced",
                                                          new_entry["last_synced"])
        lock.setdefault("overlays", {})[overlay_name] = new_entry
        consumer.write_lock(lock)
        # Fleet record (step 16).
        inst = consumer.record_subscription(overlay_name, dry)
        if inst:
            print(f"  fleet: subscribes_overlays += {overlay_name} "
                  f"({os.path.relpath(inst, consumer.root)})")

    return counts


# ---------------------------------------------------------------------------
# bridge-config materialize block (add / remove)
# ---------------------------------------------------------------------------

def upsert_upstream_block(consumer: Consumer, name: str, url: str, ref: str,
                          precedence: int, select: list[str],
                          source_root: str,
                          track_managed_dests: bool = False) -> None:
    cfg = consumer.load_config()
    upstreams = cfg.get("upstreams")
    if not isinstance(upstreams, list):
        upstreams = []
        cfg["upstreams"] = upstreams
    repo = re.sub(r"^.*[:/]([^/]+/[^/]+?)(?:\.git)?$", r"\1", url)
    entry: dict | None = None
    for u in upstreams:
        if isinstance(u, dict) and u.get("name") == name:
            entry = u
            break
    if entry is None:
        entry = {"name": name}
        upstreams.append(entry)
    materialize_block = {
        "url": url, "ref": ref,
        "cache": f"{CACHE_BASE}/{name}/",
        "precedence": precedence,
        "select": select or ["**"],
    }
    # Omitted (rather than written as false) when unset, so a default `add`
    # produces the same materialize block as before this knob existed.
    if track_managed_dests:
        materialize_block["track_managed_dests"] = True
    entry.update({
        "repo": repo, "branch": ref, "role": "org-overlay",
        "contribute": True, "pull_interval_days": 7,
        "materialize": materialize_block,
    })
    consumer.write_config(cfg)


def drop_upstream_block(consumer: Consumer, name: str) -> None:
    cfg = consumer.load_config()
    upstreams = cfg.get("upstreams")
    if isinstance(upstreams, list):
        cfg["upstreams"] = [u for u in upstreams
                            if not (isinstance(u, dict) and u.get("name") == name)]
        consumer.write_config(cfg)


def find_subscription(consumer: Consumer, name: str) -> dict | None:
    for u in consumer.org_overlay_upstreams():
        if u.get("name") == name:
            return u
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _resolve_overlay_params(consumer: Consumer, name: str) -> dict:
    """Resolve {url, ref, precedence, select, track_managed_dests} for a
    subscribed overlay. Read fresh from bridge-config.yaml on every call, so
    a hand-edit (e.g. flipping track_managed_dests) takes effect on the next
    sync/apply without re-running add."""
    sub = find_subscription(consumer, name)
    if sub is None:
        raise OverlayError(f"overlay '{name}' is not subscribed (run: add)")
    mat = sub.get("materialize") or {}
    return {
        "url": mat.get("url"),
        "ref": mat.get("ref") or sub.get("branch") or "main",
        "precedence": mat.get("precedence", 0),
        "select": mat.get("select") or ["**"],
        "track_managed_dests": bool(mat.get("track_managed_dests", False)),
    }


def cmd_add(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    # --yes ⇒ non-interactive: config/rule batch-confirm, behavioural units are
    # WITHHELD whole (a behavioural [y] can never be auto-granted), prompts are
    # not raised.
    interactive = not args.dry_run and not args.yes
    name = args.name
    ref = args.ref or "main"
    precedence = args.precedence
    select = args.select or ["**"]
    track_managed_dests = args.track_managed_dests

    # 1) cache the repo (need it to read the manifest → name fallback).
    tmp_name = name or "_pending"
    cache = ensure_cache(consumer, tmp_name, args.git_url, ref, DEFAULT_SOURCE_ROOT)
    validate_manifest(cache)
    manifest, manifest_sha = read_manifest(cache)
    defaults = manifest_defaults(manifest)
    if name is None:
        name = (manifest.get("overlay") or {}).get("name")
        if not name:
            raise OverlayError("overlay manifest has no name and --name not given")
        # relocate the cache to its real name
        if tmp_name != name:
            real = cache_dir(consumer, name)
            os.makedirs(os.path.dirname(real), exist_ok=True)
            if os.path.exists(real):
                shutil.rmtree(real)
            shutil.move(cache, real)
            cache = real

    resolved = resolved_sha(cache)
    lock = consumer.load_lock()
    if name in (lock.get("overlays") or {}):
        raise OverlayError(f"overlay '{name}' already added — use 'sync' instead")

    print(f"overlay add: {name}  ({args.git_url} @ {ref} → {resolved[:10]})")
    items, prune = build_plan(consumer, cache, manifest, defaults, select,
                              name, precedence, lock, None, interactive)
    render_plan(items, prune)
    if args.dry_run:
        wire_ecosystem_import(consumer, manifest, items, True)
        print("\n[dry-run] no files written.")
        return 0

    # Persist the subscription block BEFORE materializing so a crash mid-write
    # still leaves a recoverable subscription.
    upsert_upstream_block(consumer, name, args.git_url, ref, precedence,
                          select, defaults["source_root"], track_managed_dests)
    counts = materialize(consumer, cache, manifest, defaults, items, prune,
                         name, args.git_url, ref, resolved, manifest_sha,
                         precedence, lock, None, args.dry_run, args.yes,
                         interactive, track_managed_dests=track_managed_dests)
    report_counts("added", name, counts)
    return 0


def cmd_sync(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    names = [args.name] if args.name else [
        u["name"] for u in consumer.org_overlay_upstreams()]
    if not names:
        print("No org overlays subscribed (upstreams[] role: org-overlay).")
        return 0
    if args.unattended:
        return cmd_sync_unattended(consumer, names)
    rc = 0
    for name in names:
        try:
            rc |= _sync_one(consumer, name, args)
        except OverlayError as exc:
            sys.stderr.write(f"sync {name}: {exc}\n")
            rc = 1
    return rc


def _sync_one(consumer: Consumer, name: str, args) -> int:
    params = _resolve_overlay_params(consumer, name)
    if not params["url"]:
        raise OverlayError(f"overlay '{name}' has no materialize.url — re-add it")
    interactive = not args.dry_run and not args.yes
    lock = consumer.load_lock()
    old_sha = (lock.get("overlays") or {}).get(name, {}).get("resolved_sha")

    cache = ensure_cache(consumer, name, params["url"], params["ref"],
                         DEFAULT_SOURCE_ROOT)
    validate_manifest(cache)
    manifest, manifest_sha = read_manifest(cache)
    defaults = manifest_defaults(manifest)
    resolved = resolved_sha(cache)
    print(f"overlay sync: {name}  ({old_sha[:10] if old_sha else 'new'} → "
          f"{resolved[:10]})")
    items, prune = build_plan(consumer, cache, manifest, defaults,
                              params["select"], name, params["precedence"],
                              lock, old_sha, interactive)
    render_plan(items, prune)
    if args.dry_run:
        wire_ecosystem_import(consumer, manifest, items, True)
        print("\n[dry-run] no files written.")
        return 0
    counts = materialize(consumer, cache, manifest, defaults, items, prune,
                         name, params["url"], params["ref"], resolved,
                         manifest_sha, params["precedence"], lock, old_sha,
                         args.dry_run, args.yes, interactive,
                         track_managed_dests=params["track_managed_dests"])
    report_counts("synced", name, counts)
    return 0


def pull_interval_days(sub: dict | None) -> int:
    """`pull_interval_days` of a subscription. It sits on the upstream entry
    (bridge-config.yaml.template, `add`); an older write-up put it under
    `materialize:`, so that spelling is read too rather than silently ignored."""
    sub = sub or {}
    raw = sub.get("pull_interval_days",
                  (sub.get("materialize") or {}).get("pull_interval_days",
                                                     DEFAULT_PULL_INTERVAL_DAYS))
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_PULL_INTERVAL_DAYS


def unattended_due(prev: dict | None, interval: int, now: datetime) -> bool:
    """Only an APPLIED run waits out the interval. A held or failed overlay is
    looked at again on the next run, so a conflict somebody resolves today is
    picked up tomorrow and not a week later."""
    if not prev or prev.get("outcome") != "applied" or interval <= 0:
        return True
    try:
        last = datetime.strptime(prev.get("at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return True
    return now - last >= timedelta(days=interval) - DUE_SLACK


def unattended_blockers(consumer: Consumer, cache: str, items: list[PlanItem],
                        prune: list[dict], old_sha: str | None,
                        lock_files: dict | None = None,
                        held_units: set[str] | frozenset = frozenset()) -> list[str]:
    """What in this plan needs a person. Any of it holds the WHOLE overlay.

    A conflict: `sync --yes` keeps the local side AND advances the lock pin, and
    from the next run on the base of the 3-way merge is the new upstream, so the
    file reads as an ordinary local edit. The upstream change is then lost with
    no state left that says so: `status` counts it as locally-modified. Holding
    the overlay keeps the pin where it is, and the conflict stays a conflict
    until somebody resolves it with `/overlay sync`.

    A deletion: an unattended run applies and updates, it never deletes (see
    scripts/overlay-autosync.sh for the file that made this the rule).

    Applying the rest and holding only the conflicting file would need a pin per
    file, and the lock has one per overlay.

    A deletion inside a unit held at the behavioural gate is no blocker: the
    engine keeps it with the unit (see materialize) and deletes nothing."""
    lock_files = lock_files or {}
    blockers: list[str] = []
    for it in items:
        if it.state == "error":
            blockers.append(f"error: {it.dest}")
        elif it.state == "local-edit":
            merged, _ = three_way(consumer, cache, it, old_sha, interactive=False,
                                  base_source_sha=(lock_files.get(it.dest) or {})
                                  .get("source_sha256"))
            if merged is None:
                blockers.append(f"conflict: {it.dest}")
    for pr in prune:
        if pr["present"] and gate_unit(pr["dest"]) not in held_units:
            blockers.append(f"would delete: {pr['dest']}")
    return blockers


def _unattended_one(consumer: Consumer, name: str, prev: dict | None,
                    now: datetime) -> tuple[str, str]:
    """(outcome, detail) for one overlay. Outcomes: applied · held · not-due."""
    sub = find_subscription(consumer, name)
    interval = pull_interval_days(sub)
    if not unattended_due(prev, interval, now):
        return "not-due", f"last applied {prev.get('at')}, interval {interval}d"
    params = _resolve_overlay_params(consumer, name)
    if not params["url"]:
        raise OverlayError(f"overlay '{name}' has no materialize.url, re-add it")
    lock = consumer.load_lock()
    prev_entry = (lock.get("overlays") or {}).get(name, {})
    old_sha = prev_entry.get("resolved_sha")
    cache = ensure_cache(consumer, name, params["url"], params["ref"],
                         DEFAULT_SOURCE_ROOT)
    validate_manifest(cache)
    manifest, manifest_sha = read_manifest(cache)
    defaults = manifest_defaults(manifest)
    resolved = resolved_sha(cache)
    items, prune = build_plan(consumer, cache, manifest, defaults,
                              params["select"], name, params["precedence"],
                              lock, old_sha, False)
    lock_files = {f["dest"]: f for f in prev_entry.get("files", [])
                  if isinstance(f, dict) and f.get("dest")}
    units = gated_units(items, set(lock_files))
    blockers = unattended_blockers(consumer, cache, items, prune, old_sha,
                                   lock_files, set(units))
    if blockers:
        return "held", "; ".join(blockers)

    # What the engine will leave for a person without holding anything back:
    # every changed file of a behavioural unit with a first-time file in it (the
    # [y] gate is never answered unattended, and a skill folder is held whole,
    # deletions inside it included) and a file the consumer already has that the
    # overlay would claim. Neither is applied to the lock, so both come up again.
    pending = sorted(
        {m.dest for ms in units.values() for m in ms}
        | {pr["dest"] for prs in held_prune(prune, units).values() for pr in prs}
        | {it.dest for it in items
           if it.state == "user-owned"
           and (it.on_conflict or defaults["on_conflict"]) == "prompt"})
    refused = sorted(it.dest for it in items
                     if it.state in ("core-refused", "leak-refused"))
    counts = materialize(consumer, cache, manifest, defaults, items, prune,
                         name, params["url"], params["ref"], resolved,
                         manifest_sha, params["precedence"], lock, old_sha,
                         False, True, False,
                         track_managed_dests=params["track_managed_dests"])
    written = sum(counts[k] for k in ("clean", "upstream-ahead", "locally-modified"))
    detail = [f"{written} written", f"at {resolved[:10]}"]
    if pending:
        detail.append("pending: " + ", ".join(pending))
    if refused:
        detail.append("refused: " + ", ".join(refused))
    return "applied", "; ".join(detail)


def cmd_sync_unattended(consumer: Consumer, names: list[str]) -> int:
    """The scheduled run: apply an overlay only when its plan needs nobody.

    One line per overlay, `unattended <name>: <outcome> (<detail>)`, stable and
    parsed by scripts/overlay-autosync.sh. Exit 1 only when an overlay FAILED; a
    held overlay did its job."""
    state = consumer.load_unattended()
    now = datetime.now(timezone.utc)
    rc = 0
    for name in names:
        prev = state.get(name) if isinstance(state.get(name), dict) else None
        try:
            outcome, detail = _unattended_one(consumer, name, prev, now)
        except (OverlayError, OSError, subprocess.SubprocessError) as exc:
            outcome, detail = "failed", str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
            rc = 1
        print(f"unattended {name}: {outcome}" + (f" ({detail})" if detail else ""))
        if outcome != "not-due":
            state[name] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "outcome": outcome, "detail": detail}
    consumer.write_unattended(state)
    return rc


def cmd_apply(consumer: Consumer, args) -> int:
    """OFFLINE re-materialize from cache + lock (no network)."""
    consumer.require_user_branch()
    names = [args.name] if args.name else [
        u["name"] for u in consumer.org_overlay_upstreams()]
    if not names:
        print("No org overlays subscribed.")
        return 0
    rc = 0
    for name in names:
        try:
            params = _resolve_overlay_params(consumer, name)
            cache = cache_dir(consumer, name)
            if not os.path.isdir(os.path.join(cache, ".git")):
                raise OverlayError(
                    f"no cache at {CACHE_BASE}/{name} — run 'sync' first (apply "
                    f"is offline)")
            validate_manifest(cache)
            manifest, manifest_sha = read_manifest(cache)
            defaults = manifest_defaults(manifest)
            resolved = resolved_sha(cache)
            lock = consumer.load_lock()
            old_sha = (lock.get("overlays") or {}).get(name, {}).get("resolved_sha")
            interactive = not args.yes
            print(f"overlay apply (offline): {name} @ {resolved[:10]}")
            items, prune = build_plan(consumer, cache, manifest, defaults,
                                      params["select"], name,
                                      params["precedence"], lock, old_sha,
                                      interactive)
            counts = materialize(consumer, cache, manifest, defaults, items,
                                 prune, name, params["url"], params["ref"],
                                 resolved, manifest_sha, params["precedence"],
                                 lock, old_sha, False, args.yes, interactive,
                                 track_managed_dests=params["track_managed_dests"])
            report_counts("applied", name, counts)
        except OverlayError as exc:
            sys.stderr.write(f"apply {name}: {exc}\n")
            rc = 1
    return rc


def status_data(consumer: Consumer, name: str, lock: dict) -> dict:
    """One overlay's state as data: what `status` prints, and what a briefing reads."""
    entry = (lock.get("overlays") or {}).get(name)
    sub = find_subscription(consumer, name)
    out = {"name": name, "subscribed": sub is not None, "materialized": entry is not None}
    if entry is None:
        return out
    cache = cache_dir(consumer, name)
    head = resolved_sha(cache) if os.path.isdir(os.path.join(cache, ".git")) else None
    out.update(resolved_sha=entry.get("resolved_sha"), cache_head=head,
               cache_ahead=bool(head and head != entry.get("resolved_sha")),
               interval_days=(sub or {}).get("pull_interval_days", 7), count_lock=len(entry.get("files", [])))
    last = entry.get("last_synced")
    out["last_synced"] = last
    if last:
        try:
            when = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            out["days_since_sync"] = (datetime.now(timezone.utc) - when).days
            out["stale"] = out["days_since_sync"] > out["interval_days"]
        except ValueError:
            pass
    run = consumer.load_unattended().get(name)
    out["last_unattended"] = run if isinstance(run, dict) else None
    # pending-confirm: files the next sync holds at the behavioural gate until a
    # person says [y] (a subset of the counts beside it, never hidden by them).
    counts = {"clean": 0, "locally-modified": 0, "upstream-ahead": 0, "conflict": 0,
              "orphan": 0, "pending-confirm": 0}
    out["withheld"] = []
    if os.path.isdir(os.path.join(cache, ".git")):
        try:
            manifest, _ = read_manifest(cache)
            defaults = manifest_defaults(manifest)
            params = _resolve_overlay_params(consumer, name) if sub else \
                {"select": ["**"], "precedence": entry.get("precedence", 0)}
            items, prune = build_plan(
                consumer, cache, manifest, defaults, params["select"], name,
                params["precedence"], lock, entry.get("resolved_sha"), False)
            for it in items:
                if it.state == "skip":
                    counts["clean"] += 1
                elif it.state in ("upstream-ahead", "clean-new"):
                    # A file the overlay has and the consumer does not is ahead
                    # upstream as much as a changed one. Leaving it uncounted is
                    # what let a withheld new reference read as upstream-ahead=0.
                    counts["upstream-ahead"] += 1
                elif it.state == "local-edit":
                    counts["locally-modified"] += 1
                elif it.state in ("core-refused", "leak-refused"):
                    counts.setdefault(it.state, 0)
                    counts[it.state] += 1
            counts["orphan"] = len(prune)
            known = {f.get("dest") for f in entry.get("files", []) if isinstance(f, dict)}
            units = gated_units(items, known)
            counts["pending-confirm"] = (
                sum(len(m) for m in units.values())
                + sum(len(p) for p in held_prune(prune, units).values()))
            out["withheld"] = sorted(units)
        except OverlayError as exc:
            out["plan_error"] = str(exc)
    out["files"] = counts
    return out


def cmd_status(consumer: Consumer, args) -> int:
    names = [args.name] if args.name else [
        u["name"] for u in consumer.org_overlay_upstreams()]
    lock = consumer.load_lock()
    data = [status_data(consumer, name, lock) for name in names]
    if getattr(args, "json", False):
        print(json.dumps(data, indent=1))
        return 0
    if not names:
        print("No org overlays subscribed.")
        return 0
    for d in data:
        print(f"\n■ {d['name']}")
        if not d["subscribed"]:
            print("  (not in upstreams[] — orphaned lock entry)")
        if not d["materialized"]:
            print("  (subscribed but never materialized)")
            continue
        print(f"  resolved_sha : {(d.get('resolved_sha') or '?')[:12]}")
        head = d.get("cache_head")
        print(f"  cache HEAD   : {head[:12] if head else '(no cache — offline)'}")
        if d.get("cache_ahead"):
            print("  ↑ cache is AHEAD of lock — run 'sync'")
        last = d.get("last_synced")
        if last and "days_since_sync" in d:
            flag = "  (stale)" if d.get("stale") else ""
            print(f"  last_synced  : {last}  ({d['days_since_sync']}d ago){flag}")
        elif last:
            print(f"  last_synced  : {last}")
        run = d.get("last_unattended")
        if run:
            print(f"  last unattended: {run.get('at', '?')}  {run.get('outcome', '?')}"
                  + (f" ({run['detail']})" if run.get("detail") else ""))
        else:
            print("  last unattended: never")
        if d.get("plan_error"):
            print(f"  (plan error: {d['plan_error']})")
        print("  files        : " + "  ".join(f"{k}={v}" for k, v in d["files"].items()))
        if d.get("withheld"):
            print("  withheld     : " + ", ".join(d["withheld"])
                  + "  (needs [y]: run 'sync' interactively)")
        print(f"  count(lock)  : {d['count_lock']}")
    return 0


def cmd_diff(consumer: Consumer, args) -> int:
    """Preview the next sync/apply — no writes."""
    names = [args.name] if args.name else [
        u["name"] for u in consumer.org_overlay_upstreams()]
    if not names:
        print("No org overlays subscribed.")
        return 0
    lock = consumer.load_lock()
    for name in names:
        params = _resolve_overlay_params(consumer, name)
        cache = cache_dir(consumer, name)
        if not os.path.isdir(os.path.join(cache, ".git")):
            print(f"{name}: no cache (run 'sync' first for a live diff)")
            continue
        manifest, _ = read_manifest(cache)
        defaults = manifest_defaults(manifest)
        old_sha = (lock.get("overlays") or {}).get(name, {}).get("resolved_sha")
        print(f"\noverlay diff: {name} (preview, no writes)")
        items, prune = build_plan(consumer, cache, manifest, defaults,
                                  params["select"], name, params["precedence"],
                                  lock, old_sha, False)
        render_plan(items, prune, verbose=True, consumer=consumer)
    return 0


def cmd_remove(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    name = args.name
    lock = consumer.load_lock()
    entry = (lock.get("overlays") or {}).get(name)
    sub = find_subscription(consumer, name)
    if entry is None and sub is None:
        raise OverlayError(f"overlay '{name}' is not subscribed")
    interactive = sys.stdin.isatty()

    deleted = 0
    kept = 0
    if entry and not args.keep_files:
        for f in entry.get("files", []):
            dest_abs = os.path.join(consumer.root, f["dest"])
            if not os.path.exists(dest_abs):
                continue
            clean = sha256_file(dest_abs) == f.get("materialized_sha256")
            if clean:
                os.remove(dest_abs)
                deleted += 1
            else:
                if interactive and prompt_yes(
                        f"  {f['dest']} is locally-modified. Delete anyway?"):
                    os.remove(dest_abs)
                    deleted += 1
                else:
                    kept += 1
                    sys.stderr.write(f"  KEEP   {f['dest']}: locally-modified\n")
    # Ecosystem @import + fragment.
    if entry:
        # try to find the fragment name from cache manifest
        cache = cache_dir(consumer, name)
        if os.path.isdir(os.path.join(cache, ".git")):
            try:
                manifest, _ = read_manifest(cache)
                frag = manifest.get("ecosystem_fragment")
                if frag and valid_fragment_name(frag) and not args.keep_files:
                    consumer.drop_ecosystem_import(frag)
                    fp = os.path.join(consumer.root, frag)
                    managed = any(f.get("dest") == frag
                                  for f in entry.get("files", []))
                    if (not managed and not entry.get("fragment_managed")
                            and os.path.exists(fp)):
                        # A lock from before the fragment was managed: the files
                        # loop above never saw it. The last copy the overlay
                        # wrote is the blob at the pinned SHA, so delete only
                        # when the file still matches it. The old code deleted
                        # the fragment unconditionally, edits included. Under a
                        # lock that plans the fragment, a missing entry means
                        # the consumer's own file, which remove never touches.
                        pinned = entry.get("resolved_sha")
                        base = git_show_blob(cache, pinned, frag) if pinned else None
                        if base is not None and sha256_file(fp) == sha256_bytes(base):
                            os.remove(fp)
                            deleted += 1
                        else:
                            kept += 1
                            sys.stderr.write(f"  KEEP   {frag}: locally-modified\n")
            except OverlayError:
                pass
        # Drop the git-exclude guard block (files are being removed).
        if not args.keep_files:
            consumer.drop_git_exclude_block(name)
        # Drop cache.
        if os.path.isdir(cache):
            shutil.rmtree(cache, ignore_errors=True)

    # Drop lock entry + materialize block + fleet record.
    if entry:
        lock["overlays"].pop(name, None)
        consumer.write_lock(lock)
    drop_upstream_block(consumer, name)
    consumer.unrecord_subscription(name)

    suffix = " (subscription ended; files kept)" if args.keep_files else ""
    print(f"overlay remove: {name} — deleted {deleted}, kept {kept}{suffix}")
    return 0


def cmd_list(consumer: Consumer, args) -> int:
    subs = consumer.org_overlay_upstreams()
    lock = consumer.load_lock()
    if not subs:
        print("No org overlays subscribed.")
        return 0
    print(f"{'NAME':16} {'REF':10} {'SHA':10} {'PREC':>4} {'FILES':>5}  "
          f"{'LAST_SYNCED':20} URL")
    for u in subs:
        name = u.get("name", "?")
        mat = u.get("materialize") or {}
        entry = (lock.get("overlays") or {}).get(name, {})
        print(f"{name:16} {(mat.get('ref') or u.get('branch') or '?'):10} "
              f"{entry.get('resolved_sha','?')[:10]:10} "
              f"{mat.get('precedence', 0):>4} "
              f"{len(entry.get('files', [])):>5}  "
              f"{entry.get('last_synced','-'):20} {mat.get('url') or u.get('repo','?')}")
    return 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

STATE_RISK = {
    "clean-new": "  ",
    "skip": "  ",
    "upstream-ahead": "↑ ",
    "local-edit": "✎ ",
    "user-owned": "! ",
    "core-refused": "✗ ",
    "leak-refused": "✗ ",
    "error": "✗ ",
}


def render_plan(items: list[PlanItem], prune: list[dict],
                verbose: bool = False, consumer: Consumer | None = None) -> None:
    if not items and not prune:
        print("  (empty plan)")
        return
    for it in sorted(items, key=lambda x: (x.state, x.dest)):
        risk = STATE_RISK.get(it.state, "  ")
        beh = " [behavioural→y]" if it.kind in BEHAVIOURAL_KINDS else ""
        line = f"  {risk}{it.state:14} {it.kind:13} {it.dest}{beh}"
        if it.reason:
            line += f"   ({it.reason})"
        print(line)
        if verbose and consumer is not None and it.state in (
                "clean-new", "upstream-ahead", "local-edit"):
            dest_abs = os.path.join(consumer.root, it.dest)
            before = "absent"
            if os.path.exists(dest_abs):
                before = sha256_file(dest_abs)[:10]
            print(f"        before={before}  after={it.materialized_sha[:10]}")
    for pr in prune:
        tag = "orphan(clean)" if pr["clean"] else "orphan(modified)"
        print(f"  ⌫ {tag:14} {'-':13} {pr['dest']}")
    clean_orphan_count = sum(1 for pr in prune if pr["present"] and pr["clean"])
    if clean_orphan_count > LARGE_PRUNE_THRESHOLD:
        print(f"\n  ⚠ {clean_orphan_count} files above would be pruned as "
              f"orphans — more than usual for a genuine upstream removal. "
              f"Check `select:` in bridge-config.yaml wasn't narrowed by "
              f"mistake before running this for real; `sync` will gate this "
              f"batch behind an extra confirmation either way.")


def report_counts(verb: str, name: str, counts: dict) -> None:
    summary = "  ".join(f"{k}={v}" for k, v in counts.items() if v)
    print(f"\n{verb} {name}: {summary or 'no changes'}")
    if counts.get("core-refused") or counts.get("leak-refused"):
        print("  (refused files were surfaced above — overlay continued with "
              "the rest)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="overlay",
        description="Org-overlay engine — subscribe to / sync / materialize an "
                    "org overlay into this Bridge.",
    )
    p.add_argument("--repo-root", help="consumer repo root "
                   "(default: $BRIDGE_REPO_ROOT or the repo this script ships in)")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="subscribe to an overlay repo + first materialize")
    a.add_argument("git_url", help="clone URL of the overlay repo")
    a.add_argument("--ref", default="main", help="git ref (branch/tag, default main)")
    a.add_argument("--name", help="overlay name (default: from manifest.overlay.name)")
    a.add_argument("--select", nargs="*", help="extra select glob(s) (default **)")
    a.add_argument("--precedence", type=int, default=0,
                   help="layering order — higher wins a dest collision")
    a.add_argument("--track-managed-dests", action="store_true",
                   help="opt this overlay's managed dests INTO git tracking "
                        "instead of the default .git/info/exclude guard (off "
                        "by default; see docs/org-overlays.md). Can also be "
                        "set later by hand-editing bridge-config.yaml's "
                        "upstreams[].materialize.track_managed_dests and "
                        "re-running sync/apply.")
    a.add_argument("--dry-run", action="store_true", help="plan only, no writes")
    a.add_argument("--yes", action="store_true",
                   help="batch-confirm non-behavioural (behavioural still gated)")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("sync", help="pull cache + re-materialize (3-way vs lock)")
    s.add_argument("name", nargs="?", help="overlay name (default: all)")
    s.add_argument("--dry-run", action="store_true", help="plan only, no writes")
    s.add_argument("--yes", action="store_true",
                   help="batch-confirm non-behavioural; skip interactive prompts")
    s.add_argument("--unattended", action="store_true",
                   help="the scheduled run: honour pull_interval_days, hold an "
                        "overlay whose plan has a conflict or a deletion, never "
                        "approve a new behavioural file, record the outcome for "
                        "`status` (scripts/overlay-autosync.sh)")
    s.set_defaults(func=cmd_sync)

    ap = sub.add_parser("apply", help="OFFLINE re-materialize from cache + lock")
    ap.add_argument("name", nargs="?", help="overlay name (default: all)")
    ap.add_argument("--yes", action="store_true", help="batch-confirm non-behavioural")
    ap.set_defaults(func=cmd_apply)

    st = sub.add_parser("status", help="resolved_sha vs cache HEAD + file counts")
    st.add_argument("--json", action="store_true", help="the same state as data")
    st.add_argument("name", nargs="?", help="overlay name (default: all)")
    st.set_defaults(func=cmd_status)

    d = sub.add_parser("diff", help="preview next sync/apply (no writes)")
    d.add_argument("name", nargs="?", help="overlay name (default: all)")
    d.set_defaults(func=cmd_diff)

    r = sub.add_parser("remove", help="unsubscribe + delete clean managed files")
    r.add_argument("name", help="overlay name")
    r.add_argument("--keep-files", action="store_true",
                   help="end the subscription but leave materialized files")
    r.set_defaults(func=cmd_remove)

    li = sub.add_parser("list", help="list subscribed org overlays")
    li.set_defaults(func=cmd_list)
    return p


def resolve_repo_root(args) -> str:
    if args.repo_root:
        return os.path.abspath(args.repo_root)
    env = os.environ.get("BRIDGE_REPO_ROOT")
    if env:
        return os.path.abspath(env)
    # default: the repo this script ships in (parent of scripts/)
    return os.path.dirname(SCRIPT_DIR)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = resolve_repo_root(args)
    # Run with the consumer root as cwd so categorize-commits' frontmatter
    # reads resolve, and relative git ops behave.
    try:
        os.chdir(root)
    except OSError as exc:
        sys.stderr.write(f"ERROR: cannot enter repo root {root}: {exc}\n")
        return 2
    consumer = Consumer(root)
    try:
        return args.func(consumer, args)
    except OverlayError as exc:
        sys.stderr.write(f"overlay: {exc}\n")
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        sys.stderr.write("\noverlay: interrupted\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
