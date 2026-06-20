#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Permission-gated system scan for the Bridge onboarding wizard.

Phase B of /bridge-onboard. Collects evidence about what the user already
has installed and structured, so Phase C can propose specific features
instead of asking abstract questions.

Authoritative spec: skills/bridge-onboard/references/system-discovery.md.

Design principles:
  - Discover, don't interrogate — look at apps, configs, directories
  - Permission-gated — only scan what the user opted into via --permissions
  - Non-fatal — each source can fail independently with structured error
  - Stdlib only — Python 3.11+, no PyYAML, no requests
  - Cross-platform — macOS sources gracefully skip on Linux

Usage:
  scripts/system-discovery.py
  scripts/system-discovery.py --permissions git_config,os_and_apps
  scripts/system-discovery.py --projects-root ~/Code --output -
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Source registry — name → (default_on, macos_only).
SOURCES: dict[str, tuple[bool, bool]] = {
    "git_config":          (True,  False),
    "developer_dir":       (True,  False),
    "os_and_apps":         (True,  False),  # apps subtree is macOS-only; OS info is universal
    "homebrew_packages":   (True,  False),
    "tailscale_devices":   (False, False),
    "documents_structure": (False, False),
    "mail_accounts":       (False, True),
    "moneymoney_accounts": (False, True),
    "calendar_list":       (False, True),
    "ssh_known_hosts":     (False, False),
}

DEFAULT_PERMISSIONS = [name for name, (on, _) in SOURCES.items() if on]
IS_MACOS = platform.system() == "Darwin"


# --- Helpers -----------------------------------------------------------------

def _run(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with safe defaults; never raises on exit-code."""
    return subprocess.run(
        cmd,
        timeout=timeout,
        capture_output=True,
        text=True,
        check=False,
    )


def _osascript(script: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    """Run an AppleScript one-liner with a generous timeout."""
    return _run(["osascript", "-e", script], timeout=timeout)


def _macos_only(fn):
    """Decorator: short-circuit non-macOS callers with structured error."""
    def wrapper(*args, **kwargs):
        if not IS_MACOS:
            return {"error": "not_macos"}
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _emit_progress(symbol: str, source: str, detail: str = "") -> None:
    """Write a one-line progress marker to stderr."""
    suffix = f" ({detail})" if detail else ""
    print(f"{symbol} {source}{suffix}", file=sys.stderr, flush=True)


def _parse_projects_root_from_config(config_path: Path) -> str | None:
    """Minimal YAML grep: pull `projects_root:` value without PyYAML."""
    if not config_path.is_file():
        return None
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return None
    in_identity = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Detect top-level `identity:` block — entered when line starts unindented.
        if re.match(r"^identity:\s*$", line):
            in_identity = True
            continue
        # Leaving identity block when a new top-level key appears.
        if in_identity and re.match(r"^[A-Za-z_][\w-]*:", line):
            in_identity = False
        if in_identity:
            m = re.match(r"^\s+projects_root:\s*(.+?)\s*(?:#.*)?$", line)
            if m:
                value = m.group(1).strip().strip('"').strip("'")
                return value
    return None


def _resolve_path(p: str) -> Path:
    """Expand ~ and env-vars, return Path."""
    return Path(os.path.expandvars(os.path.expanduser(p)))


# --- Scan functions ----------------------------------------------------------

def scan_git_config() -> dict:
    """Read user.name and user.email from global git config."""
    if not shutil.which("git"):
        return {"error": "tool_missing"}
    try:
        name = _run(["git", "config", "--global", "user.name"]).stdout.strip()
        email = _run(["git", "config", "--global", "user.email"]).stdout.strip()
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    if not name and not email:
        return {"error": "not_configured"}
    return {"name": name or None, "email": email or None}


def scan_developer_dir(projects_root: Path) -> dict:
    """List top-level orgs and git repos under projects_root (depth 2)."""
    if not projects_root.is_dir():
        return {"error": f"not_a_directory: {projects_root}"}
    orgs: list[str] = []
    try:
        for entry in sorted(projects_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                orgs.append(entry.name)
    except PermissionError:
        return {"error": "permission_denied"}
    except OSError as exc:
        return {"error": str(exc)}

    repos: list[dict] = []
    for org in orgs:
        org_dir = projects_root / org
        try:
            for child in sorted(org_dir.iterdir()):
                if not child.is_dir():
                    continue
                git_dir = child / ".git"
                if git_dir.exists():
                    origin = _read_git_origin(child)
                    repos.append({
                        "path": f"{org}/{child.name}",
                        "origin": origin,
                    })
                if len(repos) >= 50:
                    break
        except (PermissionError, OSError):
            continue
        if len(repos) >= 50:
            break

    return {
        "root": str(projects_root),
        "repo_count": len(repos),
        "orgs": orgs,
        "repos": repos,
    }


def _read_git_origin(repo_dir: Path) -> str | None:
    """Extract origin URL from a repo's git config without invoking git."""
    config = repo_dir / ".git" / "config"
    if not config.is_file():
        return None
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_origin = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped.lower() == '[remote "origin"]'
            continue
        if in_origin and stripped.lower().startswith("url"):
            _, _, url = stripped.partition("=")
            url = url.strip()
            # Normalise git@host:org/repo.git → host/org/repo
            m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
            if m:
                return f"{m.group(1)}/{m.group(2)}"
            m = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?/?$", url)
            if m:
                return f"{m.group(1)}/{m.group(2)}"
            return url
    return None


def scan_os_and_apps() -> dict:
    """Collect uname info plus /Applications listing (macOS) or dpkg (Linux)."""
    os_info = {
        "platform": platform.system().lower(),
        "arch": platform.machine(),
        "release": platform.release(),
    }
    apps: list[str] | dict = []
    if IS_MACOS:
        apps_dir = Path("/Applications")
        if apps_dir.is_dir():
            try:
                apps = sorted(
                    e.name for e in apps_dir.iterdir()
                    if e.name.endswith(".app") and not e.name.startswith(".")
                )
            except (PermissionError, OSError) as exc:
                apps = {"error": str(exc)}
        else:
            apps = {"error": "not_found"}
    else:
        # Linux: dpkg if available, else skip apps subtree gracefully.
        if shutil.which("dpkg"):
            try:
                result = _run(["dpkg", "--get-selections"], timeout=10.0)
                apps = sorted({
                    line.split()[0]
                    for line in result.stdout.splitlines()
                    if line.strip() and not line.startswith("#")
                })[:200]
            except subprocess.TimeoutExpired:
                apps = {"error": "timeout"}
        else:
            apps = {"error": "not_macos"}
    return {"os": os_info, "apps": apps}


def scan_homebrew_packages() -> dict:
    """List Homebrew formulae and casks (if brew is installed)."""
    if not shutil.which("brew"):
        return {"error": "tool_missing"}
    try:
        formula_p = _run(["brew", "list", "--formula"], timeout=15.0)
        cask_p = _run(["brew", "list", "--cask"], timeout=15.0)
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    formula = [f for f in formula_p.stdout.split() if f]
    cask = [c for c in cask_p.stdout.split() if c]
    return {"formula": formula, "cask": cask}


def scan_tailscale_devices() -> dict:
    """List own Tailscale devices via `tailscale status --json` (devices only)."""
    if not shutil.which("tailscale"):
        return {"error": "tool_missing"}
    try:
        result = _run(["tailscale", "status", "--json"], timeout=5.0)
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    if result.returncode != 0:
        msg = (result.stderr or "tailscale_error").strip().splitlines()[0]
        if "not running" in msg.lower() or "logged out" in msg.lower():
            return {"error": "not_running"}
        return {"error": msg[:120]}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "invalid_json"}
    self_name = (data.get("Self") or {}).get("HostName")
    devices = [self_name] if self_name else []
    for peer in (data.get("Peer") or {}).values():
        host = peer.get("HostName")
        if host:
            devices.append(host)
    return {"self": self_name, "devices": sorted(set(devices))}


def scan_documents_structure() -> dict:
    """List top-level folders under detected docs root (Documents/OneDrive/PARA/iCloud)."""
    home = Path.home()
    candidates: list[Path] = []
    # ~/Documents
    docs = home / "Documents"
    if docs.is_dir():
        candidates.append(docs)
    # Glob-like patterns at $HOME level: OneDrive*, PARA*, iCloud*
    try:
        for entry in home.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith(("OneDrive", "PARA", "iCloud")):
                candidates.append(entry)
    except (PermissionError, OSError):
        pass

    if not candidates:
        return {"error": "no_docs_root"}

    roots: list[dict] = []
    for root in candidates:
        try:
            folders = sorted(
                e.name for e in root.iterdir()
                if e.is_dir() and not e.name.startswith(".")
            )
        except (PermissionError, OSError) as exc:
            roots.append({"path": str(root), "error": str(exc)})
            continue
        roots.append({"path": str(root), "folders": folders})
    return {"roots": roots}


@_macos_only
def scan_mail_accounts() -> dict:
    """List Apple Mail account names (and Outlook profile accounts if present)."""
    result = _osascript('tell application "Mail" to get name of every account')
    accounts: list[str] = []
    error: str | None = None
    if result.returncode == 0:
        accounts = [a.strip() for a in result.stdout.strip().split(",") if a.strip()]
    else:
        stderr_lower = result.stderr.lower()
        if "not authorized" in stderr_lower or "1743" in stderr_lower:
            error = "permission_denied"
        elif "(-600)" in stderr_lower or "isn't running" in stderr_lower:
            error = "app_not_running"
        else:
            error = (result.stderr or "osascript_error").strip().splitlines()[0][:120]

    # Optional Outlook plist (display names only, no addresses)
    outlook: list[str] = []
    outlook_plist = Path.home() / (
        "Library/Group Containers/UBF8T346G9.Office/Outlook/"
        "Outlook 15 Profiles/Main Profile/Accounts.plist"
    )
    if outlook_plist.is_file() and shutil.which("plutil"):
        try:
            conv = _run(["plutil", "-convert", "xml1", "-o", "-", str(outlook_plist)], timeout=5.0)
            if conv.returncode == 0:
                # Pull <string>…</string> values under any AccountName-ish key.
                names = re.findall(r"<key>AccountName</key>\s*<string>([^<]+)</string>", conv.stdout)
                outlook = [n.strip() for n in names if n.strip()]
        except subprocess.TimeoutExpired:
            pass

    if error and not accounts and not outlook:
        return {"error": error}
    payload: dict = {"apple_mail": accounts}
    if outlook:
        payload["outlook"] = outlook
    if error:
        payload["apple_mail_error"] = error
    return payload


@_macos_only
def scan_moneymoney_accounts() -> dict:
    """List MoneyMoney account names via AppleScript (no transactions)."""
    if not Path("/Applications/MoneyMoney.app").exists():
        return {"error": "app_not_installed"}
    result = _osascript('tell application "MoneyMoney" to get name of every account')
    if result.returncode != 0:
        stderr_lower = result.stderr.lower()
        if "not authorized" in stderr_lower or "1743" in stderr_lower:
            return {"error": "permission_denied"}
        if "(-600)" in stderr_lower or "isn't running" in stderr_lower:
            return {"error": "app_not_running"}
        return {"error": (result.stderr or "osascript_error").strip().splitlines()[0][:120]}
    accounts = [a.strip() for a in result.stdout.strip().split(",") if a.strip()]
    return {"accounts": accounts}


@_macos_only
def scan_calendar_list() -> dict:
    """List Apple Calendar calendar names via AppleScript."""
    result = _osascript('tell application "Calendar" to get name of every calendar')
    if result.returncode != 0:
        stderr_lower = result.stderr.lower()
        if "not authorized" in stderr_lower or "1743" in stderr_lower:
            return {"error": "permission_denied"}
        if "(-600)" in stderr_lower or "isn't running" in stderr_lower:
            return {"error": "app_not_running"}
        return {"error": (result.stderr or "osascript_error").strip().splitlines()[0][:120]}
    cals = [c.strip() for c in result.stdout.strip().split(",") if c.strip()]
    return {"calendars": cals}


def scan_ssh_known_hosts() -> dict:
    """Extract unique hostnames from ~/.ssh/known_hosts (max 30)."""
    path = Path.home() / ".ssh" / "known_hosts"
    if not path.is_file():
        return {"error": "no_known_hosts"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (PermissionError, OSError) as exc:
        return {"error": str(exc)}
    hosts: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            # `|` prefix = hashed (HashKnownHosts) — opaque, skip
            continue
        first = line.split(" ", 1)[0]
        # Strip port suffix like [host]:2222
        first = first.strip("[]")
        if "," in first:
            first = first.split(",", 1)[0]
        if ":" in first and not first.startswith("["):
            first = first.split(":", 1)[0]
        if first:
            hosts.add(first)
    return {"hosts": sorted(hosts)[:30]}


# --- Orchestration -----------------------------------------------------------

SCAN_DISPATCH = {
    "git_config":          ("git",           lambda p: scan_git_config()),
    "developer_dir":       ("developer",     lambda p: scan_developer_dir(p["projects_root"])),
    "os_and_apps":         (None,            lambda p: scan_os_and_apps()),
    "homebrew_packages":   ("homebrew",      lambda p: scan_homebrew_packages()),
    "tailscale_devices":   ("tailscale",     lambda p: scan_tailscale_devices()),
    "documents_structure": ("documents",     lambda p: scan_documents_structure()),
    "mail_accounts":       ("mail",          lambda p: scan_mail_accounts()),
    "moneymoney_accounts": ("moneymoney",    lambda p: scan_moneymoney_accounts()),
    "calendar_list":       ("calendar",      lambda p: scan_calendar_list()),
    "ssh_known_hosts":     ("ssh",           lambda p: scan_ssh_known_hosts()),
}


def _summarise(source: str, result) -> str:
    """Generate a short human-readable detail string for progress lines."""
    if isinstance(result, dict) and "error" in result and len(result) == 1:
        return result["error"]
    if isinstance(result, dict) and result.get("error") and source != "os_and_apps":
        return result["error"]
    if source == "git_config":
        return result.get("name") or result.get("email") or "ok"
    if source == "developer_dir":
        return f"{result.get('repo_count', 0)} repos"
    if source == "os_and_apps":
        apps = result.get("apps")
        count = len(apps) if isinstance(apps, list) else 0
        return f"{result['os']['platform']}, {count} apps"
    if source == "homebrew_packages":
        return f"{len(result.get('formula', []))} formula, {len(result.get('cask', []))} cask"
    if source == "tailscale_devices":
        return f"{len(result.get('devices', []))} devices"
    if source == "documents_structure":
        return f"{len(result.get('roots', []))} roots"
    if source == "mail_accounts":
        return f"{len(result.get('apple_mail', []))} accounts"
    if source == "moneymoney_accounts":
        return f"{len(result.get('accounts', []))} accounts"
    if source == "calendar_list":
        return f"{len(result.get('calendars', []))} calendars"
    if source == "ssh_known_hosts":
        return f"{len(result.get('hosts', []))} hosts"
    return "ok"


def _is_error_only(result) -> bool:
    return isinstance(result, dict) and set(result.keys()) == {"error"}


def run_scan(permissions: list[str], projects_root: Path) -> dict:
    """Execute the requested scan sources sequentially and assemble evidence."""
    evidence: dict = {}
    ctx = {"projects_root": projects_root}

    for source in permissions:
        if source not in SCAN_DISPATCH:
            _emit_progress("⚠", source, "unknown_source")
            continue
        evidence_key, fn = SCAN_DISPATCH[source]
        try:
            result = fn(ctx)
        except Exception as exc:  # last-resort guard — spec says never raise
            result = {"error": f"unhandled: {exc.__class__.__name__}: {exc}"[:200]}

        symbol = "⚠" if _is_error_only(result) else "✓"
        _emit_progress(symbol, source, _summarise(source, result))

        # os_and_apps is special: writes two top-level subtrees (`os`, `apps`).
        if source == "os_and_apps":
            evidence["os"] = result.get("os", {})
            evidence["apps"] = result.get("apps", [])
            continue

        if evidence_key:
            evidence[evidence_key] = result

    return {
        "scan_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "permissions_granted": permissions,
        "evidence": evidence,
    }


# --- CLI ---------------------------------------------------------------------

def _parse_permissions(arg: str | None) -> list[str]:
    if arg is None:
        return list(DEFAULT_PERMISSIONS)
    items = [p.strip() for p in arg.split(",") if p.strip()]
    unknown = [p for p in items if p not in SOURCES]
    if unknown:
        print(f"error: unknown permission(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"valid: {', '.join(SOURCES)}", file=sys.stderr)
        sys.exit(2)
    return items


def _default_projects_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    config = here / "bridge-config.yaml"
    parsed = _parse_projects_root_from_config(config)
    if parsed:
        return _resolve_path(parsed)
    return Path.home() / "Developer"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Permission-gated system scan for the Bridge onboarding wizard.",
    )
    parser.add_argument(
        "--permissions",
        help=(
            "Comma-separated source list. Default: all default-on sources "
            f"({','.join(DEFAULT_PERMISSIONS)})."
        ),
    )
    parser.add_argument(
        "--projects-root",
        help="Path to scan for developer_dir (default: bridge-config.yaml or ~/Developer).",
    )
    parser.add_argument(
        "--output",
        default="work/onboarding-scan.json",
        help="Output path. Use '-' for stdout. Default: work/onboarding-scan.json.",
    )
    args = parser.parse_args(argv)

    permissions = _parse_permissions(args.permissions)
    projects_root = (
        _resolve_path(args.projects_root) if args.projects_root else _default_projects_root()
    )

    report = run_scan(permissions, projects_root)
    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False)

    if args.output == "-":
        print(payload)
    else:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
