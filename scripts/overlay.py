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
  - behavioural files (skill/agent/standing-order) force a per-file [y]
  - the lock stores prompted-field PATHS only, never the user's values
  - writes are atomic COPIES (never symlinks); --dry-run stops before any write

Exit codes:
  0 — success           1 — refusal / error           2 — setup/usage error

Full design: docs/org-overlays.md
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BEHAVIOURAL_KINDS = {"skill", "agent", "standing-order"}
ALL_KINDS = {"config", "skill", "agent", "standing-order", "rule",
             "ecosystem-fragment"}
CACHE_BASE = ".bridge/overlays"
LOCK_FILE = "overlays.lock.yaml"
MANIFEST_FILE = "overlay.manifest.yaml"
DEFAULT_SOURCE_ROOT = "tree/"
MAX_MANIFEST_BYTES = 256 * 1024  # an overlay manifest is small; anything bigger is suspect

# Secret material that must never be copied verbatim into a consumer file.
# Accounts reference secrets by URI only (azure-keyvault:// keychain:// 1password://).
SECRET_URI_PREFIXES = ("azure-keyvault://", "keychain://", "1password://",
                       "vault://", "op://")
RAW_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),                       # AWS temp key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),             # GitHub token
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),           # Slack token
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                    # OpenAI-style key
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
]
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
    r"access[_-]?key|private[_-]?key)\b\s*[:=]\s*['\"]?([^\s'\"#]{8,})"
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


def atomic_write_bytes(dest: str, data: bytes) -> None:
    """Write `data` to `dest` atomically (temp + os.replace). COPY, never link."""
    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".overlay-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
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
            if not inserted and ln.strip() == "@ecosystem.yaml":
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


def validate_manifest(cache: str) -> None:
    schema = os.path.join(SCRIPT_DIR, "..", "docs", "schemas",
                          "overlay-manifest.schema.yaml")
    schema = os.path.normpath(schema)
    manifest = os.path.join(cache, MANIFEST_FILE)
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


def dest_refusal(dest: str, content: bytes, consumer: Consumer,
                 lock: dict, overlay_name: str, precedence: int) -> str | None:
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
    # Effective scope: inline staged scope wins, else path-based classification.
    scope = staged_scope(content) or classify_file(dest)
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

def leak_check(content: bytes, target_scope: str = "org") -> list[str]:
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
    for raw_line in text.splitlines():
        for pat in RAW_SECRET_PATTERNS:
            if pat.search(raw_line):
                reasons.append(f"raw secret material: {raw_line.strip()[:60]}")
                break
        code = raw_line.split("#", 1)[0]            # drop trailing comment
        m = RAW_ASSIGN.search(code)
        if not m:
            continue
        value = m.group(2)
        if value.startswith(SECRET_URI_PREFIXES) or "${" in value:
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
            # on-disk override at this path rather than reverting to the source
            # default (Gate 2 — never a silent clobber). A fresh add has no
            # existing file, so the shipped default stands. Aligned by position;
            # if the structure diverged (count mismatch) keep the source default.
            if edata is not None:
                try:
                    erefs = list(jsonpath_refs(edata, path))
                except OverlayError:
                    erefs = []
                if erefs and len(erefs) == len(refs):
                    restored = False
                    for (container, key, current), (_, _, eprev) in zip(refs, erefs):
                        if eprev is not None and eprev != current:
                            container[key] = eprev
                            changed = True
                            restored = True
                    if restored:
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

class PlanItem:
    __slots__ = ("src", "dest", "kind", "prompt_fields", "on_conflict",
                 "source_bytes", "source_sha", "state", "reason",
                 "staged_bytes", "materialized_sha", "prompted_fields")

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
    # files[] exceptions whose dest was not produced by the walk (explicit add)
    for dest, exc in files_exc.items():
        if dest in seen:
            continue
        abs_src = os.path.join(src_dir, dest)
        if not os.path.exists(abs_src):
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

    lock_entry = (lock.get("overlays") or {}).get(overlay_name, {})
    lock_files = {f["dest"]: f for f in lock_entry.get("files", [])
                  if isinstance(f, dict) and f.get("dest")}

    planned_dests: set[str] = set()

    for it in items:
        abs_src = os.path.join(cache, source_root.rstrip("/"),
                               it.dest)
        try:
            with open(abs_src, "rb") as fh:
                it.source_bytes = fh.read()
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
        # Stage: scope tripwire + prompt-field injection.
        staged = inject_scope_tripwire(it.dest, it.source_bytes, it.kind, scope)
        staged, prompted = inject_prompt_fields(staged, it.prompt_fields,
                                                interactive, existing)
        it.staged_bytes = staged
        it.materialized_sha = sha256_bytes(staged)
        it.prompted_fields = prompted

        # Step 5 — CORE / structural / ownership refusal.
        refusal = dest_refusal(it.dest, staged, consumer, lock,
                               overlay_name, precedence)
        if refusal:
            it.state = "core-refused"
            it.reason = refusal
            continue

        # Step 9 — leak gate (before any write). Org/user materialization keeps
        # only the raw-secret check; the core-boundary scan runs at push time.
        leaks = leak_check(staged, scope)
        if leaks:
            it.state = "leak-refused"
            it.reason = "; ".join(leaks)[:300]
            continue

        planned_dests.add(it.dest)
        dest_abs = os.path.join(consumer.root, it.dest)
        on_disk = os.path.exists(dest_abs)
        in_lock = it.dest in lock_files

        if not in_lock:
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
              old_sha: str | None, interactive: bool) -> tuple[bytes | None, str]:
    """Resolve a locally-edited file against new upstream. Returns (bytes,state)."""
    dest_abs = os.path.join(consumer.root, it.dest)
    with open(dest_abs, "rb") as fh:
        live = fh.read()
    base = git_show_blob(cache, old_sha, it.src) if old_sha else None
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

def materialize(consumer: Consumer, cache: str, manifest: dict, defaults: dict,
                items: list[PlanItem], prune: list[dict], overlay_name: str,
                url: str, ref: str, resolved: str, manifest_sha: str,
                precedence: int, lock: dict, old_sha: str | None,
                dry: bool, assume_yes: bool, interactive: bool) -> dict:
    counts = {k: 0 for k in ("clean", "locally-modified", "upstream-ahead",
                             "conflict", "orphan", "core-refused",
                             "leak-refused", "skipped")}
    file_locks: list[dict] = []
    # Carry forward prompted_fields PATHS from the prior lock for skipped files.
    prev_files = {f["dest"]: f for f in
                  (lock.get("overlays") or {}).get(overlay_name, {})
                  .get("files", []) if isinstance(f, dict) and f.get("dest")}

    for it in items:
        if it.state in ("core-refused", "leak-refused"):
            counts[it.state] += 1
            sys.stderr.write(f"  REFUSE {it.dest}: {it.reason}\n")
            continue
        if it.state == "error":
            sys.stderr.write(f"  ERROR  {it.dest}: {it.reason}\n")
            continue

        if it.state == "skip":
            counts["skipped"] += 1
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
            merged, st = three_way(consumer, cache, it, old_sha, interactive)
            if merged is None:
                # kept local / skipped — preserve live, record live hash.
                counts["locally-modified" if "kept" in st else "conflict"] += 1
                dest_abs = os.path.join(consumer.root, it.dest)
                live_sha = sha256_file(dest_abs)
                prev = prev_files.get(it.dest, {})
                file_locks.append({
                    "src": it.src, "dest": it.dest,
                    "source_sha256": it.source_sha,
                    "materialized_sha256": live_sha,
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
                if not prompt_yes(f"  {it.dest} exists (user-owned). Overwrite?"):
                    counts["skipped"] += 1
                    continue
            # overlay-wins or confirmed prompt → write as a clean copy.

        # Behavioural gate (step 11) at first materialize. Counts are bumped
        # only AFTER this gate so reported counts match the files actually written.
        first_time = it.dest not in prev_files
        if it.kind in BEHAVIOURAL_KINDS and first_time:
            if not interactive:
                counts["skipped"] += 1
                sys.stderr.write(
                    f"  SKIP   {it.dest}: behavioural ({it.kind}) needs explicit "
                    f"[y]; --yes is not valid for behavioural files\n")
                continue
            print(f"\n  Behavioural file ({it.kind}): {it.dest}")
            preview = it.staged_bytes.decode("utf-8", errors="ignore")
            print("  --- preview (first 20 lines) ---")
            for ln in preview.splitlines()[:20]:
                print("   | " + ln)
            if not prompt_yes(f"  Materialize {it.kind} {it.dest}?"):
                counts["skipped"] += 1
                sys.stderr.write(f"  SKIP   {it.dest}: declined at behavioural gate\n")
                continue

        # Write (step 12) — atomic COPY.
        counts[record_state] += 1
        dest_abs = os.path.join(consumer.root, it.dest)
        if not dry:
            atomic_write_bytes(dest_abs, write_bytes)
        file_locks.append({
            "src": it.src, "dest": it.dest,
            "source_sha256": it.source_sha,
            "materialized_sha256": sha256_bytes(write_bytes),
            **({"prompted_fields": it.prompted_fields}
               if it.prompted_fields else {}),
        })

    # Prune (step 14).
    for pr in prune:
        if not pr["present"]:
            continue
        if pr["clean"]:
            counts["orphan"] += 1
            if not dry:
                os.remove(os.path.join(consumer.root, pr["dest"]))
        else:
            if interactive and prompt_yes(
                    f"  upstream removed {pr['dest']} but it is modified. Delete?"):
                counts["orphan"] += 1
                if not dry:
                    os.remove(os.path.join(consumer.root, pr["dest"]))
            else:
                sys.stderr.write(f"  KEEP   {pr['dest']}: orphan but modified\n")

    # Ecosystem fragment (step 13).
    fragment = manifest.get("ecosystem_fragment")
    if fragment:
        frag_src = os.path.join(cache, fragment)
        if os.path.exists(frag_src):
            if not dry:
                with open(frag_src, "rb") as fh:
                    atomic_write_bytes(os.path.join(consumer.root, fragment),
                                       fh.read())
            wired = consumer.ensure_ecosystem_import(fragment, dry)
            if wired:
                print(f"  @import {fragment} → CLAUDE.md")
        else:
            sys.stderr.write(
                f"  WARN   manifest declares ecosystem_fragment '{fragment}' "
                f"but it is absent from the overlay\n")

    # Lockfile (step 15).
    if not dry:
        prev_entry = (lock.get("overlays") or {}).get(overlay_name)
        new_entry = {
            "url": url, "ref": ref, "resolved_sha": resolved,
            "manifest_sha256": manifest_sha, "precedence": precedence,
            "last_synced": now_iso(), "files": file_locks,
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
                          source_root: str) -> None:
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
    entry.update({
        "repo": repo, "branch": ref, "role": "org-overlay",
        "contribute": True, "pull_interval_days": 7,
        "materialize": {
            "url": url, "ref": ref,
            "cache": f"{CACHE_BASE}/{name}/",
            "precedence": precedence,
            "select": select or ["**"],
        },
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
    """Resolve {url, ref, precedence, select} for a subscribed overlay."""
    sub = find_subscription(consumer, name)
    if sub is None:
        raise OverlayError(f"overlay '{name}' is not subscribed (run: add)")
    mat = sub.get("materialize") or {}
    return {
        "url": mat.get("url"),
        "ref": mat.get("ref") or sub.get("branch") or "main",
        "precedence": mat.get("precedence", 0),
        "select": mat.get("select") or ["**"],
    }


def cmd_add(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    # --yes ⇒ non-interactive: config/rule batch-confirm, behavioural files SKIP
    # (a behavioural [y] can never be auto-granted), prompts are not raised.
    interactive = not args.dry_run and not args.yes
    name = args.name
    ref = args.ref or "main"
    precedence = args.precedence
    select = args.select or ["**"]

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
        print("\n[dry-run] no files written.")
        return 0

    # Persist the subscription block BEFORE materializing so a crash mid-write
    # still leaves a recoverable subscription.
    upsert_upstream_block(consumer, name, args.git_url, ref, precedence,
                          select, defaults["source_root"])
    counts = materialize(consumer, cache, manifest, defaults, items, prune,
                         name, args.git_url, ref, resolved, manifest_sha,
                         precedence, lock, None, args.dry_run, args.yes,
                         interactive)
    report_counts("added", name, counts)
    return 0


def cmd_sync(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    names = [args.name] if args.name else [
        u["name"] for u in consumer.org_overlay_upstreams()]
    if not names:
        print("No org overlays subscribed (upstreams[] role: org-overlay).")
        return 0
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
        print("\n[dry-run] no files written.")
        return 0
    counts = materialize(consumer, cache, manifest, defaults, items, prune,
                         name, params["url"], params["ref"], resolved,
                         manifest_sha, params["precedence"], lock, old_sha,
                         args.dry_run, args.yes, interactive)
    report_counts("synced", name, counts)
    return 0


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
                                 lock, old_sha, False, args.yes, interactive)
            report_counts("applied", name, counts)
        except OverlayError as exc:
            sys.stderr.write(f"apply {name}: {exc}\n")
            rc = 1
    return rc


def cmd_status(consumer: Consumer, args) -> int:
    names = [args.name] if args.name else [
        u["name"] for u in consumer.org_overlay_upstreams()]
    if not names:
        print("No org overlays subscribed.")
        return 0
    lock = consumer.load_lock()
    for name in names:
        entry = (lock.get("overlays") or {}).get(name)
        sub = find_subscription(consumer, name)
        print(f"\n■ {name}")
        if sub is None:
            print("  (not in upstreams[] — orphaned lock entry)")
        if entry is None:
            print("  (subscribed but never materialized)")
            continue
        cache = cache_dir(consumer, name)
        head = resolved_sha(cache) if os.path.isdir(
            os.path.join(cache, ".git")) else None
        print(f"  resolved_sha : {entry.get('resolved_sha','?')[:12]}")
        print(f"  cache HEAD   : {head[:12] if head else '(no cache — offline)'}")
        if head and head != entry.get("resolved_sha"):
            print("  ↑ cache is AHEAD of lock — run 'sync'")
        last = entry.get("last_synced")
        if last:
            try:
                dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)
                days = (datetime.now(timezone.utc) - dt).days
                interval = (sub or {}).get("pull_interval_days", 7)
                flag = "  (stale)" if days > interval else ""
                print(f"  last_synced  : {last}  ({days}d ago){flag}")
            except ValueError:
                print(f"  last_synced  : {last}")
        # per-file state counts
        counts = {"clean": 0, "locally-modified": 0, "upstream-ahead": 0,
                  "conflict": 0, "orphan": 0}
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
                    elif it.state == "upstream-ahead":
                        counts["upstream-ahead"] += 1
                    elif it.state == "local-edit":
                        counts["locally-modified"] += 1
                    elif it.state in ("core-refused", "leak-refused"):
                        counts.setdefault(it.state, 0)
                        counts[it.state] += 1
                counts["orphan"] = len(prune)
            except OverlayError as exc:
                print(f"  (plan error: {exc})")
        print("  files        : " + "  ".join(
            f"{k}={v}" for k, v in counts.items()))
        print(f"  count(lock)  : {len(entry.get('files', []))}")
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
                if frag and not args.keep_files:
                    consumer.drop_ecosystem_import(frag)
                    fp = os.path.join(consumer.root, frag)
                    if os.path.exists(fp):
                        os.remove(fp)
            except OverlayError:
                pass
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
    a.add_argument("--dry-run", action="store_true", help="plan only, no writes")
    a.add_argument("--yes", action="store_true",
                   help="batch-confirm non-behavioural (behavioural still gated)")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("sync", help="pull cache + re-materialize (3-way vs lock)")
    s.add_argument("name", nargs="?", help="overlay name (default: all)")
    s.add_argument("--dry-run", action="store_true", help="plan only, no writes")
    s.add_argument("--yes", action="store_true",
                   help="batch-confirm non-behavioural; skip interactive prompts")
    s.set_defaults(func=cmd_sync)

    ap = sub.add_parser("apply", help="OFFLINE re-materialize from cache + lock")
    ap.add_argument("name", nargs="?", help="overlay name (default: all)")
    ap.add_argument("--yes", action="store_true", help="batch-confirm non-behavioural")
    ap.set_defaults(func=cmd_apply)

    st = sub.add_parser("status", help="resolved_sha vs cache HEAD + file counts")
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
