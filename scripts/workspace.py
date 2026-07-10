#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Standalone workspace engine — bind member repos + config-overlay
subscriptions into a named workspace.

A *workspace* (workflow/workspaces/<id>.yaml) is a user-authored binding of
member repos and config-overlay subscriptions describing "what happens when":
the working set a session operates on. This engine creates / lists / validates
those definitions, records the resolved reality of `role: code` member clones in
a generated `workspaces.lock.yaml`, and delegates config-overlay materialization
to its sibling `scripts/overlay.py` (subprocess — never an import).

Design invariants (see the increment-1 build spec):
  * STANDALONE — no external provider is required or imported. Passing a bare
    name where a git URL is expected degrades gracefully (exit 3): the name→repos
    resolver is an optional, capability-detected seam that is simply absent here.
  * overlay.py is delegated to, never rewritten or imported. The workspace layer
    sits ABOVE it; the CLI argv is the only contract.
  * `role: code` members are a security surface: they clone into an IGNORED
    location under `.bridge/` and are additionally guarded by a marked
    `.git/info/exclude` block (the same discipline overlay.py uses) so a public
    fork can never `git add -A`-publish foreign code.
  * Mutating verbs (create / add-repo / remove-repo) refuse to run off a user/*
    branch; read-only verbs (list / validate / status) run anywhere.

The small helpers below are deliberately reimplemented locally (not imported
from overlay.py) so the engine stays self-contained.
"""

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OVERLAY_PY = os.path.join(SCRIPT_DIR, "overlay.py")

WORKSPACES_DIR = "workflow/workspaces"
LOCK_FILE = "workspaces.lock.yaml"
MEMBER_BASE = ".bridge/workspaces"
SCHEMA = "docs/schemas/workspace.schema.yaml"

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SCP_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:.+$")
ALLOWED_URL_SCHEMES = ("https", "ssh", "file")

# Field order used when (re)writing a definition — known keys first, extras kept.
DEF_ORDER = ["schema_version", "id", "title", "description", "directory",
             "created_at", "updated_at", "overlays", "repos", "session_ref",
             "x-provider"]


class WorkspaceError(Exception):
    """User-facing, fail-closed error — printed without a traceback (exit 1)."""


# ---------------------------------------------------------------------------
# Low-level helpers (reimplemented locally — NOT imported from overlay.py)
# ---------------------------------------------------------------------------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_bytes(dest: str, data: bytes) -> None:
    """Write `data` to `dest` atomically (temp + os.replace)."""
    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".workspace-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_git(args: list, cwd=None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise WorkspaceError(
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
        raise WorkspaceError(f"malformed YAML in {path}: {exc}")


def dump_yaml(data) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=100)


def dump_definition(data: dict) -> str:
    """Dump a workspace definition with known keys ordered, extras preserved."""
    ordered = {}
    for k in DEF_ORDER:
        if k in data:
            ordered[k] = data[k]
    for k in data:
        if k not in ordered:
            ordered[k] = data[k]
    return dump_yaml(ordered)


# ---------------------------------------------------------------------------
# git-URL classification + trust guard (security-critical)
# ---------------------------------------------------------------------------

def classify_target(arg: str):
    """Classify the `add-repo` second positional.

    Returns ("url", <url>) for a trusted git URL, or ("provider", <name>) for a
    bare provider/workspace name (the optional, absent-here resolver seam).
    Raises WorkspaceError (exit 1) for a dangerous scheme, an argv-injection
    argument, or an ambiguous value.
    """
    if arg.startswith("-"):
        raise WorkspaceError(
            f"refusing an argument that begins with '-' (argv-injection guard): "
            f"{arg!r}. Pass a git URL after '--' if that is really the path.")
    if "://" in arg:
        scheme = arg.split("://", 1)[0].lower()
        if scheme in ALLOWED_URL_SCHEMES:
            return ("url", arg)
        raise WorkspaceError(
            f"refusing disallowed/dangerous URL scheme '{scheme}://' — only "
            f"https://, ssh://, file:// and scp-form user@host:path are trusted.")
    if "::" in arg:
        # git remote-helper transports (ext::, fd::, …) are a remote-code-execution
        # surface — refuse them outright.
        raise WorkspaceError(
            f"refusing a git remote-helper transport in {arg!r} — only https://, "
            f"ssh://, file:// and scp-form user@host:path are trusted.")
    if SCP_RE.match(arg):
        return ("url", arg)
    if "/" not in arg and SLUG_RE.match(arg):
        return ("provider", arg)
    raise WorkspaceError(
        f"{arg!r} is not a recognized git URL. Use https://, ssh://, file:// or "
        f"scp-form user@host:path.")


def derive_member_slug(url: str) -> str:
    """last URL path segment, `.git` stripped, lowercased-kebab."""
    s = url
    if "://" in s:
        s = s.split("://", 1)[1]
    seg = re.split(r"[/:]", s.rstrip("/"))[-1]
    if seg.endswith(".git"):
        seg = seg[:-4]
    slug = seg.lower()
    if not SLUG_RE.match(slug):
        raise WorkspaceError(
            f"cannot derive a valid member slug from URL {url!r} (got {slug!r}) — "
            f"pass one via the definition or a differently-named remote.")
    return slug


def default_branch(clone_abs: str) -> str:
    p = run_git(["-C", clone_abs, "symbolic-ref", "--short", "HEAD"], check=False)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip()
    p = run_git(["-C", clone_abs, "rev-parse", "--abbrev-ref", "HEAD"], check=False)
    if p.returncode == 0 and p.stdout.strip() and p.stdout.strip() != "HEAD":
        return p.stdout.strip()
    return "HEAD"


# ---------------------------------------------------------------------------
# Consumer — the Bridge instance we operate on
# ---------------------------------------------------------------------------

class Consumer:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.lock_path = os.path.join(self.root, LOCK_FILE)

    # --- branch gate (HARD; honours the shared env escape hatch) ----------
    def current_branch(self):
        proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"],
                       cwd=self.root, check=False)
        if proc.returncode == 0:
            return proc.stdout.strip()
        return None

    def require_user_branch(self) -> None:
        # Reuse the SAME env name as overlay.py so the shared test harness works.
        if os.environ.get("BRIDGE_OVERLAY_ALLOW_ANY_BRANCH") == "1":
            return
        branch = self.current_branch()
        if branch is None:
            raise WorkspaceError(
                "not a git repo (or detached HEAD) — workspace mutations only run "
                "on a user/* branch; CORE branches must stay clean.")
        if not branch.startswith("user/"):
            raise WorkspaceError(
                f"refusing to mutate on '{branch}': workspace create/add-repo/"
                f"remove-repo only run on a user/* branch (CORE branches never "
                f"carry instance state).")

    # --- schema / template resolution (consumer first, then this repo) -----
    def _resolve_repo_file(self, rel: str):
        for base in (self.root, os.path.dirname(SCRIPT_DIR)):
            p = os.path.join(base, rel)
            if os.path.exists(p):
                return p
        return None

    def schema_path(self):
        return self._resolve_repo_file(SCHEMA)

    def template_base(self) -> dict:
        # The definition is built deterministically in-engine; the _template.yaml
        # is the discoverable human-authoring scaffold. If present, its scalar
        # seeds are inherited, but the engine always sets the managed fields.
        tpl = self._resolve_repo_file(os.path.join(WORKSPACES_DIR, "_template.yaml"))
        if tpl:
            data = load_yaml_file(tpl)
            if isinstance(data, dict):
                base = {k: v for k, v in data.items()
                        if k not in ("id", "title", "description", "directory",
                                     "created_at", "updated_at", "overlays",
                                     "repos", "session_ref", "x-provider")}
                return base
        return {}

    # --- definitions ------------------------------------------------------
    def def_path(self, ws_id: str) -> str:
        return os.path.join(self.root, WORKSPACES_DIR, f"{ws_id}.yaml")

    def load_definition(self, ws_id: str):
        path = self.def_path(ws_id)
        data = load_yaml_file(path)
        if data is None:
            raise WorkspaceError(
                f"workspace '{ws_id}' not found ({WORKSPACES_DIR}/{ws_id}.yaml).")
        if not isinstance(data, dict):
            raise WorkspaceError(f"workspace definition {path} is not a mapping.")
        return data, path

    def write_definition(self, ws_id: str, data: dict) -> None:
        header = (
            "# yaml-language-server: $schema=../../docs/schemas/workspace.schema.yaml\n"
            "# Workspace definition — maintained by scripts/workspace.py.\n")
        atomic_write_bytes(self.def_path(ws_id),
                           (header + dump_definition(data)).encode("utf-8"))

    def list_definitions(self):
        pattern = os.path.join(self.root, WORKSPACES_DIR, "*.yaml")
        return sorted(p for p in glob.glob(pattern)
                      if not os.path.basename(p).startswith("_"))

    # --- lock -------------------------------------------------------------
    def load_lock(self):
        return load_yaml_file(self.lock_path)

    def write_lock(self, lock: dict) -> None:
        header = (
            "# yaml-language-server: $schema=./docs/schemas/workspaces-lock.schema.yaml\n"
            "# GENERATED by scripts/workspace.py — do not hand-edit.\n")
        atomic_write_bytes(self.lock_path,
                           (header + dump_yaml(lock)).encode("utf-8"))

    # --- .git/info/exclude marked block (belt-and-suspenders, per overlay.py)
    def _exclude_markers(self, ws_id: str):
        return (
            f"# >>> workspace:{ws_id} (managed by scripts/workspace.py — do not edit) >>>",
            f"# <<< workspace:{ws_id} <<<")

    def _strip_marked_block(self, text: str, begin: str, end: str) -> str:
        if begin not in text:
            return text
        out = []
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

    def _git_exclude_path(self):
        proc = run_git(["rev-parse", "--git-path", "info/exclude"],
                       cwd=self.root, check=False)
        if proc.returncode != 0:
            return None
        rel = proc.stdout.strip()
        if not rel:
            return None
        return rel if os.path.isabs(rel) else os.path.join(self.root, rel)

    def ensure_git_exclude_block(self, ws_id: str, dests: list) -> bool:
        """Keep member code clones OUT of git via the LOCAL, UNTRACKED
        .git/info/exclude (never .gitignore, which a public fork would publish).
        Idempotent; each dest listed as `/<path>/`."""
        path = self._git_exclude_path()
        if path is None:
            return False
        begin, end = self._exclude_markers(ws_id)
        body = [begin,
                "# workspace member code clones — kept OUT of git so a fork",
                "# (public by default) can't publish foreign code via `git add -A`.",
                "# This is the local, untracked exclude file; dropped on remove.",
                *(f"/{d.strip('/')}/" for d in sorted(set(dests))),
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
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, new.encode("utf-8"))
        return True

    def drop_git_exclude_block(self, ws_id: str) -> None:
        path = self._git_exclude_path()
        if path is None or not os.path.exists(path):
            return
        begin, end = self._exclude_markers(ws_id)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        new = self._strip_marked_block(text, begin, end)
        if new != text:
            atomic_write_bytes(path, new.encode("utf-8"))


# ---------------------------------------------------------------------------
# Definition / lock helpers
# ---------------------------------------------------------------------------

def find_code_member(definition: dict, name: str):
    for m in definition.get("repos") or []:
        if isinstance(m, dict) and m.get("role") == "code" and m.get("name") == name:
            return m
    return None


def code_member_paths(definition: dict):
    return [m["path"] for m in definition.get("repos") or []
            if isinstance(m, dict) and m.get("role") == "code" and m.get("path")]


def definition_overlay_names(definition: dict) -> list[str]:
    names: list[str] = []
    for o in definition.get("overlays") or []:
        if isinstance(o, dict):
            name = o.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def rebuild_workspace_lock(consumer: Consumer, ws_id: str, definition: dict) -> None:
    """Rewrite the ws entry in workspaces.lock.yaml from the definition's live
    role:code member clones (pinning each to its actual HEAD)."""
    lock = consumer.load_lock()
    if not isinstance(lock, dict):
        lock = {}
    lock.setdefault("schema_version", 1)
    workspaces = lock.setdefault("workspaces", {})
    if not isinstance(workspaces, dict):
        workspaces = {}
        lock["workspaces"] = workspaces

    repos = []
    for m in definition.get("repos") or []:
        if not (isinstance(m, dict) and m.get("role") == "code"):
            continue
        clone_abs = os.path.join(consumer.root, m["path"])
        if not os.path.isdir(clone_abs):
            # `.bridge/` is gitignored, so a committed definition on a fresh
            # checkout has NO clone yet — the normal state on machine B. Omit the
            # member from the lock (never crash) so add/remove of OTHER members
            # still works; the definition entry is left intact.
            sys.stderr.write(
                f"workspace: member '{m.get('name')}' clone missing at "
                f"{clone_abs} — omitted from lock; re-subscribe to materialize.\n")
            continue
        sha = run_git(["-C", clone_abs, "rev-parse", "HEAD"]).stdout.strip()
        repos.append({
            "name": m["name"],
            "url": m["url"],
            "ref": m.get("ref") or default_branch(clone_abs),
            "resolved_sha": sha,
            "path": m["path"],
        })
    workspaces[ws_id] = {
        "updated_at": now_iso(),
        "repos": repos,
        "overlays": definition_overlay_names(definition),
    }
    consumer.write_lock(lock)


# ---------------------------------------------------------------------------
# overlay.py delegation (subprocess — never an import)
# ---------------------------------------------------------------------------

def _overlay_universe(consumer: Consumer):
    """Names known to overlay.py: overlays.lock.yaml keys ∪ .bridge/overlays dirs."""
    names = set()
    lock = load_yaml_file(os.path.join(consumer.root, "overlays.lock.yaml"))
    if isinstance(lock, dict):
        names |= set((lock.get("overlays") or {}).keys())
    cache = os.path.join(consumer.root, ".bridge", "overlays")
    if os.path.isdir(cache):
        names |= {d for d in os.listdir(cache)
                  if os.path.isdir(os.path.join(cache, d))}
    return names


def _overlay_add(consumer: Consumer, url: str, ref, precedence):
    cmd = [sys.executable, OVERLAY_PY, "--repo-root", consumer.root,
           "add", url, "--ref", ref or "main"]
    if precedence:
        cmd += ["--precedence", str(precedence)]
    # Inherit stdin/stdout/stderr so overlay.py's own prompts + gates run
    # unmodified (its exit codes are preserved verbatim).
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise WorkspaceError(
            f"overlay.py add failed (exit {proc.returncode}) for {url}")


def _overlay_remove(consumer: Consumer, name: str):
    cmd = [sys.executable, OVERLAY_PY, "--repo-root", consumer.root, "remove", name]
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise WorkspaceError(
            f"overlay.py remove failed (exit {proc.returncode}) for {name}")


# ---------------------------------------------------------------------------
# Shared-registry publish — Option 3 write-through (ADDITIVE identity mirror)
# ---------------------------------------------------------------------------

def _origin_remote(clone_abs: str):
    """Best-effort `git remote get-url origin` for a role:code member clone."""
    if not os.path.isdir(clone_abs):
        return None
    p = run_git(["-C", clone_abs, "remote", "get-url", "origin"], check=False)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip()
    return None


def _publish_identity(consumer: Consumer, ws_id: str) -> None:
    """Mirror this workspace's IDENTITY into the shared cross-tool registry.

    ADDITIVE: the repo-local definition + materialization stay the source of
    record; this publishes a namespaced mirror — name (our `title` mapped to the
    shared `name`), the workspace's own `directory:` as the PRIMARY (unlabelled,
    position-0) directory, the role:code members' clone directories after it
    (label "repo"), their git remotes, and our `extensions["open-bridge"]` slice
    (overlays + repos) — into $WORKSPACES_DIR/workspaces.json (else
    ~/.workspaces/), keyed by an INSTANCE-QUALIFIED open-bridge id
    (`<hash(repo root)>:<slug>`) so successive publishes from THIS instance
    converge on one entry (a removal shrinks the mirror) while a second Bridge
    instance sharing the slug never clobbers this one.

    A shared-registry hiccup — a version-guarded newer file, an unreadable
    registry, an import failure — NEVER fails the local command: it warns and
    returns. Local materialization has already succeeded by this point.
    """
    try:
        if SCRIPT_DIR not in sys.path:
            sys.path.insert(0, SCRIPT_DIR)
        # Sibling module in scripts/ — resolved at runtime via SCRIPT_DIR on
        # sys.path[0] when running `python3 scripts/workspace.py`. Pyright can't
        # follow that dynamic path from the repo root, so silence the static-only
        # miss (the import is exercised green by the workspace suite).
        import workspace_registry  # pyright: ignore[reportMissingImports]
    except Exception as exc:  # pragma: no cover - defensive
        sys.stderr.write(
            f"workspace: shared-registry publish skipped (module unavailable: {exc})\n")
        return
    try:
        definition = load_yaml_file(consumer.def_path(ws_id))
        if not isinstance(definition, dict):
            return
        directories = []
        d = definition.get("directory")
        if isinstance(d, str) and d:
            if "${" in d:
                # An uninterpolated ${var} means the working dir is not yet
                # resolvable — publish NO bogus path (position 0 stays reserved
                # for a real primary directory once the variable is set).
                sys.stderr.write(
                    f"workspace: skipping directory publish for '{ws_id}' — "
                    f"'{d}' still holds an uninterpolated ${{...}} variable.\n")
            else:
                p = os.path.expanduser(d)
                if not os.path.isabs(p):
                    p = os.path.join(consumer.root, p)
                # PRIMARY entry — no label; position 0 marks it the working dir.
                directories.append({"path": os.path.realpath(p)})
        git_remotes = []
        repos_ext = []
        for m in definition.get("repos") or []:
            if not isinstance(m, dict):
                continue
            entry = {k: m.get(k) for k in ("url", "role", "name", "ref")
                     if m.get(k) is not None}
            if entry:
                repos_ext.append(entry)
            if m.get("role") == "code" and m.get("path"):
                clone_abs = os.path.join(consumer.root, m["path"])
                directories.append({"path": clone_abs, "label": "repo"})
                remote = _origin_remote(clone_abs) or m.get("url")
                if remote:
                    git_remotes.append(remote)
        open_bridge_ext = {
            "overlays": definition_overlay_names(definition),
            "repos": repos_ext,
        }
        title = definition.get("title") or ws_id
        # Instance-qualify the mirror id so two Bridge instances that share a
        # workspace slug (AGENTS.md § Multiple Instances) never clobber each
        # other's row: <first-12-hex of sha256(realpath repo root)>:<slug>.
        ref = (hashlib.sha256(
            os.path.realpath(consumer.root).encode()).hexdigest()[:12]
            + ":" + ws_id)
        registry = workspace_registry.Registry()
        registry.publish_workspace(
            ref, str(title),
            directories=directories,
            git_remotes=git_remotes,
            open_bridge_ext=open_bridge_ext,
        )
    except Exception as exc:  # the additive mirror must never break local state
        sys.stderr.write(
            f"workspace: shared-registry publish failed (local state unaffected): {exc}\n")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_create(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    ws_id = args.name
    if not SLUG_RE.match(ws_id):
        raise WorkspaceError(
            f"invalid workspace id '{ws_id}' — must be lowercase-kebab "
            f"(^[a-z][a-z0-9-]*$).")
    if os.path.exists(consumer.def_path(ws_id)):
        raise WorkspaceError(
            f"workspace '{ws_id}' already exists at {WORKSPACES_DIR}/{ws_id}.yaml.")
    ts = now_iso()
    data = consumer.template_base()
    data["schema_version"] = 1
    data["id"] = ws_id
    data["title"] = args.title or ws_id
    if args.description:
        data["description"] = args.description
    if getattr(args, "dir", None):
        data["directory"] = args.dir
    data["created_at"] = ts
    data["updated_at"] = ts
    data["overlays"] = []
    data["repos"] = []
    consumer.write_definition(ws_id, data)
    print(f"created {WORKSPACES_DIR}/{ws_id}.yaml")
    return 0


def cmd_list(consumer: Consumer, _args) -> int:
    defs = consumer.list_definitions()
    if not defs:
        print("No workspaces defined yet (workflow/workspaces/*.yaml).")
        return 0
    lock = consumer.load_lock() or {}
    lws = lock.get("workspaces") or {}
    rows = []
    for path in defs:
        d = load_yaml_file(path) or {}
        wid = str(d.get("id") or os.path.splitext(os.path.basename(path))[0])
        title = str(d.get("title") or "")
        ncode = len(((lws.get(wid) or {}).get("repos")) or [])
        nover = len(d.get("overlays") or [])
        dirv = str(d.get("directory") or "")
        rows.append((wid, title, str(ncode), str(nover), dirv))
    headers = ("ID", "TITLE", "#CODE", "#OVERLAY", "DIR")
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for r in rows:
        print(fmt.format(*r))
    return 0


def _fallback_validate(data: dict):
    """Structural validation used only when check-jsonschema is unavailable."""
    for key in ("schema_version", "id", "title"):
        if key not in data:
            return False, f"missing required key '{key}'"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if not (isinstance(data.get("id"), str) and SLUG_RE.match(data["id"])):
        return False, "id must be lowercase-kebab"
    if not (isinstance(data.get("title"), str) and data["title"]):
        return False, "title must be a non-empty string"
    for m in data.get("repos") or []:
        if not isinstance(m, dict):
            return False, "repos[] entries must be mappings"
        if "url" not in m or "role" not in m:
            return False, "each repo needs url + role"
        if m.get("role") not in ("code", "config"):
            return False, f"invalid role '{m.get('role')}' (code|config)"
    for o in data.get("overlays") or []:
        if not (isinstance(o, dict) and o.get("name")):
            return False, "each overlay needs a name"
    return True, ""


def validate_one(path: str, schema):
    data = load_yaml_file(path)
    if not isinstance(data, dict):
        return False, "not a YAML mapping"
    base = os.path.splitext(os.path.basename(path))[0]
    if data.get("id") != base:
        return False, f"id '{data.get('id')}' != filename basename '{base}'"
    if schema and shutil.which("check-jsonschema"):
        proc = subprocess.run(
            ["check-jsonschema", "--schemafile", schema, path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            tail = proc.stdout.strip().splitlines()
            return False, "schema: " + (tail[-1] if tail else "invalid")
        return True, ""
    return _fallback_validate(data)


def cmd_validate(consumer: Consumer, args) -> int:
    if getattr(args, "name", None):
        path = consumer.def_path(args.name)
        if not os.path.exists(path):
            raise WorkspaceError(
                f"workspace '{args.name}' not found ({WORKSPACES_DIR}/{args.name}.yaml).")
        files = [path]
    else:
        files = consumer.list_definitions()
    if not files:
        print("No workspace definitions to validate.")
        return 0
    schema = consumer.schema_path()
    failed = 0
    for f in files:
        ok, reason = validate_one(f, schema)
        base = os.path.basename(f)
        if ok:
            print(f"PASS — {base}")
        else:
            print(f"FAIL — {base}: {reason}")
            failed += 1
    return 1 if failed else 0


def cmd_status(consumer: Consumer, args) -> int:
    if getattr(args, "name", None):
        path = consumer.def_path(args.name)
        if not os.path.exists(path):
            print(f"workspace '{args.name}' not found — nothing to report.")
            return 0
        defs = [path]
    else:
        defs = consumer.list_definitions()
    if not defs:
        print("No workspaces defined.")
        return 0
    lock = consumer.load_lock() or {}
    lws = lock.get("workspaces") or {}
    for path in defs:
        d = load_yaml_file(path) or {}
        wid = str(d.get("id") or os.path.splitext(os.path.basename(path))[0])
        print(f"\n■ {wid} — {d.get('title', '')}")
        locked = {r.get("name"): r for r in ((lws.get(wid) or {}).get("repos") or [])}
        code_members = [m for m in (d.get("repos") or [])
                        if isinstance(m, dict) and m.get("role") == "code"]
        if not code_members:
            print("  code members : (none)")
        for m in code_members:
            name = m.get("name")
            clone_abs = os.path.join(consumer.root, m.get("path", ""))
            if not os.path.isdir(clone_abs):
                state = "missing"
            else:
                head = run_git(["-C", clone_abs, "rev-parse", "HEAD"],
                               check=False).stdout.strip()
                pin = (locked.get(name) or {}).get("resolved_sha")
                if pin and head == pin:
                    state = "clean"
                elif pin:
                    state = "ahead"
                else:
                    state = "unpinned"
            print(f"  code · {name}: {state}")
        overs = definition_overlay_names(d)
        print("  overlays     : " + (", ".join(overs) if overs else "(none)"))
    return 0


def _add_code(consumer: Consumer, args, url: str) -> int:
    ws_id = args.name
    definition, _ = consumer.load_definition(ws_id)
    member = derive_member_slug(url)

    existing = find_code_member(definition, member)
    if existing is not None:
        same_url = existing.get("url") == url
        same_ref = (args.ref is None) or (existing.get("ref") == args.ref)
        if same_url and same_ref:
            print(f"'{member}' is already a member of workspace '{ws_id}' — no change.")
            return 0
        raise WorkspaceError(
            f"member slug '{member}' already exists in '{ws_id}' with a different "
            f"url/ref — remove it first (remove-repo {ws_id} {member}).")

    clone_rel = f"{MEMBER_BASE}/{ws_id}/{member}"
    clone_abs = os.path.join(consumer.root, clone_rel)
    if os.path.exists(clone_abs):
        shutil.rmtree(clone_abs, ignore_errors=True)
    os.makedirs(os.path.dirname(clone_abs), exist_ok=True)

    clone_args = ["clone", "--recurse-submodules"]
    if args.ref:
        clone_args += ["--branch", args.ref]
    clone_args += [url, clone_abs]
    run_git(clone_args)

    sha = run_git(["-C", clone_abs, "rev-parse", "HEAD"]).stdout.strip()
    ref = args.ref or default_branch(clone_abs)

    # Ordering (S5): clone → exclude (incl. the NEW member path) → write the
    # definition → rebuild the lock. Arming the exclude block BEFORE the clone is
    # recorded in the tracked definition closes the crash window where a public
    # fork could `git add -A`-publish freshly cloned foreign code.
    consumer.ensure_git_exclude_block(
        ws_id, code_member_paths(definition) + [clone_rel])

    definition.setdefault("repos", [])
    definition["repos"].append({
        "url": url,
        "role": "code",
        "name": member,
        "ref": ref,
        "path": clone_rel,
    })
    definition["updated_at"] = now_iso()
    consumer.write_definition(ws_id, definition)

    rebuild_workspace_lock(consumer, ws_id, definition)

    print(f"added code member '{member}' @ {sha} → {clone_rel}")
    return 0


def _add_config(consumer: Consumer, args, url: str) -> int:
    ws_id = args.name
    definition, _ = consumer.load_definition(ws_id)

    before = _overlay_universe(consumer)
    _overlay_add(consumer, url, args.ref, getattr(args, "precedence", None))
    after = _overlay_universe(consumer)
    new_names = sorted(after - before)

    existing = set(definition_overlay_names(definition))
    for nm in new_names:
        if nm not in existing:
            definition.setdefault("overlays", []).append({"name": nm})
            existing.add(nm)
    definition["updated_at"] = now_iso()
    consumer.write_definition(ws_id, definition)

    print("delegated config overlay(s) to overlay.py: "
          + (", ".join(new_names) if new_names else "(no new overlay)"))
    return 0


def cmd_add_repo(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    kind, target = classify_target(args.git_url)
    if kind == "provider":
        # Optional, capability-detected name→repos resolver seam. No provider is
        # available in a standalone Bridge, so degrade gracefully (exit 3).
        sys.stderr.write(
            f"'{target}' is not a git URL. Resolving a workspace/provider name to "
            f"repos needs an external provider that is not available in this "
            f"standalone Bridge. Pass an explicit git URL, or install a provider.\n")
        return 3
    if args.role == "config":
        return _add_config(consumer, args, target)
    return _add_code(consumer, args, target)


def _remove_code(consumer: Consumer, ws_id: str, definition: dict, member: str) -> int:
    clone_rel = f"{MEMBER_BASE}/{ws_id}/{member}"
    clone_abs = os.path.join(consumer.root, clone_rel)

    # Ordering (S5): update the metadata FIRST (definition + lock + exclude),
    # then rmtree the clone LAST. If the delete is interrupted, the definition /
    # lock / exclude are already consistent (member gone); a stray clone dir is
    # inert (already excluded and no longer referenced).
    definition["repos"] = [
        m for m in (definition.get("repos") or [])
        if not (isinstance(m, dict) and m.get("role") == "code"
                and m.get("name") == member)]
    definition["updated_at"] = now_iso()
    consumer.write_definition(ws_id, definition)

    rebuild_workspace_lock(consumer, ws_id, definition)

    remaining = code_member_paths(definition)
    if remaining:
        consumer.ensure_git_exclude_block(ws_id, remaining)
    else:
        consumer.drop_git_exclude_block(ws_id)

    if os.path.isdir(clone_abs):
        shutil.rmtree(clone_abs, ignore_errors=True)

    print(f"removed code member '{member}' from workspace '{ws_id}'")
    return 0


def _remove_config(consumer: Consumer, ws_id: str, definition: dict, member: str) -> int:
    _overlay_remove(consumer, member)
    definition["overlays"] = [
        o for o in (definition.get("overlays") or [])
        if not (isinstance(o, dict) and o.get("name") == member)]
    definition["updated_at"] = now_iso()
    consumer.write_definition(ws_id, definition)
    print(f"removed config overlay '{member}' from workspace '{ws_id}'")
    return 0


def cmd_remove_repo(consumer: Consumer, args) -> int:
    consumer.require_user_branch()
    ws_id = args.name
    definition, _ = consumer.load_definition(ws_id)
    member = args.member
    if find_code_member(definition, member) is not None:
        return _remove_code(consumer, ws_id, definition, member)
    if member in definition_overlay_names(definition):
        return _remove_config(consumer, ws_id, definition, member)
    raise WorkspaceError(
        f"'{member}' is neither a code member nor an overlay of workspace "
        f"'{ws_id}'.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="workspace",
        description="Standalone workspace engine — bind member repos + config "
                    "overlays into a named workspace.")
    p.add_argument("--repo-root", help="repo root (default: $BRIDGE_REPO_ROOT or "
                   "the repo this script ships in)")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("create", help="create a new workspace definition")
    c.add_argument("name")
    c.add_argument("--dir", dest="dir", help="working directory the workspace maps to")
    c.add_argument("--title", help="human-readable label (default: the id)")
    c.add_argument("--description", help="one-line purpose")
    c.set_defaults(func=cmd_create)

    li = sub.add_parser("list", help="list workspaces")
    li.set_defaults(func=cmd_list)

    v = sub.add_parser("validate", help="validate workspace definition(s)")
    v.add_argument("name", nargs="?", help="workspace id (default: all)")
    v.set_defaults(func=cmd_validate)

    st = sub.add_parser("status", help="member drift status (read-only)")
    st.add_argument("name", nargs="?", help="workspace id (default: all)")
    st.set_defaults(func=cmd_status)

    # `subscribe` / `unsubscribe` are the canonical verbs; `add-repo` /
    # `remove-repo` stay as aliases so existing scripts and the older vocabulary
    # keep working. Both names dispatch to the same handler.
    ar = sub.add_parser("subscribe", aliases=["add-repo"],
                        help="subscribe a code member or config overlay to the workspace")
    ar.add_argument("name")
    ar.add_argument("git_url", help="clone URL (or, seam-only, a provider name)")
    ar.add_argument("--ref", help="git ref (default: the remote's default branch)")
    ar.add_argument("--role", choices=["code", "config"], default="code")
    ar.add_argument("--precedence", type=int, default=None,
                    help="config overlays only — layering order passed to overlay.py")
    ar.set_defaults(func=cmd_add_repo)

    rr = sub.add_parser("unsubscribe", aliases=["remove-repo"],
                        help="unsubscribe a code member or config overlay")
    rr.add_argument("name")
    rr.add_argument("member")
    rr.set_defaults(func=cmd_remove_repo)
    return p


def resolve_repo_root(args) -> str:
    if args.repo_root:
        return os.path.abspath(args.repo_root)
    env = os.environ.get("BRIDGE_REPO_ROOT")
    if env:
        return os.path.abspath(env)
    return os.path.dirname(SCRIPT_DIR)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = resolve_repo_root(args)
    try:
        os.chdir(root)
    except OSError as exc:
        sys.stderr.write(f"ERROR: cannot enter repo root {root}: {exc}\n")
        return 2
    consumer = Consumer(root)
    try:
        rc = args.func(consumer, args)
        # After a mutating verb succeeds, publish the workspace identity into the
        # shared registry (additive mirror — never affects the rc or local state).
        if rc == 0 and args.func in (cmd_create, cmd_add_repo, cmd_remove_repo):
            _publish_identity(consumer, args.name)
        return rc
    except WorkspaceError as exc:
        sys.stderr.write(f"workspace: {exc}\n")
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        sys.stderr.write("\nworkspace: interrupted\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
