#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Measure the always-on context a session loads, and hold it to a declared cap.

Every session loads a fixed body of text before the first answer: the entry
file Claude Code loads (AGENTS.md, or CLAUDE.md while a fork still has one)
with its `@`-imports, the standing orders carrying `scope: always`, and the
Phase 1 reads. Nothing measured it, so it only ever grew, and it grew
where nobody looks: roughly half arrives through tool reads rather than
imports, so it never appears in a client's context listing at all.

One file in this repo has never sprawled, `identity/agent/SOUL.md`, and the
only thing that distinguishes it is a declared cap that a validator enforces.
This script generalises that cap to the whole always-on surface.

    python3 scripts/measure-context.py                 # report + gate
    python3 scripts/measure-context.py --method api    # exact counts
    python3 scripts/measure-context.py --out FILE      # also write the report

Exit code 0 when every item is within policy, 1 otherwise.

WHAT GATES AND WHAT ONLY INFORMS. The gate is on **bytes**, which are exact,
offline, and identical on every machine. Tokens are reported beside them, and
carry the method that produced them: `api` is exact
(`messages.count_tokens`, model-specific), `bytes` is an estimate from a
declared calibration. An estimate never fails a build, and never wears the
label of an exact count. A budget figure that does not say what counted it is
not a measurement.

The full contract, including every state and why it exists, lives in
`scripts/tests/test_measure_context.py`, which is the spec for this file.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.standing_orders import (  # noqa: E402  (path setup must precede this import)
    collect_orders,
    eager_paths,
)
from lib.context_index import registry_files, render_card  # noqa: E402

CORE_BUDGET = "context-budget.yaml"
USER_BUDGET = "context-budget.user.yaml"
# The entry chain mirrors Claude Code's DEFAULT option for AGENTS.md support
# (`instructionFiles: claude-md-or-agents-md`, set in `/config`, not in a
# settings file, so a project can neither pin nor detect it). Under it a
# CLAUDE.md beside AGENTS.md is the only file loaded, and AGENTS.md reaches the
# session only through an import. Probed with 2.1.314: a root CLAUDE.local.md
# and a .claude/CLAUDE.md shadow AGENTS.md the same way, and each present one
# loads, in this order. Non-default options are not modelled.
AGENTS_ENTRY = "AGENTS.md"
SHADOW_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")
ENTRY_CANDIDATES = SHADOW_FILES + (AGENTS_ENTRY,)
MIGRATION_SCRIPT = "scripts/migrate-entry-file.py"
ORDERS_DIR = Path("protocols") / "standing-orders"

# Only a line that STARTS with `@` is an import. An address in prose is not,
# and neither is a line inside a ``` or ~~~ fence (an example of an import).
# The fence rule is migrate-entry-file.py's: either marker opens one, and only
# the same marker closes it.
IMPORT_RE = re.compile(r"^@(\S+)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Some always-on payload is not a file. Phase 1 loads the standing-order index
# and a slice of bridge-config.yaml, both computed at the moment of use so they
# can never go stale. A budget item keyed `cmd:<command>` is measured by running
# it and measuring stdout, which is what actually loads.
CMD_PREFIX = "cmd:"
# A budget file is reviewed, but it is still config, and config that can run
# anything is a different kind of file than the one anybody reviewed it as.
CMD_ALLOWED_PREFIX = "python3 scripts/"

LISTING_PREFIX = "listing:"

# The third residency channel, and the only DERIVED one: the harness injects
# `name` + `description` of every skill and every sub-agent into every session
# AND into every sub-agent dispatch, without any of it being a file the budget
# could point at. Measured on a live instance: 111 skills, 73 400 bytes, larger
# than every `@`-import in that tree combined, and declared nowhere.
#
# It is not dead weight. On that same instance 33 config-family paths were named
# ONLY in a skill description, and one family was reachable exclusively through
# one. So this belongs in `always_on_parts` as well as in the table: a surface
# that omits the listing makes the reachability contract report a family
# unreachable that a session can in fact find.
LISTINGS = {
    "skills": ("skills", "*/SKILL.md"),
    "agents": (".claude/agents", "*.md"),
}

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.S)

HARNESS_PREFIX = "harness:"
# The fourth channel: what the HARNESS loads on its own, named in no file this
# tree controls. Claude Code reads the auto-memory index (`MEMORY.md` in the
# configured memory directory) into every main session before the first
# answer. Measured on a live instance at 20 227 bytes, counted nowhere. The
# directory is resolved by `scripts/memory-location.py`, the one place that
# knows the harness's precedence, so the meter cannot drift from it.
HARNESS_MEMORY_INDEX = HARNESS_PREFIX + "memory-index"
MEMORY_LOCATION = Path(__file__).resolve().parent / "memory-location.py"

DEFAULT_BYTES_PER_TOKEN = 2.4
DEFAULT_MODEL = "claude-opus-5"

# The states that fail the build. `uncapped` is deliberately absent: a newly
# declared item must be addable in one line without breaking anyone's CI.
#
# `contradiction` is a file that declares a `card:` AND is `@`-imported. The
# import loads the whole file every session; the card claims only the card
# does. Measuring the card there reported green while the session paid for the
# full text (on a live instance, 3 829 bytes reported for a 24 369 byte
# import). The pair is a false statement about what loads, so it fails at any
# size, and the full text is what gets counted.
#
# `error` is a harness item whose lookup raised (a renamed or broken
# `memory-location.py`, say). Reported as "no index", that read as green; it is
# a meter that cannot see its subject, so it fails.
#
# `shadowed` is AGENTS.md while a root CLAUDE.md (or CLAUDE.local.md, or
# .claude/CLAUDE.md) exists and imports it from none of them. Claude Code then
# loads only those files and none of the manual; `/init` writes exactly such a
# file. Measuring AGENTS.md anyway would report a manual no session reads.
FAILING = {"over", "undeclared", "missing", "contradiction", "error", "shadowed"}

# The failing states that are not about SIZE, so `enforce: advisory` cannot
# excuse them: advisory covers a number driven by ongoing work, and these are
# a false claim about what loads, a lookup that broke, and a manual that does
# not load at all.
STRUCTURAL = {"contradiction", "error", "shadowed"}

# An item may declare `enforce: advisory` to be measured and reported without
# failing the build. It exists for the one class the cap cannot honestly govern:
# an item whose size is driven by ONGOING WORK rather than by a file somebody
# edited. The work log is the case that produced this. It grows all week, resets
# on `/archive`, and a red build says "you worked too much this week", which is
# not a defect report. Everything a human authors and reviews stays hard: a
# CORE always-on file over its cap IS a defect, and staying red is the point.
#
# Advisory is a claim about the ITEM, not a way to quiet a number. An item that
# went advisory to escape a real cap has moved the problem, not solved it, so
# the report still prints the overrun and names it.
ADVISORY_NOTE = "advisory (measured, does not fail the build)"


# ------------------------------------------------------------- the budget --

def load_budget(repo_root: Path) -> dict:
    """Read the CORE budget, then overlay the per-instance one when present.

    The overlay replaces an item wholesale by key. It is not a deep merge,
    because a half-overridden cap is worse than either cap on its own.
    """
    core = Path(repo_root) / CORE_BUDGET
    if not core.is_file():
        sys.exit(
            f"error: {CORE_BUDGET} not found in {repo_root}.\n"
            "       A meter with no policy enforces nothing and would report\n"
            "       green forever, so this is refused rather than skipped."
        )

    budget = yaml.safe_load(core.read_text(encoding="utf-8")) or {}
    budget.setdefault("items", {})
    budget.setdefault("calibration", {})
    budget["calibration"].setdefault("bytes_per_token", DEFAULT_BYTES_PER_TOKEN)
    budget["calibration"].setdefault("model", DEFAULT_MODEL)

    user = Path(repo_root) / USER_BUDGET
    if user.is_file():
        overlay = yaml.safe_load(user.read_text(encoding="utf-8")) or {}
        for key, value in (overlay.get("items") or {}).items():
            budget["items"][key] = value or {}
        budget["calibration"].update(overlay.get("calibration") or {})

    budget["items"] = {k: (v or {}) for k, v in (budget["items"] or {}).items()}
    return budget


# ---------------------------------------------------------- what is loaded --

def resolve_entries(repo_root: Path) -> list[str]:
    """The entry files Claude Code loads at the repo root, in load order.

    Every shadow file present, when there is one; AGENTS.md otherwise; nothing
    on a tree that has neither.

    A shadow file that IS AGENTS.md (a symlink, one manual for both tools)
    stands for AGENTS.md in the chain, so the manual is counted once.
    """
    root = Path(repo_root)
    shadows = []
    for rel in SHADOW_FILES:
        if not (root / rel).is_file():
            continue
        name = AGENTS_ENTRY if is_agents_alias(root, rel) else rel
        if name not in shadows:
            shadows.append(name)
    if shadows and shadows != [AGENTS_ENTRY]:
        return shadows
    return [AGENTS_ENTRY] if (root / AGENTS_ENTRY).is_file() else []


def is_agents_alias(repo_root: Path, rel: str) -> bool:
    """`rel` is the same file as AGENTS.md (a symlink or a hard link)."""
    root = Path(repo_root)
    if rel == AGENTS_ENTRY:
        return False
    try:
        return (root / rel).is_file() and (root / rel).samefile(root / AGENTS_ENTRY)
    except OSError:
        return False


def resolve_entry(repo_root: Path) -> str | None:
    """The first entry file Claude Code loads, or None."""
    entries = resolve_entries(repo_root)
    return entries[0] if entries else None


def _import_key(importer: str, target: str) -> str | None:
    """Repo-relative key of `target` as named in `importer`, or None.

    File-relative, as Claude Code resolves it. A root-level importer resolves
    exactly as before, so existing budget keys stay valid. `~/` and absolute
    targets live outside the tree, and so does anything that climbs out of it.
    """
    if target.startswith(("~", "/")):
        return None
    key = os.path.normpath(os.path.join(os.path.dirname(importer), target))
    key = key.replace(os.sep, "/")
    if key == ".." or key.startswith("../"):
        return None
    return key


def discover_imports(
    repo_root: Path, entry: str | None = None, max_depth: int = 4
) -> list[str]:
    """The `@`-imports actually loaded, followed recursively, first-seen order.

    With no `entry`, the walk starts from every file of the resolved entry
    chain. The entry files themselves are never reported as imports.

    An import that does not resolve is RETURNED rather than dropped. Dropping
    it would remove it from the measured set silently, which is the exact
    failure this script exists to prevent.
    """
    root = Path(repo_root)
    entries = [entry] if entry else resolve_entries(root)
    found: list[str] = []
    seen: set[str] = set(entries)

    def walk(rel: str, depth: int) -> None:
        if depth > max_depth:
            return
        path = root / rel
        if not path.is_file():
            return
        fence = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            marker = FENCE_RE.match(line)
            if fence:
                if marker and marker.group(1) == fence:
                    fence = None
                continue
            if marker:
                fence = marker.group(1)
                continue
            match = IMPORT_RE.match(line)
            if not match:
                continue
            key = _import_key(rel, match.group(1))
            if key is None or key in seen:
                continue
            seen.add(key)
            found.append(key)
            walk(key, depth + 1)

    for start in entries:
        walk(start, 0)
    return found


def agents_md_shadowed(repo_root: Path, imports: list[str] | None = None) -> bool:
    """AGENTS.md exists, a shadow file is loaded instead, and none imports it."""
    root = Path(repo_root)
    if not (root / AGENTS_ENTRY).is_file():
        return False
    # A shadow that IS AGENTS.md (a symlink, one manual for both tools) stands
    # for AGENTS.md in the chain and loads the whole manual.
    entries = resolve_entries(root)
    if not entries or AGENTS_ENTRY in entries:
        return False
    imports = discover_imports(root) if imports is None else imports
    return AGENTS_ENTRY not in imports


def discover_registries(repo_root: Path) -> list[str]:
    """The registries Phase 1 indexes, by the predicate `--registries` uses."""
    return registry_files(Path(repo_root))


def discover_standing_orders(repo_root: Path) -> list[str]:
    """The orders that are actually always-on: `scope: always` AND `load: eager`.

    An `on-trigger` order is fetched by its vocabulary and is not part of the
    always-on surface. Counting it here would overstate the budget and hide the
    saving the load contract buys. The contract lives in
    `scripts/lib/standing_orders.py`, shared so this file and the index can
    never disagree about what is always-on.
    """
    return sorted(eager_paths(collect_orders(Path(repo_root))))


def deferred_standing_orders(repo_root: Path) -> list[tuple[str, int]]:
    """The bodies the contract moved off the always-on surface, and their size.

    Reported rather than dropped: silence about a deferred body reads exactly
    like a file that vanished.
    """
    root = Path(repo_root)
    out = []
    for order in collect_orders(root):
        if order["load"] == "eager":
            continue
        path = root / order["path"]
        size = len(path.read_bytes()) if path.is_file() else 0
        out.append((order["path"], size))
    return sorted(out)


# ------------------------------------------------------------ the counting --

def _api_token_count(text: str, model: str):
    """Exact count via `messages.count_tokens`, or None when unavailable.

    Credentials are left entirely to the SDK: an unset `ANTHROPIC_API_KEY`
    does not mean there are none, since a profile from `ant auth login` also
    authenticates a zero-argument client.
    """
    try:
        import anthropic
    except Exception:
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return int(response.input_tokens)
    except Exception:
        return None


def count_tokens(text: str, method: str, bytes_per_token: float, model: str):
    """Return (count, method_actually_used).

    A requested `api` that cannot run falls back to `bytes` and says `bytes`.
    Reporting an estimate as exact is the one outcome forbidden here.
    """
    if method == "api":
        exact = _api_token_count(text, model)
        if exact is not None:
            return exact, "api"
    size = len(text.encode("utf-8"))
    return int(round(size / float(bytes_per_token))), "bytes"


# ---------------------------------------------------------------- the rows --

def run_command_item(repo_root: Path, key: str):
    """Run a `cmd:` budget item and return its stdout, or None when it failed.

    None is deliberately not an empty string: a payload that cannot be produced
    and one that shrank to nothing look identical at zero bytes, and only one of
    them is a finding.
    """
    command = key[len(CMD_PREFIX):].strip()
    if not command.startswith(CMD_ALLOWED_PREFIX):
        sys.exit(
            f"error: budget item {key!r} is outside the command allowlist.\n"
            f"       Only {CMD_ALLOWED_PREFIX!r} is accepted."
        )
    # The meter enters through the entry file Claude Code loads (AGENTS.md, or
    # CLAUDE.md while a fork still has one), so it measures a Claude Code
    # session, and a command that behaves differently inside one has to see one. The
    # case that needs it: `memory-location.py index` prints the whole memory
    # index outside Claude Code and one line inside, because there the harness
    # already loaded the file. Run from CI or a terminal, the command row
    # counted the same index as the `harness:` row, twice.
    env = dict(os.environ)
    env["CLAUDECODE"] = "1"
    # CLAUDE_CODE_DISABLE_AUTO_MEMORY passes through untouched: with it set the
    # harness row is empty and the command prints the index itself, so the
    # index is counted once either way.
    try:
        done = subprocess.run(
            shlex.split(command),
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _described(path: Path):
    """(name, one-line description) for one listing entry, or None.

    Parsed with the YAML loader rather than a regex because a description is
    routinely a folded scalar, and a regex that keeps the fold would make the
    listing's line count a lie: one entry would occupy several lines and a
    runaway one could hide in the middle of them.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        front = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict):
        return None
    description = front.get("description")
    if not isinstance(description, str) or not description.strip():
        # No description, no listing entry: the harness lists what has one.
        return None
    # The directory carries the identity when frontmatter does not. A skill is
    # addressed by its folder, so dropping one for a missing `name:` would
    # under-report a surface this exists to stop under-reporting.
    stem = path.parent.name if path.name == "SKILL.md" else path.stem
    name = front.get("name")
    name = str(name).strip() if isinstance(name, (str, int, float)) else ""
    return (name or stem, " ".join(description.split()))


def listing_entries(repo_root: Path, key: str, include_harness: bool = False):
    """Every described entry of one listing family, or None when absent.

    `include_harness` adds the skills the harness lists from outside this
    tree (user level, enabled plugins). Only the meter row asks for them: the
    guards read the tree's own listing, so their verdict never depends on the
    machine they run on.

    None and `[]` are different findings: a family this tree does not have, and
    a family whose every entry lost its description. Only the second is a bug,
    and at zero bytes they would look identical.
    """
    family = key[len(LISTING_PREFIX):].strip()
    known = LISTINGS.get(family)
    if known is None:
        sys.exit(
            f"error: budget item {key!r} names no listing family.\n"
            f"       Known: {', '.join(sorted(LISTINGS))}."
        )
    base, pattern = known
    root = Path(repo_root)
    if not (root / base).is_dir():
        return None
    entries = []
    for path in sorted((root / base).glob(pattern)):
        entry = _described(path)
        if entry:
            entries.append(entry)
    if family == "skills" and include_harness:
        entries = _with_harness_skills(root, entries)
    return entries


# --------------------------------------- skills the harness adds on its own --
#
# The harness lists more than this tree's skills/: the user-level skills in its
# config dir (skills/ and commands/), and the skills and commands of every
# ENABLED plugin, including the extra paths its plugin.json declares. Measured on
# a live instance at 5 420 bytes on top of a listing already at its cap, and
# counted nowhere, so the meter reported headroom the session did not have.
#
# Every location is read from the harness's own files, never a hardcoded path:
# the config dir (`CLAUDE_CONFIG_DIR`, else ~/.claude), its
# `plugins/installed_plugins.json` for where each plugin is installed, and
# `enabledPlugins` across user, project and local settings for which ones load.
# Anything missing or unreadable is nothing to count, never an error: CI has
# no config dir, and a meter that crashed there would gate nothing.

def _harness_config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def _json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _settings_files(repo_root: Path, config_dir: Path) -> tuple:
    """User, project and local settings, lowest precedence first, as in the harness."""
    return (
        config_dir / "settings.json",
        repo_root / ".claude" / "settings.json",
        repo_root / ".claude" / "settings.local.json",
    )


def _merged_mapping(repo_root: Path, config_dir: Path, key: str) -> dict:
    """One object-valued setting merged per entry, the later settings file winning."""
    state: dict = {}
    for settings in _settings_files(repo_root, config_dir):
        value = _json_object(settings).get(key)
        if isinstance(value, dict):
            state.update({str(k): v for k, v in value.items()})
    return state


def _last_scalar(repo_root: Path, config_dir: Path, key: str):
    """One scalar setting as the highest-precedence file that sets it says."""
    found = None
    for settings in _settings_files(repo_root, config_dir):
        data = _json_object(settings)
        if key in data and isinstance(data[key], (int, float, str)):
            found = data[key]
    return found


def _enabled_plugins(repo_root: Path, config_dir: Path) -> set[str]:
    """Plugin keys enabled for this tree; later settings files win, as in the harness."""
    state = _merged_mapping(repo_root, config_dir, "enabledPlugins")
    return {key for key, on in state.items() if bool(on)}


# `skillOverrides` decides, per skill NAME, what the harness lists: "on" name
# and description, "name-only" the name alone, "user-invocable-only" and "off"
# nothing at all. Absent, or a value the harness does not know, counts as "on".
# Plugin skills are not affected (the harness manages those through /plugin).
SKILL_HIDDEN = frozenset({"off", "user-invocable-only"})
SKILL_NAME_ONLY = "name-only"


def skill_overrides(repo_root: Path) -> dict[str, str]:
    """skillOverrides across user, project and local settings, local winning."""
    merged = _merged_mapping(Path(repo_root), _harness_config_dir(), "skillOverrides")
    return {k: v for k, v in merged.items() if isinstance(v, str)}


def listing_settings(repo_root: Path) -> list[tuple[str, str]]:
    """The listing-budget settings in force, each named with where it came from.

    The harness truncates the listing at 1 % of the context window. The meter
    cannot know the window, so it does not compute the limit; it names what
    changes it, and only when somebody set it.
    """
    root, config_dir = Path(repo_root), _harness_config_dir()
    found = []
    for key in ("skillListingBudgetFraction", "skillListingMaxDescChars"):
        value = _last_scalar(root, config_dir, key)
        if value is not None:
            found.append((f"`{key}` (settings)", str(value)))
    env = _merged_mapping(root, config_dir, "env").get("SLASH_COMMAND_TOOL_CHAR_BUDGET")
    if env not in (None, ""):
        found.append(("`SLASH_COMMAND_TOOL_CHAR_BUDGET` (settings env)", str(env)))
    shell = os.environ.get("SLASH_COMMAND_TOOL_CHAR_BUDGET")
    if shell:
        found.append(("`SLASH_COMMAND_TOOL_CHAR_BUDGET` (environment)", shell))
    return found


def _same_path(a, b: Path) -> bool:
    try:
        return Path(str(a)).expanduser().resolve() == b.resolve()
    except (OSError, RuntimeError):
        return False


def _plugin_installs(repo_root: Path, config_dir: Path):
    """(plugin name, install dir) for every enabled plugin installed for this tree."""
    plugins = _json_object(config_dir / "plugins" / "installed_plugins.json").get("plugins")
    if not isinstance(plugins, dict):
        return []
    enabled = _enabled_plugins(repo_root, config_dir)
    found = []
    for key in sorted(plugins):
        if key not in enabled:
            continue
        installs = plugins[key]
        installs = installs if isinstance(installs, list) else [installs]
        for install in installs:
            if not isinstance(install, dict) or not install.get("installPath"):
                continue
            scope = install.get("scope", "user")
            # A project or local install loads only inside the project it names.
            if scope != "user" and not _same_path(install.get("projectPath", ""), repo_root):
                continue
            found.append((key.partition("@")[0], Path(str(install["installPath"]))))
            break
    return found


def _manifest_paths(install: Path, field: str) -> list:
    """Extra `skills`/`commands` locations a plugin.json declares, beside the defaults."""
    declared = _json_object(install / ".claude-plugin" / "plugin.json").get(field)
    declared = [declared] if isinstance(declared, str) else declared
    if not isinstance(declared, list):
        return []
    return [install / p for p in declared if isinstance(p, str) and p.strip()]


def _plugin_entry_files(install: Path) -> list:
    """Every SKILL.md and command file one plugin contributes, each once."""
    found = list(install.glob("skills/*/SKILL.md")) + list(install.glob("commands/*.md"))
    for extra in _manifest_paths(install, "skills"):
        if extra.is_file():
            found.append(extra)
        else:
            found += list(extra.glob("SKILL.md")) + list(extra.glob("*/SKILL.md"))
    for extra in _manifest_paths(install, "commands"):
        found += [extra] if extra.is_file() else list(extra.glob("*.md"))
    unique = {}
    for path in found:
        try:
            unique.setdefault(path.resolve(), path)
        except (OSError, RuntimeError):
            continue
    return sorted(unique.values())


def harness_skill_entries(repo_root: Path):
    """(user-level entries, plugin entries) the harness lists beside this tree's."""
    config_dir = _harness_config_dir()
    user = []
    paths = sorted((config_dir / "skills").glob("*/SKILL.md")) + sorted(
        (config_dir / "commands").glob("*.md")
    )
    for path in paths:
        entry = _described(path)
        if entry:
            user.append(entry)
    plugin = []
    for name, install in _plugin_installs(Path(repo_root), config_dir):
        for path in _plugin_entry_files(install):
            entry = _described(path)
            if entry:
                plugin.append((f"{name}:{entry[0]}", entry[1]))
    return user, plugin


def harness_skill_view(repo_root: Path, entries: list):
    """(listed entries, hidden names, name-only names) as the session sees them.

    This tree's skills plus the harness's own, a user-level name winning: the
    user level overrides the project level of the same name (AGENTS.md
    § Skills), so the session carries one entry for it, the user one. Then
    `skillOverrides` applies to everything but the plugin entries.
    """
    user, plugin = harness_skill_entries(repo_root)
    shadowed = {name for name, _ in user}
    own = [e for e in entries if e[0] not in shadowed] + user
    overrides = skill_overrides(repo_root)
    kept, hidden, name_only = [], [], []
    for name, desc in own:
        state = overrides.get(name)
        if state in SKILL_HIDDEN:
            hidden.append(name)
        elif state == SKILL_NAME_ONLY:
            name_only.append(name)
            kept.append((name, ""))
        else:
            kept.append((name, desc))
    return sorted(kept + plugin, key=lambda e: e[0]), hidden, name_only


def _with_harness_skills(repo_root: Path, entries: list) -> list:
    return harness_skill_view(repo_root, entries)[0]


def _listing_line(name: str, description: str) -> str:
    if not description:
        # A name-only override: the harness lists the name and nothing else.
        return f"- **{name}**\n"
    return f"- **{name}** \u2014 {description}\n"


def render_listing(repo_root: Path, key: str, include_harness: bool = False):
    """The listing as the session carries it, or None when the family is absent."""
    entries = listing_entries(repo_root, key, include_harness)
    if entries is None:
        return None
    return "".join(_listing_line(name, desc) for name, desc in entries)


def discover_listings(repo_root: Path) -> list[str]:
    """The listing families this tree actually has.

    Discovered, never merely declared. An instance that never writes the budget
    entry would otherwise carry the whole listing unmeasured, which is exactly
    the state this feature was written to end.
    """
    root = Path(repo_root)
    return [
        LISTING_PREFIX + family
        for family, (base, _) in sorted(LISTINGS.items())
        if (root / base).is_dir()
    ]


@functools.lru_cache(maxsize=1)
def _memory_location():
    spec = importlib.util.spec_from_file_location("memory_location", MEMORY_LOCATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def harness_memory_index(repo_root: Path, home: Path | None = None) -> Path | None:
    """The MEMORY.md the harness loads for this repo, or None when it loads none.

    None covers both "auto memory is switched off" and "no index yet", which
    on a fresh clone is the normal case and not an error. The directory is the
    one the harness READS (`autoMemoryDirectory`, else its per-project default),
    not the reader fallback `work/memory/`: a directory the harness does not
    load costs a session nothing until Phase 1 reads it, and that read is
    measured as its own `cmd:` row.

    Errors are NOT swallowed here. A lookup that raises is a meter that cannot
    see its subject, and `discover_harness` turns it into the failing state
    `error` rather than into "no index".
    """
    home = Path(home) if home is not None else Path.home()
    if os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "").lower() in ("1", "true"):
        return None  # the same switch the harness and memory-location.py honour
    ml = _memory_location()
    root = ml.repo_root_for(repo_root)
    enabled, _source = ml._first_setting(root, home, "autoMemoryEnabled")
    if enabled is False:
        return None
    directory, _source, _warnings = ml.resolve_memory_dir(repo_root, home)
    index = Path(directory) / "MEMORY.md"
    return index if index.is_file() else None


class HarnessError(str):
    """A harness lookup that raised, carried as its message."""


def _harness_loaded_text(text: str) -> str:
    """What the harness actually puts into the session: MEMORY.md cut at its
    load limit (lines, then bytes). Beyond it, the tail reaches a session only
    through the Phase 1 read, which is measured as its own `cmd:` row."""
    ml = _memory_location()
    lines = text.splitlines(keepends=True)[: ml.LOAD_LIMIT_LINES]
    data = "".join(lines).encode("utf-8")[: ml.LOAD_LIMIT_BYTES]
    return data.decode("utf-8", errors="ignore")


def discover_harness(repo_root: Path) -> dict[str, Path]:
    """The harness-loaded items that exist for this tree right now, by key.

    Resolved once per run: the directory lookup asks git, and a meter that
    asked it once per row would pay for that on every item.
    """
    try:
        index = harness_memory_index(repo_root)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        return {HARNESS_MEMORY_INDEX: HarnessError(f"{type(exc).__name__}: {exc}")}
    return {HARNESS_MEMORY_INDEX: index} if index else {}


def read_harness_item(key: str, found: dict[str, Path]):
    """Text of a `harness:` item, or None when the harness loads nothing there."""
    if key != HARNESS_MEMORY_INDEX:
        sys.exit(
            f"error: budget item {key!r} names no harness item.\n"
            f"       Known: {HARNESS_MEMORY_INDEX}."
        )
    index = found.get(key)
    if not index or isinstance(index, HarnessError):
        return None
    return _harness_loaded_text(index.read_text(encoding="utf-8", errors="replace"))


def item_state(
    row: dict,
    policy,
    exists: bool,
    contradiction: bool = False,
    error: bool = False,
    shadowed: bool = False,
) -> str:
    """ok | over | uncapped | undeclared | absent | missing | contradiction |
    error | shadowed.

    A row carrying `truncated_from` is a harness item cut at the harness's load
    limit: its tail never reaches the session, so it is `over` whatever the
    declared cap says.
    """
    if error:
        return "error"
    if shadowed:
        return "shadowed"
    if contradiction:
        return "contradiction"
    if policy is None:
        # Discovered on disk (or declared as an import) but absent from the
        # budget. Without this the budget silently stops covering the tree the
        # moment somebody adds an import, and a meter that cannot see a new
        # file is worse than no meter: it reports green while its subject grows.
        return "undeclared"
    if not exists:
        return "absent" if policy.get("optional") else "missing"
    if row.get("truncated_from"):
        return "over"
    cap = policy.get("max_bytes")
    if cap is None:
        return "uncapped"
    return "over" if row["bytes"] > int(cap) else "ok"


def collect_rows(repo_root: Path, budget: dict, method: str) -> list[dict]:
    """One row per always-on item, sorted by (source, path)."""
    root = Path(repo_root)
    items = budget.get("items") or {}
    calibration = budget.get("calibration") or {}
    bytes_per_token = float(calibration.get("bytes_per_token", DEFAULT_BYTES_PER_TOKEN))
    model = str(calibration.get("model", DEFAULT_MODEL))

    discovered: dict[str, str] = {}
    for rel in resolve_entries(root):
        discovered[rel] = "import"
    imports = discover_imports(root)
    for rel in imports:
        discovered.setdefault(rel, "import")
    shadowed = agents_md_shadowed(root, imports)
    if shadowed:
        # Reported even when undeclared: the finding is the shadow.
        discovered.setdefault(AGENTS_ENTRY, "import")
    registries = set(discover_registries(root))
    for rel in sorted(registries):
        discovered.setdefault(rel, "phase1")  # an import wins
    for rel in discover_standing_orders(root):
        discovered.setdefault(rel, "standing-order")
    for rel in discover_listings(root):
        discovered.setdefault(rel, "listing")
    harness = discover_harness(root)
    for rel in harness:
        discovered.setdefault(rel, "harness")

    rows = []
    for path in sorted(set(discovered) | set(items)):
        policy = items.get(path)
        source = discovered.get(path) or (policy or {}).get("source") or "phase1"
        body_bytes = None
        largest = None
        overridden = None
        settings = None
        contradiction = False
        error = None
        if path.startswith(HARNESS_PREFIX):
            if isinstance(harness.get(path), HarnessError):
                error = str(harness[path])
            text = read_harness_item(path, harness)
            exists = text is not None
            source = (policy or {}).get("source") or "harness"
        elif path.startswith(LISTING_PREFIX):
            entries = listing_entries(root, path, include_harness=True)
            exists = entries is not None
            text = render_listing(root, path, include_harness=True) if exists else None
            source = (policy or {}).get("source") or "listing"
            if entries:
                largest = sorted(
                    (
                        (name, len(_listing_line(name, desc).encode("utf-8")))
                        for name, desc in entries
                    ),
                    key=lambda pair: (-pair[1], pair[0]),
                )[:5]
            if path == LISTING_PREFIX + "skills" and exists:
                tree_only = listing_entries(root, path) or []
                _, hidden, name_only = harness_skill_view(root, tree_only)
                if hidden or name_only:
                    overridden = {"hidden": len(hidden), "name_only": len(name_only)}
                settings = listing_settings(root)
        elif path.startswith(CMD_PREFIX):
            text = run_command_item(root, path)
            exists = text is not None
            source = (policy or {}).get("source") or "command"
        elif is_agents_alias(root, path):
            # Counted under AGENTS.md: measuring the link again would charge
            # the manual twice and hold it to the legacy entry's cap.
            text, exists = None, False
        else:
            text, body_bytes, contradiction = _file_surface(
                root, path, policy, discovered.get(path) == "import", path in registries
            )
            exists = text is not None

        row = {
            "path": path,
            "source": source,
            "bytes": 0,
            "tokens": 0,
            "method": method,
            "max_bytes": (policy or {}).get("max_bytes"),
            "body_bytes": body_bytes,
            "largest": largest,
            "overridden": overridden,
            "listing_settings": settings or None,
            "advisory": (policy or {}).get("enforce") == "advisory",
        }
        if exists and path.startswith(HARNESS_PREFIX):
            full = harness[path].stat().st_size
            if full > len(text.encode("utf-8")):
                row["truncated_from"] = full
        if exists:
            row["bytes"] = len(text.encode("utf-8"))
            row["tokens"], row["method"] = count_tokens(
                text, method, bytes_per_token, model
            )
        row["state"] = item_state(
            row,
            policy,
            exists,
            contradiction,
            error is not None,
            shadowed=shadowed and path == AGENTS_ENTRY,
        )
        if is_agents_alias(root, path):
            row["alias_of"] = AGENTS_ENTRY
            if row["state"] == "missing":
                row["state"] = "absent"
        if error is not None:
            row["error"] = error
        # Advisory excuses a size, never a structural failure.
        if row["state"] in STRUCTURAL:
            row["advisory"] = False
        rows.append(row)

    rows.sort(key=lambda r: (r["source"], r["path"]))
    return rows


def _file_surface(root: Path, path: str, policy, imported: bool, registry: bool):
    """(text the session loads, body bytes when indexed, contradiction) for a file.

    One definition for the gate and the surface, so they cannot disagree.

    A registry Phase 1 indexes loads as `context-index.py --registries` prints
    it: the declared card, else the card derived from its shape. One branch,
    so the row and the CLI render it once and identically.

    Any other file with a declared card loads as that card. Measuring the file
    instead would report red for content no session pays for, and the obvious
    response to that red (raise the cap) would quietly undo the feature.

    Unless the file is ALSO `@`-imported. Then the import loads it whole and
    the card is a claim nothing honours: the full text counts, and the row
    fails as `contradiction` whatever its size.
    """
    target = root / path
    if not target.is_file():
        return None, None, False
    text = target.read_text(encoding="utf-8", errors="replace")
    card = (policy or {}).get("card")
    if imported:
        return text, None, bool(card)
    if registry or card:
        return render_card(text, card, path), len(text.encode("utf-8")), False
    return text, None, False


SURFACES = ("session", "subagent")


def always_on_parts(
    repo_root: Path, budget: dict, surface: str = "session"
) -> dict[str, str]:
    """Everything a session loads before it answers, KEYED BY WHERE IT CAME FROM.

    Same discovery as `collect_rows`, on purpose. A second definition of
    always-on would let something claim residency in a file no session reads,
    which is the failure the budget exists to make impossible.

    Keyed rather than concatenated so a caller can say WHICH file carries a
    thing, and so a mutation battery can remove one contributor at a time. A
    battery over the concatenation only proves that a substring test is a
    substring test.

    `surface="subagent"` is what a dispatched sub-agent gets: the entry chain,
    its `@`-imports and the harness listings. It runs no Phase 1, so standing
    orders, registry cards, commands and the main session's harness items never
    reach it. On both surfaces an import counts when it is actually imported,
    not when the budget declares `source: import`: a declaration loads nothing.
    """
    if surface not in SURFACES:
        raise ValueError(f"surface must be one of {SURFACES}, not {surface!r}")
    root = Path(repo_root)
    parts: dict[str, str] = {}
    harness = discover_harness(root)
    registries = set(discover_registries(root))
    imported = set(resolve_entries(root)) | set(discover_imports(root))
    for row in collect_rows(root, budget, "bytes"):
        path = row["path"]
        if row["state"] == "shadowed" or row.get("alias_of"):
            continue  # no session loads it, or it is loaded as AGENTS.md
        if row["source"] == "import" and path not in imported:
            continue  # declared an import, but nothing imports it: not loaded
        if surface == "subagent" and not (
            path.startswith(LISTING_PREFIX) or path in imported
        ):
            continue  # Phase 1, standing orders, commands, harness items
        if path.startswith(HARNESS_PREFIX):
            text = read_harness_item(path, harness)
        elif path.startswith(LISTING_PREFIX):
            text = render_listing(root, path)
        elif path.startswith(CMD_PREFIX):
            text = run_command_item(root, path)
        else:
            # The CARD is what a session loads for a declared source or a
            # registry, so it is what the surface has to be. Handing over the
            # file body would put ~25 KB of never-read registry into the
            # reachability contract and let a family claim a route through text
            # nobody sees, the second definition of always-on this function
            # exists to prevent. A contradiction loads whole, so it enters the
            # surface whole.
            policy = (budget.get("items") or {}).get(path)
            text, _, _ = _file_surface(
                root, path, policy, path in imported, path in registries
            )
        if text:
            parts[path] = text
    return parts


def always_on_text(repo_root: Path, budget: dict) -> str:
    """The same surface as one string."""
    return "\n".join(always_on_parts(repo_root, budget).values())


# -------------------------------------------------------------- the report --

def effective_method(rows: list[dict], requested: str) -> str:
    """`api` only when every measured row really got an exact count."""
    measured = [r for r in rows if r["bytes"] > 0]
    if requested == "api" and measured and all(r["method"] == "api" for r in measured):
        return "api"
    return "bytes"


def _cell(value) -> str:
    return "-" if value is None else f"{value:,}".replace(",", " ")


def render_report(
    rows: list[dict],
    method: str,
    bytes_per_token: float,
    deferred: list[tuple[str, int]] | None = None,
) -> str:
    """Deterministic markdown. No timestamp, no host, no absolute path."""
    out = ["# Context budget", ""]
    if method == "api":
        out.append("Token counts are exact (`messages.count_tokens`).")
    else:
        out.append(
            f"Token counts are an **estimate** (method `bytes`, "
            f"{bytes_per_token} bytes per token). Bytes are exact, and the caps "
            f"gate on bytes."
        )
    out += [
        "",
        "| Source | Path | Bytes | Cap | Tokens | State |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        out.append(
            f"| {row['source']} | `{row['path']}` | {_cell(row['bytes'])} | "
            f"{_cell(row['max_bytes'])} | {_cell(row['tokens'])} | {row['state']} |"
        )

    total_bytes = sum(r["bytes"] for r in rows)
    total_tokens = sum(r["tokens"] for r in rows)
    out.append(
        f"| | **total** | **{_cell(total_bytes)}** | | "
        f"**{_cell(total_tokens)}** | |"
    )

    if deferred:
        total = sum(size for _, size in deferred)
        out += [
            "",
            f"{len(deferred)} standing order(s) load on trigger and are not part "
            f"of the always-on surface ({_cell(total)} bytes, fetched by "
            f"vocabulary). They are listed here so a deferred body is never "
            f"mistaken for a file that vanished:",
            "",
        ]
        for path, size in deferred:
            out.append(f"- `{path}` ({_cell(size)} bytes)")

    indexed = [r for r in rows if r.get("body_bytes")]
    if indexed:
        out += [
            "",
            f"{len(indexed)} source(s) are indexed: the card above is always-on, "
            f"the rest arrives when somebody names an entry. Listed so a "
            f"deferred body is never mistaken for a file that shrank:",
            "",
        ]
        for row in indexed:
            deferred_bytes = row["body_bytes"] - row["bytes"]
            out.append(
                f"- `{row['path']}` — card {_cell(row['bytes'])} of "
                f"{_cell(row['body_bytes'])} bytes, {_cell(deferred_bytes)} "
                f"reachable with `context-index.py {row['path']} --get <path>`"
            )

    listings = [r for r in rows if r.get("largest")]
    if listings:
        out += [
            "",
            f"{len(listings)} listing(s) are DERIVED, not read: the harness "
            f"injects one line per entry into every session and every sub-agent "
            f"dispatch. There is no file to cap, so the cap is on the sum and "
            f"the heaviest entries are named here \u2014 a listing grows one "
            f"description at a time, and that is the growth nobody notices:",
            "",
        ]
        for row in listings:
            entries = ", ".join(f"{n} ({_cell(b)} B)" for n, b in row["largest"])
            out.append(f"- `{row['path']}` \u2014 heaviest: {entries}")

    for row in rows:
        if row.get("overridden"):
            o = row["overridden"]
            out += [
                "",
                f"`{row['path']}` applies `skillOverrides` from settings: "
                f"{o['hidden']} hidden, {o['name_only']} name-only. The row counts "
                f"what the session carries, not what the tree holds.",
            ]
        if row.get("listing_settings"):
            named = ", ".join(f"{k} = {v}" for k, v in row["listing_settings"])
            out += [
                "",
                f"`{row['path']}` budget settings in force: {named}. The harness "
                f"cuts descriptions beyond its listing budget (1 % of the context "
                f"window by default); the meter does not guess the window.",
            ]

    contradicted = [r for r in rows if r["state"] == "contradiction"]
    if contradicted:
        out += [
            "",
            f"{len(contradicted)} source(s) declare a `card:` and are also "
            f"`@`-imported. The import loads the whole file every session, so "
            f"the full text is counted above and the card is not. Remove the "
            f"`@`-import (and import a generated card file instead, if "
            f"sub-agents need the registry), or drop the `card:`:",
            "",
        ]
        for row in contradicted:
            out.append(f"- `{row['path']}` ({_cell(row['bytes'])} bytes loaded in full)")

    truncated = [r for r in rows if r.get("truncated_from")]
    if truncated:
        out += [
            "",
            f"{len(truncated)} harness item(s) exceed the harness load limit, so "
            f"their tail is silently not loaded. The row counts what loads; trim "
            f"the file below the limit:",
            "",
        ]
        for row in truncated:
            out.append(
                f"- `{row['path']}` ({_cell(row['truncated_from'])} bytes on disk, "
                f"{_cell(row['bytes'])} loaded)"
            )

    shadowed = [r for r in rows if r["state"] == "shadowed"]
    if shadowed:
        present = [
            r["path"] for r in rows
            if r["path"] in SHADOW_FILES and r["state"] not in ("absent", "missing")
        ] or ["CLAUDE.md"]
        names = ", ".join(present)
        verb = (f"{names} exists and does not import AGENTS.md" if len(present) == 1
                else f"{names} exist and none of them imports AGENTS.md")
        out += [
            "",
            f"{verb}, so Claude Code loads only {names} and none of the manual. "
            f"Run python3 {MIGRATION_SCRIPT}, or delete "
            f"{'it' if len(present) == 1 else 'them'}.",
        ]

    legacy = [
        r["path"]
        for r in rows
        if r["path"] in SHADOW_FILES
        and r["source"] == "import"
        and r["state"] not in ("absent", "missing")
    ]
    if legacy:
        out += [
            "",
            f"legacy entry {', '.join(legacy)} present: python3 "
            f"{MIGRATION_SCRIPT} moves its lines and removes it (docs/updating.md).",
        ]

    errored = [r for r in rows if r["state"] == "error"]
    if errored:
        out += [
            "",
            f"{len(errored)} harness item(s) could not be resolved, so what the "
            f"harness loads there is unknown. Fix the lookup "
            f"(`scripts/memory-location.py`); the meter does not guess:",
            "",
        ]
        for row in errored:
            out.append(f"- `{row['path']}`: {row['error']}")

    outside = [r for r in rows if r["state"] in FAILING]
    failing = [r for r in outside if not r["advisory"]]
    advisory = [r for r in outside if r["advisory"]]
    out.append("")
    if outside:
        out.append(f"{len(outside)} item(s) outside policy:")
        out.append("")
        for row in outside:
            suffix = f" — {ADVISORY_NOTE}" if row["advisory"] else ""
            out.append(f"- `{row['path']}` — {row['state']}{suffix}")
        if advisory and not failing:
            out.append("")
            out.append(
                "All of them are advisory, so the build stays green. They are "
                "still over: read the note on each item before ignoring it."
            )
    else:
        out.append("Every item is within policy.")
    out.append("")
    return "\n".join(out)


def write_user_budget(repo_root: Path, rows: list[dict], force: bool = False) -> Path:
    """`--init`: declare the undeclared, uncapped, in the per-instance overlay.

    An instance adopting this from CORE starts with every file CORE cannot know
    about reported `undeclared`, which fails the run. That is correct (a meter
    that cannot see a new file reports green while its subject grows) and it is
    also unusable as a first experience. So the first run can declare them,
    uncapped: visible in every report, failing nothing, and one line each away
    from a real cap.

    It refuses to overwrite an existing overlay without `--force`, because that
    file is hand-tuned the moment anybody cares about it.
    """
    target = Path(repo_root) / USER_BUDGET
    if target.exists() and not force:
        sys.exit(
            f"error: {USER_BUDGET} already exists.\n"
            "       It is hand-tuned once anybody has cared about a cap, so it\n"
            "       is not overwritten. Add the items by hand, or pass --force."
        )
    undeclared = [r["path"] for r in rows if r["state"] == "undeclared"]
    lines = [
        "# Per-instance context budget, layered over the CORE `context-budget.yaml`.",
        "#",
        "# Written by `measure-context.py --init` from what this instance actually",
        "# loads. Every entry starts UNCAPPED: reported in each run, failing",
        "# nothing. Add `max_bytes:` to the ones whose growth you want to hear",
        "# about, which is the entire value of the file.",
        "",
        "# The shipped schema (docs/schemas/context-budget.schema.yaml) validates",
        "# this overlay as well as the CORE file, and requires this key. It was",
        "# missing here for a day, unnoticed, because the file is gitignored by",
        "# default and no validator ever reached it.",
        "schema_version: 1",
        "",
        "items:",
    ]
    for path in undeclared:
        lines.append(f'  "{path}": {{}}')
    if not undeclared:
        lines.append("  {}")

    # A file that already exists is APPENDED to, never replaced. `--init` writes
    # the UNDECLARED items, so on a file that already declares things those items
    # are by definition no longer undeclared — and the rewrite wrote their
    # COMPLEMENT. Measured against a live instance: 162 lines, 8 380 bytes and 13
    # declarations became 15 lines, 629 bytes and none. Every cap gone, and with
    # them 147 lines explaining why each cap has its number, which is the half
    # nobody can reconstruct. One command, no confirmation, no backup.
    #
    # `--force` therefore means "add what is missing", which is what the
    # docstring above always said this was for.
    if target.exists():
        if not undeclared:
            return target
        existing = target.read_text(encoding="utf-8").rstrip("\n")
        added = [
            "",
            "  # Appended by `measure-context.py --init --force`: items this",
            "  # instance loads and had not declared. Uncapped on purpose —",
            "  # visible in every report, failing nothing. Give the ones whose",
            "  # growth should be heard about a `max_bytes:` AND a reason.",
        ]
        added += [f'  "{path}": {{}}' for path in undeclared]
        target.write_text(existing + "\n" + "\n".join(added) + "\n", encoding="utf-8")
        return target

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


# ------------------------------------------------------------------ main --

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the always-on context and hold it to its budget."
    )
    parser.add_argument("--repo-root", default=None, help="defaults to this repo")
    parser.add_argument("--method", choices=("bytes", "api"), default="bytes")
    parser.add_argument("--out", default=None, help="also write the report here")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--init",
        action="store_true",
        help="declare this instance's undeclared items, uncapped, in "
             "context-budget.user.yaml",
    )
    parser.add_argument("--force", action="store_true", help="with --init: overwrite")
    args = parser.parse_args(argv)

    root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[1]
    )
    budget = load_budget(root)
    rows = collect_rows(root, budget, args.method)

    bytes_per_token = float(
        (budget.get("calibration") or {}).get("bytes_per_token", DEFAULT_BYTES_PER_TOKEN)
    )
    if args.init:
        target = write_user_budget(root, rows, force=args.force)
        undeclared = sum(1 for r in rows if r["state"] == "undeclared")
        if not args.quiet:
            print(
                f"measure-context: declared {undeclared} item(s) uncapped in "
                f"{target.name}. Add a cap to the ones whose growth you want to "
                f"hear about."
            )
        return 0

    report = render_report(
        rows,
        effective_method(rows, args.method),
        bytes_per_token,
        deferred=deferred_standing_orders(root),
    )

    if not args.quiet:
        print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")

    return 1 if any(r["state"] in FAILING and not r["advisory"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
