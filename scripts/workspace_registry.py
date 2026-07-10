#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Standalone conformant reader/writer of the tool-neutral workspace registry.

The registry is a *shared, multi-writer-safe* JSON file that lives OUTSIDE any
single tool — `$WORKSPACES_DIR/workspaces.json`, else `~/.workspaces/workspaces.json`
— and is the canonical answer to "which project am I in?" agreed across tools. It
is authored by an external design (schema v2, `version: 2`); this module is a
first-class, standalone WRITER of it — no external tool is imported, shelled out
to, or assumed present. Pure stdlib.

Because other tools write the SAME file, every mutation is SAFETY-CRITICAL: a bug
that drops a field or another tool's data corrupts their real registry. The write
path therefore follows the documented multi-writer protocol EXACTLY:

    take the advisory lock (`<dir>/.lock`, flock) → read → modify in memory →
    atomic replace (write `workspaces.json.tmp` + os.replace) → release the lock.

Protocol invariants enforced here:
  * **Preserve unknown fields** — unrecognized top-level keys and unrecognized
    per-workspace keys round-trip untouched.
  * **Never touch another tool's extension slice** — a writer edits only the
    shared identity fields plus its OWN `extensions["open-bridge"]` namespace.
  * **version is max-monotonic** — MAX_SUPPORTED_VERSION = 2; the on-disk
    `version` is COERCED (int, the string `"2"`, and the float `2.0` all mean 2)
    before comparison. A file whose coerced version exceeds MAX may be READ but
    is REFUSED for WRITE (a clean error, never a clobber). Writes always emit
    `version: 2` (int).
  * **De-dup by identity on BOTH create paths** — `upsert_workspace` de-dups on
    a shared git remote OR a shared canonical directory (§D); `publish_workspace`
    additionally does a *guarded structural adopt* (§C.3 rule 3) so its owning
    mirror CONVERGES onto a peer tool's pre-existing row for the same project
    instead of minting a duplicate — but never onto a second such row, and never
    onto a row that already carries an `extensions["open-bridge"]` slice (one of
    ours / another instance's).
  * **Fail closed on anomalies** — an unparseable file, or a missing/non-numeric
    `version`, REFUSES the write (a clean error; the on-disk bytes are left
    untouched, nothing is rotated or guessed). ONLY a genuine older file (coerced
    `version <= 1`, the documented v1→v2 cutover) is rotated — to a TIMESTAMPED
    `workspaces.json.bak.<UTC>` (never a reused slot) with a LOUD stderr notice —
    before a fresh v2 registry is started.

The identity/matching rules (§D): paths are canonicalized (symlinks resolved,
`~` expanded) and alias-expanded (macOS File-Provider `~/Dropbox` ↔
`~/Library/CloudStorage/Dropbox`); path lookup matches equal-or-nested and the
longest matching directory wins.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone

try:
    # POSIX advisory locking. On a platform WITHOUT fcntl (non-POSIX) the lock
    # file is still created but NOT actually held — the whole read-modify-write
    # then runs UNSERIALIZED there (advisory best-effort only, as docs/workspaces.md
    # notes). Concurrent writers are a POSIX-only guarantee.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REGISTRY_FILENAME = "workspaces.json"
TMP_FILENAME = "workspaces.json.tmp"
BAK_FILENAME = "workspaces.json.bak"
LOCK_FILENAME = ".lock"
DEFAULT_DIR = "~/.workspaces"

#: Highest on-disk `version` this writer understands. Writes emit exactly this;
#: a file whose version exceeds it is read-only (writing is refused).
MAX_SUPPORTED_VERSION = 2

#: Our own extension namespace under each workspace's `extensions{}` map. We
#: touch ONLY this slice; every other tool's slice round-trips untouched.
OUR_EXTENSION = "open-bridge"

#: Stable identity key stored INSIDE our own extension slice. An owning writer
#: (publish_workspace) mirrors a repo-local workspace under this id, so its
#: successive publishes converge on ONE row and a removal shrinks the mirror —
#: without hijacking a structural (path/remote) match on another tool's entry.
OUR_ID_KEY = "id"

#: Bookkeeping sub-key INSIDE our own extension slice, written ONLY on a row we
#: structurally ADOPTED from a peer tool (never on a row we minted). It records
#: the identity forms (canonical dirs + normalized remotes) THIS instance last
#: mirrored onto the adopted row — so a later id-match publish can MERGE the
#: peer's curated fields (name + peer-only dirs/remotes) instead of wholesale-
#: replacing them, while still SHRINKING the subset we ourselves contributed. Its
#: presence is the durable "this row was adopted" marker the id-match branch
#: reads (a foreign extension slice can NOT serve as that marker — a row we
#: minted can grow one when a peer tool bolts its own slice onto ours).
OUR_MIRROR_KEY = "_mirror"

#: macOS File-Provider path aliases (§D.2). The legacy spelling on the left is a
#: symlink to the canonical one on the right; both must match the same workspace.
#: The Dropbox rule is concrete; the same shape generalizes to OneDrive / Google
#: Drive (`Library/CloudStorage/<Provider>-<Account>`) when those are needed.
_ALIAS_SEGMENTS = [
    ("Dropbox", os.path.join("Library", "CloudStorage", "Dropbox")),
]

_WS_ID_RE = re.compile(r"^ws_(\d+)$")


class RegistryError(Exception):
    """User-facing, fail-closed error — printed without a traceback (exit 1)."""


class RegistryVersionError(RegistryError):
    """The on-disk file is newer than we understand — refuse to WRITE it (exit 4)."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """ISO-8601 UTC with a trailing Z (matches the schema's timestamp form)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonicalize(path: str) -> str:
    """Expand `~`, resolve symlinks, normalize — WITHOUT requiring existence.

    `os.path.realpath` resolves the symlink components that DO exist and
    normalizes the rest lexically, so a not-yet-created path still canonicalizes
    deterministically (no filesystem mutation, no touch of the queried path).
    """
    p = os.path.realpath(os.path.expanduser(path))
    p = p.rstrip(os.sep)
    return p or os.sep


def _alias_variants(canon: str) -> set[str]:
    """Every equivalent spelling of an already-canonicalized path (§D.2).

    Substitutes the known File-Provider alias segments in BOTH directions so a
    registry that stored only one spelling still matches a query in the other.
    """
    home = os.path.expanduser("~")
    forms = {canon}
    for legacy, modern in _ALIAS_SEGMENTS:
        legacy_root = os.path.join(home, legacy)
        modern_root = os.path.join(home, modern)
        for f in list(forms):
            if f == legacy_root or f.startswith(legacy_root + os.sep):
                forms.add(modern_root + f[len(legacy_root):])
            if f == modern_root or f.startswith(modern_root + os.sep):
                forms.add(legacy_root + f[len(modern_root):])
    return forms


def _path_forms(path: str) -> set[str]:
    """Canonicalize + alias-expand a raw path into its full match set."""
    return _alias_variants(_canonicalize(path))


def _normalize_remote(remote: str) -> str:
    """Reduce a git remote to a comparable `host/org/repo` identity.

    Folds the scp form (`user@host:path`) and the URL forms
    (`https://…`, `ssh://user@host/…`) onto the same shape, strips a trailing
    `.git` and slash, and lowercases — so the same project's remotes compare
    equal regardless of transport.
    """
    s = remote.strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    scp = re.match(r"^[^/@]+@([^/:]+):(.+)$", s)
    if scp:
        s = scp.group(1) + "/" + scp.group(2)
    else:
        s = re.sub(r"^[^/@]+@", "", s)  # drop a leading user@ on URL forms
    s = s.rstrip("/")
    s = re.sub(r"\.git$", "", s, flags=re.IGNORECASE)  # strip a `.git`/`.GIT` suffix
    return s.lower()


def _match_entries(ws: dict) -> list[str]:
    """Canonical directory paths of a workspace = union of path + aliases."""
    out: list[str] = []
    for d in ws.get("directories") or []:
        if not isinstance(d, dict):
            continue
        p = d.get("path")
        if isinstance(p, str) and p:
            out.append(_canonicalize(p))
        for a in d.get("aliases") or []:
            if isinstance(a, str) and a:
                out.append(_canonicalize(a))
    return out


def _build_directory(entry) -> dict:
    """Normalize a `directories[]` input (str or dict) into a schema entry.

    The primary `path` is stored canonical; every alternate spelling (provided
    aliases + File-Provider variants) lands in `aliases` so cheap string-prefix
    consumers match without canonicalizing (§C / §D.2).
    """
    if isinstance(entry, str):
        raw, aliases, label, added = entry, [], None, None
    elif isinstance(entry, dict):
        raw = entry.get("path")
        aliases = list(entry.get("aliases") or [])
        label = entry.get("label")
        added = entry.get("added_at")
    else:
        raise RegistryError("a directories[] entry must be a string or a mapping")
    if not isinstance(raw, str) or not raw:
        raise RegistryError("a directories[] entry needs a non-empty 'path'")

    canon = _canonicalize(raw)
    merged: list[str] = []
    for a in [*aliases, *sorted(_alias_variants(canon) - {canon})]:
        if not isinstance(a, str) or not a:
            continue
        ca = _canonicalize(a)
        if ca != canon and ca not in merged:
            merged.append(ca)

    out: dict = {"path": canon, "aliases": merged}
    if label:
        out["label"] = label
    out["added_at"] = added or _now_iso()
    return out


def _next_id(workspaces: list[dict]) -> str:
    """Next free `ws_NNNN` id (max existing + 1). Safe because we hold the lock."""
    mx = 0
    for ws in workspaces:
        wid = ws.get("id")
        if isinstance(wid, str):
            m = _WS_ID_RE.match(wid)
            if m:
                mx = max(mx, int(m.group(1)))
    return f"ws_{mx + 1:04d}"


def _coerce_version(version) -> int | None:
    """Coerce a registry `version` field to int, or None if it is not numeric.

    Accepts an int (kept as-is), a decimal string matching `^\\d+$` (`"2"` → 2),
    and an integral float (`2.0` → 2) — the JSON representations that all mean
    the same schema version. A bool, a non-integral float, a non-numeric string,
    or a missing/other type is NON-coercible (None); the caller then fails closed
    rather than guessing a version for it.
    """
    if isinstance(version, bool):
        return None  # bool is an int subclass, but true/false is not a version
    if isinstance(version, int):
        return version
    if isinstance(version, float):
        return int(version) if version.is_integer() else None
    if isinstance(version, str) and re.match(r"^\d+$", version):
        return int(version)
    return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class Registry:
    """A conformant reader/writer of one `workspaces.json` registry directory."""

    def __init__(self, directory: str | None = None):
        self.dir = os.path.abspath(
            os.path.expanduser(
                directory or os.environ.get("WORKSPACES_DIR") or DEFAULT_DIR
            )
        )
        self.path = os.path.join(self.dir, REGISTRY_FILENAME)
        self.tmp_path = os.path.join(self.dir, TMP_FILENAME)
        self.lock_path = os.path.join(self.dir, LOCK_FILENAME)

    # --- read side (lockless; atomic-replace guarantees a whole-file read) ----

    @staticmethod
    def _empty() -> dict:
        return {"version": MAX_SUPPORTED_VERSION, "workspaces": []}

    def _parse(self, raw: bytes) -> dict:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("registry root is not a JSON object")
        ws = data.get("workspaces")
        if ws is None:
            data["workspaces"] = []
        elif not isinstance(ws, list) or any(not isinstance(w, dict) for w in ws):
            raise ValueError("registry 'workspaces' is not a list of objects")
        return data

    def read_registry(self) -> dict:
        """Return the whole registry (a deep copy). Missing file → empty v2.

        Reading is allowed for ANY version (including one newer than us); the
        version ceiling is enforced only on WRITE. A present-but-corrupt file
        raises fail-closed (a write would refuse it too — see `_read_for_write`).
        """
        if not os.path.exists(self.path):
            return self._empty()
        try:
            with open(self.path, "rb") as fh:
                return self._parse(fh.read())
        except (ValueError, UnicodeDecodeError) as exc:
            raise RegistryError(
                f"registry {self.path} is unreadable ({exc}) — inspect or "
                f"remove it; refusing to guess.")

    def list_workspaces(self, include_archived: bool = True) -> list[dict]:
        rows = self.read_registry().get("workspaces") or []
        if include_archived:
            return rows
        return [w for w in rows if not w.get("archived")]

    def find_by_path(self, path: str) -> dict | None:
        """Longest-match workspace for `path` (equal or nested), else None (§D)."""
        qforms = _path_forms(path)
        best: dict | None = None
        best_len = -1
        for ws in self.read_registry().get("workspaces") or []:
            for entry in _match_entries(ws):
                for ef in _alias_variants(entry):
                    if any(qf == ef or qf.startswith(ef + os.sep) for qf in qforms):
                        if len(ef) > best_len:
                            best_len = len(ef)
                            best = ws
        return deepcopy(best) if best is not None else None

    # --- lock (POSIX flock; whole read-modify-write runs inside it) -----------

    class _Lock:
        def __init__(self, reg: "Registry"):
            self.reg = reg
            self.fd = -1

        def __enter__(self):
            os.makedirs(self.reg.dir, exist_ok=True)  # create the dir on first write
            self.fd = os.open(self.reg.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_EX)
            return self

        def __exit__(self, *_exc):
            try:
                if fcntl is not None:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                if self.fd >= 0:
                    os.close(self.fd)
                    self.fd = -1
            return False

    # --- write side (ONLY inside the lock) ------------------------------------

    def _rotate_to_bak(self, raw: bytes) -> str:
        """Preserve a legacy (v1) file's bytes in a TIMESTAMPED backup.

        The backup is `workspaces.json.bak.<UTC yyyymmddThhmmssZ>` — never a
        single reused slot, so a later v1→v2 rotation can NEVER clobber an
        earlier evacuation. If two rotations fall in the same UTC second, a
        numeric suffix keeps them distinct. Returns the backup path (for the
        loud stderr notice).
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = os.path.join(self.dir, f"{BAK_FILENAME}.{stamp}")
        dest = base
        n = 1
        while os.path.exists(dest):
            dest = f"{base}.{n}"
            n += 1
        self._atomic_write(dest, raw)
        return dest

    def _read_for_write(self) -> dict:
        """Read the base to modify while holding the lock — FAIL-CLOSED.

        A newer file is REFUSED (RegistryVersionError). An unparseable file or a
        missing/non-numeric `version` is REFUSED too (RegistryError) — the bytes
        are left exactly as found, never rotated, never guessed. ONLY a genuine
        older file (coerced `version <= 1`, the documented v1→v2 cutover) is
        rotated to a timestamped `.bak` (with a loud stderr notice) and a fresh
        v2 base returned.
        """
        if not os.path.exists(self.path):
            return self._empty()
        with open(self.path, "rb") as fh:
            raw = fh.read()
        try:
            data = self._parse(raw)
        except (ValueError, UnicodeDecodeError):
            raise RegistryError(
                f"registry {self.path} is unreadable — inspect or remove it; "
                f"refusing to guess (a write must not overwrite an unparseable "
                f"file).")
        version = _coerce_version(data.get("version"))
        if version is None:
            raise RegistryError(
                f"registry {self.path} has a missing or non-numeric 'version' "
                f"— inspect or remove it; refusing to guess.")
        if version > MAX_SUPPORTED_VERSION:
            raise RegistryVersionError(
                f"registry {self.path} is version {version}; this writer "
                f"understands at most {MAX_SUPPORTED_VERSION}. Refusing to write "
                f"(a newer tool's semantics must not be clobbered). Reading is "
                f"still allowed.")
        if version <= 1:
            dest = self._rotate_to_bak(raw)  # documented v1→v2 cutover only
            n = len(data.get("workspaces") or [])
            sys.stderr.write(
                f"workspace-registry: rotated legacy v{version} registry to "
                f"{dest} ({n} workspace row(s) evacuated); started a fresh v2 "
                f"registry.\n")
            return self._empty()
        return data

    def _atomic_write(self, dest: str, data: bytes) -> None:
        """Write `data` to `dest` atomically (temp in same dir + os.replace).

        For the registry itself the temp is the documented `workspaces.json.tmp`
        (safe under the lock — one writer at a time). The `finally` unlink means
        a failure before `os.replace` never leaves a stray `.tmp` behind.
        """
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if dest == self.path:
            tmp = self.tmp_path
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            close_via_fd = True
        else:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".wsreg-",
                                       suffix=".tmp")
            close_via_fd = True
        try:
            with os.fdopen(fd, "wb", closefd=close_via_fd) as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _write(self, data: dict) -> None:
        data["version"] = MAX_SUPPORTED_VERSION  # always emit our max
        body = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
        self._atomic_write(self.path, (body + "\n").encode("utf-8"))

    # --- identity resolution --------------------------------------------------

    @staticmethod
    def _identity_index(workspaces: list[dict], canon_dirs: list[str],
                        norm_remotes: set[str]) -> int | None:
        """Index of the workspace this identity belongs to, or None (§D de-dup).

        Matches on a shared normalized git remote OR a shared canonical directory
        (alias-aware, exact — never nested, so a parent/child stay distinct).
        """
        dir_forms: set[str] = set()
        for cd in canon_dirs:
            dir_forms |= _alias_variants(cd)
        for i, ws in enumerate(workspaces):
            ws_remotes = {
                _normalize_remote(r) for r in ws.get("git_remotes") or []
                if isinstance(r, str) and r
            }
            if norm_remotes & ws_remotes:
                return i
            ws_forms: set[str] = set()
            for e in _match_entries(ws):
                ws_forms |= _alias_variants(e)
            if dir_forms & ws_forms:
                return i
        return None

    @staticmethod
    def _adopt_candidates(workspaces: list[dict], canon_dirs: list[str],
                          norm_remotes: set[str]) -> list[int]:
        """Indices of rows a publish could structurally ADOPT (§C.3 rule 3).

        Same identity test as `_identity_index` — a shared normalized git remote
        OR a shared alias-aware canonical directory — but scanned over ALL rows
        and EXCLUDING any row that already carries our own `extensions`
        namespace (that is one of ours / another instance's mirror; never
        adopted). Returns EVERY match so the caller can tell exactly-one (adopt)
        from zero / ambiguous (mint).
        """
        dir_forms: set[str] = set()
        for cd in canon_dirs:
            dir_forms |= _alias_variants(cd)
        hits: list[int] = []
        for i, ws in enumerate(workspaces):
            exts = ws.get("extensions")
            if isinstance(exts, dict) and OUR_EXTENSION in exts:
                continue  # a row already ours / another instance's — never adopt
            ws_remotes = {
                _normalize_remote(r) for r in ws.get("git_remotes") or []
                if isinstance(r, str) and r
            }
            if norm_remotes & ws_remotes:
                hits.append(i)
                continue
            ws_forms: set[str] = set()
            for e in _match_entries(ws):
                ws_forms |= _alias_variants(e)
            if dir_forms & ws_forms:
                hits.append(i)
        return hits

    # --- public writer API ----------------------------------------------------

    def upsert_workspace(self, name: str, directories=None, git_remotes=None,
                         open_bridge_ext=None, short: str | None = None,
                         description: str | None = None,
                         color: str | None = None,
                         pinned: bool | None = None,
                         name_generated: bool | None = None) -> dict:
        """Create-or-update a workspace by IDENTITY, then park our config slice.

        `name` is the shared display name (callers that use `title` internally
        map it to `name` here). `directories` items are strings or
        `{path, aliases?, label?, added_at?}` mappings. `open_bridge_ext` is our
        opaque payload (e.g. `{"overlays": [...], "repos": [...]}`), stored ONLY
        under `extensions["open-bridge"]`. De-dups on a shared git remote or a
        shared canonical path instead of appending a duplicate row.
        """
        if not isinstance(name, str) or not name:
            raise RegistryError("upsert_workspace needs a non-empty name")

        new_dirs = [_build_directory(d) for d in (directories or [])]
        canon_dirs = [d["path"] for d in new_dirs]
        remotes = list(dict.fromkeys(  # de-dup, preserve order
            r for r in (git_remotes or []) if isinstance(r, str) and r))
        norm_remotes = {_normalize_remote(r) for r in remotes}

        with self._Lock(self):
            data = self._read_for_write()
            workspaces: list[dict] = data.setdefault("workspaces", [])
            now = _now_iso()
            idx = self._identity_index(workspaces, canon_dirs, norm_remotes)

            if idx is None:
                ws: dict = {
                    "id": _next_id(workspaces),
                    "name": name,
                    "description": description or "",
                    "name_generated": bool(name_generated),
                    "pinned": bool(pinned),
                    "archived": False,
                    "directories": new_dirs,
                    "git_remotes": remotes,
                    "resource_refs": [],
                    "recent_chat_session_ids": [],
                    "extensions": {},
                    "created_at": now,
                    "updated_at": now,
                }
                if short:
                    ws["short"] = short
                if color:
                    ws["color"] = color
                workspaces.append(ws)
            else:
                # Update in place — touch ONLY shared-identity fields. Merge (not
                # replace) directories + remotes so a field another tool added is
                # never dropped. Unknown per-workspace keys are left untouched.
                ws = workspaces[idx]
                ws["name"] = name
                if short is not None:
                    ws["short"] = short
                if description is not None:
                    ws["description"] = description
                if color is not None:
                    ws["color"] = color
                if pinned is not None:
                    ws["pinned"] = bool(pinned)
                if name_generated is not None:
                    ws["name_generated"] = bool(name_generated)
                self._merge_directories(ws, new_dirs)
                self._merge_remotes(ws, remotes)
                ws["updated_at"] = now

            if open_bridge_ext is not None:
                exts = ws.setdefault("extensions", {})
                if not isinstance(exts, dict):
                    raise RegistryError("workspace 'extensions' is not a mapping")
                exts[OUR_EXTENSION] = deepcopy(open_bridge_ext)

            self._write(data)
            return deepcopy(ws)

    @staticmethod
    def _merge_directories(ws: dict, new_dirs: list[dict]) -> None:
        existing = ws.setdefault("directories", [])
        if not isinstance(existing, list):
            existing = []
            ws["directories"] = existing
        # for each existing entry, the set of canonical forms it already covers
        forms_for: list[set[str]] = []
        for d in existing:
            fs: set[str] = set()
            if isinstance(d, dict):
                for e in _match_entries({"directories": [d]}):
                    fs |= _alias_variants(e)
            forms_for.append(fs)
        for nd in new_dirs:
            nd_forms = _alias_variants(nd["path"])
            hit = next((i for i, fs in enumerate(forms_for) if nd_forms & fs), None)
            if hit is None:
                existing.append(nd)
                forms_for.append(nd_forms | {_canonicalize(a) for a in nd["aliases"]})
            else:
                target = existing[hit]
                if isinstance(target, dict):
                    merged = list(target.get("aliases") or [])
                    for a in nd["aliases"]:
                        if a not in merged:
                            merged.append(a)
                    target["aliases"] = merged

    @staticmethod
    def _merge_remotes(ws: dict, remotes: list[str]) -> None:
        existing = ws.setdefault("git_remotes", [])
        if not isinstance(existing, list):
            existing = []
            ws["git_remotes"] = existing
        have = {_normalize_remote(r) for r in existing if isinstance(r, str)}
        for r in remotes:
            if _normalize_remote(r) not in have:
                existing.append(r)
                have.add(_normalize_remote(r))

    def archive_workspace(self, workspace_id: str) -> dict:
        """Soft-delete: set `archived: true` on the workspace with this id."""
        with self._Lock(self):
            data = self._read_for_write()
            workspaces: list[dict] = data.setdefault("workspaces", [])
            for ws in workspaces:
                if ws.get("id") == workspace_id:
                    ws["archived"] = True
                    ws["updated_at"] = _now_iso()
                    self._write(data)
                    return deepcopy(ws)
            raise RegistryError(f"no workspace with id '{workspace_id}' to archive")

    def publish_workspace(self, ref: str, name: str, directories=None,
                          git_remotes=None, open_bridge_ext=None) -> dict:
        """Mirror an OWNED workspace's identity into the shared registry.

        Resolution order (protocol §C.3 rule 3 conformance):

          1. our OWN prior mirror — the row whose
             `extensions["open-bridge"]["id"]` equals `ref`. A row we MINTED is
             REPLACEd (name, directories, git_remotes, our slice) so a removal on
             the source of record SHRINKS the mirror. A row we ADOPTED (carrying
             the `_mirror` marker) is instead MERGEd — the peer's curated name and
             its peer-only dirs/remotes survive, the name guard still applies, and
             only the subset WE previously mirrored (recorded in `_mirror`) shrinks
             — so the adopt guard is not undone by the very next publish.
          2. else a guarded STRUCTURAL ADOPT — among rows that do NOT already
             carry an `extensions["open-bridge"]` slice (those are ours / another
             instance's, never adopted), the ones sharing a normalized git remote
             OR a canonical directory with this workspace are candidates. EXACTLY
             ONE candidate is ADOPTED with MERGE semantics: directories + remotes
             are unioned onto the existing row, our slice is parked, the name is
             taken over only if the row had none or its name was auto-generated,
             `updated_at` bumps — and NOTHING else (foreign extension slices,
             `state`, `session_ns`, `resource_refs`, unknown keys) is touched.
          3. else (no id match, and zero or ≥2 structural candidates) a fresh row
             is minted.

        This de-dups our publishes against a peer tool's pre-existing row for the
        same project (convergence) without ever clobbering a second such row or a
        row that is already one of ours (instance isolation). Foreign extension
        slices, unknown top-level keys, and unknown per-workspace keys are
        preserved throughout.
        """
        if not isinstance(ref, str) or not ref:
            raise RegistryError("publish_workspace needs a non-empty ref")
        if not isinstance(name, str) or not name:
            raise RegistryError("publish_workspace needs a non-empty name")
        new_dirs = [_build_directory(d) for d in (directories or [])]
        remotes = list(dict.fromkeys(
            r for r in (git_remotes or []) if isinstance(r, str) and r))
        canon_dirs = [d["path"] for d in new_dirs]
        norm_remotes = {_normalize_remote(r) for r in remotes}
        ext_slice: dict = deepcopy(open_bridge_ext) if isinstance(open_bridge_ext, dict) else {}
        ext_slice[OUR_ID_KEY] = ref  # our id is authoritative, never overridden

        with self._Lock(self):
            data = self._read_for_write()
            workspaces: list[dict] = data.setdefault("workspaces", [])
            now = _now_iso()

            # (1) our own prior mirror, by id — REPLACE (allowing shrink).
            idx = None
            for i, ws in enumerate(workspaces):
                exts = ws.get("extensions")
                if isinstance(exts, dict):
                    slice_ = exts.get(OUR_EXTENSION)
                    if isinstance(slice_, dict) and slice_.get(OUR_ID_KEY) == ref:
                        idx = i
                        break
            if idx is not None:
                ws = workspaces[idx]
                exts = ws.setdefault("extensions", {})
                if not isinstance(exts, dict):
                    raise RegistryError("workspace 'extensions' is not a mapping")
                old_slice = exts.get(OUR_EXTENSION)
                old_mirror = (old_slice.get(OUR_MIRROR_KEY)
                              if isinstance(old_slice, dict) else None)
                if isinstance(old_mirror, dict):
                    # This row was ADOPTED from a peer tool (§C.3 rule 3): our id
                    # rides on a row whose name + some dirs/remotes belong to that
                    # peer. A wholesale REPLACE here would clobber the peer's
                    # curation one publish after the adopt guard parked us — so
                    # MERGE our identity in, keep the name guard, and SHRINK only
                    # the entries WE previously mirrored (recorded in `_mirror`).
                    new_dir_forms = {d["path"] for d in new_dirs}
                    drop_dirs = set(old_mirror.get("dirs") or []) - new_dir_forms
                    if drop_dirs:
                        ws["directories"] = [
                            d for d in (ws.get("directories") or [])
                            if not (isinstance(d, dict) and d.get("path") in drop_dirs)]
                    self._merge_directories(ws, new_dirs)  # MERGE, never replace
                    drop_remotes = set(old_mirror.get("remotes") or []) - norm_remotes
                    if drop_remotes:
                        ws["git_remotes"] = [
                            r for r in (ws.get("git_remotes") or [])
                            if not (isinstance(r, str)
                                    and _normalize_remote(r) in drop_remotes)]
                    self._merge_remotes(ws, remotes)
                    if not ws.get("name") or ws.get("name_generated"):
                        ws["name"] = name  # only overwrite empty/auto-generated
                    ext_slice[OUR_MIRROR_KEY] = {"dirs": sorted(new_dir_forms),
                                                 "remotes": sorted(norm_remotes)}
                else:
                    # A row WE minted (no adopt marker): full REPLACE of the
                    # mirrored identity fields so a source removal SHRINKS us.
                    ws["name"] = name
                    ws["directories"] = new_dirs
                    ws["git_remotes"] = remotes
                exts[OUR_EXTENSION] = ext_slice
                ws["updated_at"] = now
                self._write(data)
                return deepcopy(ws)

            # (2) no id match → guarded structural adopt of EXACTLY one row.
            candidates = self._adopt_candidates(workspaces, canon_dirs, norm_remotes)
            if len(candidates) == 1:
                ws = workspaces[candidates[0]]
                self._merge_directories(ws, new_dirs)  # MERGE, never replace
                self._merge_remotes(ws, remotes)
                exts = ws.setdefault("extensions", {})
                if not isinstance(exts, dict):
                    raise RegistryError("workspace 'extensions' is not a mapping")
                # Record which identity forms WE contributed onto this peer row so a
                # LATER id-match publish MERGEs (never wholesale-replaces) the peer's
                # fields and shrinks only our own subset. This is the adopt marker.
                ext_slice[OUR_MIRROR_KEY] = {"dirs": sorted(set(canon_dirs)),
                                             "remotes": sorted(norm_remotes)}
                exts[OUR_EXTENSION] = ext_slice
                if not ws.get("name") or ws.get("name_generated"):
                    ws["name"] = name  # only overwrite an empty/auto-generated name
                ws["updated_at"] = now
                self._write(data)
                return deepcopy(ws)

            # (3) zero or ≥2 candidates → mint a fresh mirror row.
            ws = {
                "id": _next_id(workspaces),
                "name": name,
                "description": "",
                "name_generated": False,
                "pinned": False,
                "archived": False,
                "directories": new_dirs,
                "git_remotes": remotes,
                "resource_refs": [],
                "recent_chat_session_ids": [],
                "extensions": {OUR_EXTENSION: ext_slice},
                "created_at": now,
                "updated_at": now,
            }
            workspaces.append(ws)
            self._write(data)
            return deepcopy(ws)


# ---------------------------------------------------------------------------
# CLI (thin — the library API above is the real surface)
# ---------------------------------------------------------------------------

def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_path(reg: Registry, _args) -> int:
    print(reg.dir)
    return 0


def cmd_read(reg: Registry, _args) -> int:
    _print_json(reg.read_registry())
    return 0


def cmd_list(reg: Registry, args) -> int:
    rows = reg.list_workspaces(include_archived=args.all)
    if not rows:
        print("No workspaces registered.")
        return 0
    for ws in rows:
        flag = " [archived]" if ws.get("archived") else ""
        dirs = ", ".join(d.get("path", "") for d in ws.get("directories") or []
                         if isinstance(d, dict))
        print(f"{ws.get('id', '?'):<10} {ws.get('name', ''):<24} {dirs}{flag}")
    return 0


def cmd_find_path(reg: Registry, args) -> int:
    ws = reg.find_by_path(args.path)
    if ws is None:
        print("no matching workspace")
        return 3
    print(f"{ws.get('id', '?')}\t{ws.get('name', '')}")
    return 0


def cmd_upsert(reg: Registry, args) -> int:
    ext = None
    if args.overlay or args.repo:
        ext = {"overlays": list(args.overlay), "repos": list(args.repo)}
    ws = reg.upsert_workspace(
        args.name,
        directories=list(args.dir),
        git_remotes=list(args.git_remote),
        open_bridge_ext=ext,
        short=args.short,
        description=args.description,
        color=args.color,
        pinned=args.pinned,
    )
    print(f"upserted {ws.get('id')} ({ws.get('name')})")
    return 0


def cmd_archive(reg: Registry, args) -> int:
    ws = reg.archive_workspace(args.id)
    print(f"archived {ws.get('id')} ({ws.get('name')})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="workspace-registry",
        description="Standalone conformant reader/writer of the tool-neutral "
                    "workspace identity registry ($WORKSPACES_DIR/workspaces.json).")
    p.add_argument("--registry-dir", dest="registry_dir",
                   help="registry dir (default: $WORKSPACES_DIR or ~/.workspaces)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("path", help="print the resolved registry directory").set_defaults(func=cmd_path)
    sub.add_parser("read", help="print the whole registry as JSON").set_defaults(func=cmd_read)

    li = sub.add_parser("list", help="list registered workspaces")
    li.add_argument("--all", action="store_true", help="include archived")
    li.set_defaults(func=cmd_list)

    fp = sub.add_parser("find-path", help="longest-match workspace for a path")
    fp.add_argument("path")
    fp.set_defaults(func=cmd_find_path)

    up = sub.add_parser("upsert", help="create-or-update a workspace by identity")
    up.add_argument("name")
    up.add_argument("--dir", dest="dir", action="append", default=[],
                    help="a workspace directory (repeatable)")
    up.add_argument("--git-remote", dest="git_remote", action="append", default=[],
                    help="a git remote identity (repeatable)")
    up.add_argument("--overlay", action="append", default=[],
                    help="an open-bridge overlay name (repeatable)")
    up.add_argument("--repo", action="append", default=[],
                    help="an open-bridge member repo (repeatable)")
    up.add_argument("--short")
    up.add_argument("--description")
    up.add_argument("--color")
    up.add_argument("--pinned", action="store_true", default=None)
    up.set_defaults(func=cmd_upsert)

    ar = sub.add_parser("archive", help="soft-delete (archive) a workspace by id")
    ar.add_argument("id")
    ar.set_defaults(func=cmd_archive)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    reg = Registry(args.registry_dir)
    try:
        return args.func(reg, args)
    except RegistryVersionError as exc:
        sys.stderr.write(f"workspace-registry: {exc}\n")
        return 4
    except RegistryError as exc:
        sys.stderr.write(f"workspace-registry: {exc}\n")
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        sys.stderr.write("\nworkspace-registry: interrupted\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
