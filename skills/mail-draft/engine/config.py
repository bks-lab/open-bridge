"""Where the Bridge is, and what its `mail:` block says.

Every value a draft needs that is not the message itself comes from the tree:
the persona carries the footer, the mandant carries the recipient, DESIGN.md
carries the colours, `bridge-config.yaml` carries the defaults. This module
finds the tree and reads the defaults. Nothing here is a hardcoded preference.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULTS = {
    # apple-mail | outlook | eml | none. `none` only writes the bundle.
    "client": "",
    # plain | minimal | design. `design` derives every colour from DESIGN.md.
    "theme": "design",
    "persona": "",
    "footer": "",
    # BCP 47 primary language of the footer variants without a suffix.
    "language": "en",
    # Gitignored by default: a draft carries addresses and private text.
    "drafts_dir": ".bridge/mail-drafts",
    # Shown above the title in the card. Empty means no eyebrow.
    "eyebrow": "",
    # Skill to load for tone before a draft is written, e.g. a style guide.
    "style_skill": "",
    "labels": {},
    # Words that promise an attachment. A body using one with no file attached
    # is flagged. Instances add their own language here.
    "attachment_words": ["attached", "attachment", "enclosed", "see the file"],
    "max_attachment_mb": 20,
    # Per-role overrides for the design theme: {link: secondary, ...}.
    "tokens": {},
    # Short link targets a body may use instead of a URL: {"site:home": "https://..."}.
    # A profile's own map wins key by key.
    "link_aliases": {},
    # `## <word>` headings dressed as a callout or a warning: {callout: [...], warning: [...]}.
    "heading_styles": {},
}


class ConfigError(Exception):
    pass


def find_root() -> Path:
    """The Bridge this skill belongs to: MAIL_DRAFT_ROOT, else the skill's own tree.

    Never the current directory. Run from inside another instance, the cwd
    would hand this instance's engine the other instance's mandants and
    footers (rules/multi-instance-isolation.md).
    """
    env = os.environ.get("MAIL_DRAFT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def parse_yaml(text: str, what: str):
    try:
        import yaml
    except ImportError as err:  # pragma: no cover - environment, not logic
        raise ConfigError(
            f"PyYAML is needed to read {what}. Install it with: pip install pyyaml"
        ) from err
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise ConfigError(f"{what}: not valid YAML ({err})") from err


def load_yaml(path: Path):
    return parse_yaml(path.read_text(encoding="utf-8"), str(path.name)) or {}


@dataclass
class MailConfig:
    root: Path
    values: dict = field(default_factory=dict)

    def get(self, key: str):
        return self.values.get(key, DEFAULTS.get(key))

    @property
    def drafts_dir(self) -> Path:
        p = Path(os.path.expanduser(str(self.get("drafts_dir"))))
        return p if p.is_absolute() else self.root / p


def load(root: Path | None = None) -> MailConfig:
    root = root or find_root()
    values = dict(DEFAULTS)
    cfg_path = root / "bridge-config.yaml"
    if cfg_path.is_file():
        block = (load_yaml(cfg_path) or {}).get("mail") or {}
        if not isinstance(block, dict):
            raise ConfigError("bridge-config.yaml: `mail:` must be a mapping")
        values.update(block)
    return MailConfig(root=root, values=values)
