"""Repository root discovery and the `workloads:` block of the bridge config.

Every path, prefix and deadline this skill uses comes from here. That is what
keeps the code generic: an instance name, a personal path or a label prefix in
a source file is exactly what makes a skill unpromotable, so nothing of the
kind may appear anywhere except as a default in this file.

An absent `workloads:` block yields the defaults. It is never a crash: a Bridge
that has not configured this skill still has to be able to run it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import ConfigError, Disabled as errors_Disabled, RepoRootNotFound
from .model import Guarantee

#: Where declarations live when nothing says otherwise.
DEFAULT_DIR = "workflow/workloads"

#: Files whose presence marks the root of a Bridge checkout.
ROOT_MARKERS = ("bridge-config.yaml", "AGENTS.md")

CONFIG_FILE = "bridge-config.yaml"
CONFIG_KEY = "workloads"


@dataclass(frozen=True)
class Config:
    """The `workloads:` block, with every default spelled out."""

    enabled: bool = True
    dir: str = DEFAULT_DIR
    stamp_dir: str = "~/.bridge/workloads"
    label_prefix: str = "bridge"
    dispatcher_registry: str | None = None
    dispatcher_guarantees: tuple = ()
    #: The declared alarm path: {command: [...], detail: [...]}. See
    #: engine/notify.py; a bare string is refused there, with the shape.
    notify_via: dict | None = None
    #: The words of a message, over engine/notify.py TEXT_DEFAULTS (English).
    #: An instance that reads its alarms in another language writes them here.
    notify_text: dict | None = None
    step_timeout_sec: int = 60
    probe_timeout_sec: int = 30
    ssh_connect_timeout_sec: int = 10
    #: Where the block was read from, for error messages.
    source: str = ""


def require_enabled(cfg: Config) -> None:
    """Refuse when the configuration says this skill is off.

    SKILL.md carried this sentence from the beginning and no line of code ever
    asked, so `workloads.enabled: false` was a switch connected to nothing: an
    instance that had deliberately shut the skill down still got a provisioner
    that wrote to its machines. The key was read here, stored on the dataclass,
    serialised, and never consulted anywhere.

    A guard, so it leaves as `Refused` and therefore as exit code 3. It names
    both the key and the file it was read from, because the file is the one
    thing the reader has to open and the default source is empty on a Bridge
    that has no config at all.
    """
    if cfg.enabled:
        return
    where = cfg.source or CONFIG_FILE
    raise errors_Disabled(
        f"{where}: {CONFIG_KEY}.enabled is false, so this skill does nothing "
        f"until that is changed", source=where)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up until a Bridge root is found.

    Starts from the RESOLVED location of this file by default, because the
    skill is reached through the discovery symlink and the unresolved path
    points into a directory that is not the repository.
    """
    origin = Path(start) if start is not None else Path(__file__).resolve().parent
    origin = origin.resolve()
    if origin.is_file():
        origin = origin.parent
    for candidate in (origin, *origin.parents):
        for marker in ROOT_MARKERS:
            if (candidate / marker).exists():
                return candidate
    raise RepoRootNotFound(
        f"no {' or '.join(ROOT_MARKERS)} above {origin}", start=str(origin))


def _guarantees(values, source) -> tuple:
    out = []
    for value in values or ():
        try:
            out.append(Guarantee(value))
        except ValueError:
            raise ConfigError(
                f"{source}: {CONFIG_KEY}.dispatcher_guarantees: unknown guarantee "
                f"{value!r}, allowed: {', '.join(g.value for g in Guarantee)}",
                source=source) from None
    return tuple(out)


def load_config(root: Path) -> Config:
    """The `workloads:` block of the bridge config, defaults filled in."""
    path = Path(root) / CONFIG_FILE
    raw = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = (loaded.get(CONFIG_KEY) or {}) if isinstance(loaded, dict) else {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: {CONFIG_KEY}: expected a mapping", source=str(path))
    defaults = Config()
    return Config(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        dir=str(raw.get("dir", defaults.dir)),
        stamp_dir=str(raw.get("stamp_dir", defaults.stamp_dir)),
        label_prefix=str(raw.get("label_prefix", defaults.label_prefix)),
        dispatcher_registry=raw.get("dispatcher_registry", defaults.dispatcher_registry),
        dispatcher_guarantees=_guarantees(raw.get("dispatcher_guarantees"), str(path)),
        notify_via=raw.get("notify_via", defaults.notify_via),
        notify_text=raw.get("notify_text", defaults.notify_text),
        step_timeout_sec=int(raw.get("step_timeout_sec", defaults.step_timeout_sec)),
        probe_timeout_sec=int(raw.get("probe_timeout_sec", defaults.probe_timeout_sec)),
        ssh_connect_timeout_sec=int(raw.get("ssh_connect_timeout_sec",
                                            defaults.ssh_connect_timeout_sec)),
        source=str(path),
    )
