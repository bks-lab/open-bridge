"""Colours and type for a draft, derived from DESIGN.md and never chosen here.

A mail client cannot read a stylesheet variable, so every value ends up inline
as a hex code. The `design` theme reads DESIGN.md's frontmatter and maps it to
the roles a mail needs (`link`, `text`, `card_bg`, ...). Each role has a list of
candidate tokens because forks name their tokens differently: one calls the link
colour `secondary`, another calls it `accent`. The first candidate that is
present AND readable wins.

Readable is measured, not assumed: a text role must reach WCAG AA (4.5:1) on the
card it sits on. A brand accent that is fine for a 72px headline is often too
light for a 15px link, and a mail has no headline that large. When no candidate
reaches AA, the first one is darkened until it does, and `explain()` says so.
The token stays the source; the adjustment is reported, never silent.

`plain` and `minimal` are not lesser versions of the design. They are the
version for a recipient for whom a designed mail would be wrong.

WHICH design: the Bridge resolves it (scripts/designs.py), asked with the
persona the mail goes out under, so a second identity can wear a second brand
(`design_ref:` in identity/personas/<id>.yaml). Outside a Bridge, where no
resolver ships, it is the root DESIGN.md as before.
"""

from __future__ import annotations

import re
from pathlib import Path

FALLBACK_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, Arial, sans-serif"
FALLBACK_SERIF = "Georgia, 'Times New Roman', serif"
FALLBACK_MONO = "SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace"

# Built-in neutral values. A design theme starts from these and overrides what
# DESIGN.md provides, so a fork with a sparse DESIGN.md still gets a full mail.
NEUTRAL = {
    "primary": "#111827",
    "link": "#1d4ed8",
    "text": "#1f2937",
    "text_muted": "#4b5563",
    "bg": "#ffffff",
    "card_bg": "#ffffff",
    "muted_bg": "#f3f4f6",
    "border": "#e5e7eb",
    "accent_subtle": "#eef2ff",
    "accent_line": "#c7d2fe",
    "header_bg": "#f3f4f6",
    "header_text": "#111827",
    "on_primary": "#ffffff",
    "success": "#047857",
    "info": "#1d4ed8",
    "warning": "#b45309",
    "danger": "#b91c1c",
    "masthead": "",
    "font_body": FALLBACK_SANS,
    "font_display": FALLBACK_SANS,
    "font_mono": FALLBACK_MONO,
    "base_size": "15px",
    "base_line": "1.6",
    "card": False,
    "zebra": True,
    "display_headings": False,
}

NEUTRAL_DARK = {
    "bg": "#111418",
    "card_bg": "#1a1e24",
    "muted_bg": "#232831",
    "text": "#e6e9ee",
    "text_muted": "#a6afbb",
    "border": "#343c48",
    "link": "#7fb0ff",
    "accent_subtle": "#1c2638",
    "accent_line": "#34496b",
}

BUILTIN = {
    "plain": {
        **NEUTRAL,
        "link": "#0645ad",
        "text": "#222222",
        "text_muted": "#555555",
        "header_bg": "#eeeeee",
        "zebra": False,
        "accent_subtle": "",
        "plain_headings": True,
    },
    "minimal": {**NEUTRAL},
}

# role -> candidate tokens in DESIGN.md `colors`, first readable one wins.
ROLE_TOKENS = {
    "primary": ["primary"],
    "link": ["link", "accent", "secondary", "info"],
    "text": ["on-surface", "text", "primary"],
    "text_muted": ["on-surface-muted", "text-muted", "secondary"],
    "bg": ["surface"],
    "card_bg": ["surface-raised", "surface"],
    "muted_bg": ["surface-muted", "surface-subtle"],
    "border": ["border"],
    "accent_subtle": ["accent-subtle", "surface-subtle"],
    "accent_line": ["accent-line", "border"],
    "header_bg": ["primary"],
    "header_text": ["on-primary"],
    "on_primary": ["on-primary"],
    "success": ["success"],
    "info": ["info", "accent"],
    "warning": ["warning", "attention"],
    "danger": ["danger", "error"],
    "masthead": ["primary"],
}

# Roles that carry text and therefore must be readable on the card.
TEXT_ROLES = {"link", "text", "text_muted", "primary"}
# Roles whose text sits on a filled surface: (role, surface role).
ON_FILL = {"header_text": "header_bg"}

DARK_ROLES = {
    "bg": ["surface"],
    "card_bg": ["surface-raised", "surface"],
    "muted_bg": ["surface-muted", "surface-subtle"],
    "text": ["on-surface"],
    "text_muted": ["on-surface-muted"],
    "border": ["border"],
    "link": ["link", "secondary", "accent", "info"],
    "accent_subtle": ["accent-subtle", "surface-subtle"],
    "accent_line": ["accent-line", "border"],
}

HEX = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


# ---------------------------------------------------------------- contrast --

def _rgb(hexcode: str) -> tuple[float, float, float]:
    h = hexcode.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _lum(hexcode: str) -> float:
    def ch(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(hexcode))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(hexcode: str) -> float:
    r, g, b = _rgb(hexcode)
    hi, lo = max(r, g, b), min(r, g, b)
    return 0.0 if hi == 0 else (hi - lo) / hi


def contrast(fg: str, bg: str) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _toward(hexcode: str, target: float, step: float) -> str:
    r, g, b = _rgb(hexcode)
    mix = lambda c: c + (target - c) * step  # noqa: E731
    return "#" + "".join(f"{round(mix(c) * 255):02x}" for c in (r, g, b))


def ensure_contrast(fg: str, bg: str, minimum: float = 4.5) -> str:
    """`fg` itself if readable on `bg`, else the nearest shade of it that is."""
    if contrast(fg, bg) >= minimum:
        return fg
    target = 0.0 if _lum(bg) > 0.5 else 1.0
    for i in range(1, 21):
        candidate = _toward(fg, target, i / 20)
        if contrast(candidate, bg) >= minimum:
            return candidate
    return "#000000" if target == 0.0 else "#ffffff"


# ------------------------------------------------------------------ design --

def _resolver():
    """scripts/designs.py of the Bridge this skill ships in, or None outside one.

    The code comes from the skill's own tree, the data from `root`: the
    resolver is pure, and MAIL_DRAFT_ROOT may name another tree (the tests do).
    """
    path = Path(__file__).resolve().parents[3] / "scripts" / "designs.py"
    if not path.is_file():
        return None
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("bridge_designs", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError:          # no PyYAML: the root DESIGN.md, as before
        return None
    return mod


def design_file(root: Path, persona: str | None = None) -> Path | None:
    """The design a mail wears: resolved for `persona`, else the root DESIGN.md."""
    designs = _resolver()
    if designs is None:
        path = root / "DESIGN.md"
        return path if path.is_file() else None
    try:
        return designs.resolve(root, persona=persona or None).path
    except designs.DesignError as err:
        from .config import ConfigError  # noqa: PLC0415
        raise ConfigError(str(err)) from err


def read_design(root: Path, persona: str | None = None) -> dict:
    path = design_file(root, persona)
    if path is None or not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    from .config import parse_yaml  # noqa: PLC0415 - plain themes never need PyYAML
    return parse_yaml(text[3:end], path.name) or {}


def _font_stack(family: str | None, fallback: str) -> str:
    if not family:
        return fallback
    # The stack lands inside style="..."; a double quote would end the attribute.
    family = str(family).strip().replace('"', "'")
    if "," in family:
        return family
    quoted = f"'{family}'" if " " in family else family
    return f"{quoted}, {fallback}"


def _dark_tokens(design: dict) -> dict:
    """`colorsDark` if present, else `dark-*` prefixed keys in `colors`."""
    if isinstance(design.get("colorsDark"), dict):
        return {str(k).lower(): str(v) for k, v in design["colorsDark"].items()}
    colors = design.get("colors") or {}
    return {k[5:].lower(): str(v) for k, v in colors.items() if str(k).startswith("dark-")}


def _pick(tokens: dict, candidates: list[str]) -> str | None:
    for name in candidates:
        value = tokens.get(name)
        if value and HEX.match(str(value)):
            return str(value).lower()
    return None


class Theme(dict):
    """A flat role -> value map plus the notes on how each value was reached."""

    def __init__(self, values: dict, dark: dict, notes: list[str], name: str, tokens: dict | None = None):
        super().__init__(values)
        self.dark = dark
        self.notes = notes
        self.name = name
        # Every DESIGN.md colour by its own name, for a badge that names a token
        # (`secondary`, `accent`) rather than a role.
        self.tokens = tokens or {}

    def explain(self) -> str:
        lines = [f"theme: {self.name}"]
        lines += [f"  {n}" for n in self.notes] or ["  (all values built in)"]
        return "\n".join(lines)


def build_design(design: dict, overrides: dict | None = None) -> Theme:
    colors = {str(k).lower(): v for k, v in (design.get("colors") or {}).items()}
    overrides = overrides or {}
    values: dict = dict(NEUTRAL, card=True, display_headings=False)
    notes: list[str] = []

    for role, candidates in ROLE_TOKENS.items():
        if role in overrides:
            candidates = [str(overrides[role])]
        picked = None
        source = None
        for name in candidates:
            value = colors.get(name)
            if not (value and HEX.match(str(value))):
                continue
            value = str(value).lower()
            # A grey is not a link colour: next to grey body text it does not
            # read as a link. Unless pinned, links take a chromatic token.
            if role == "link" and role not in overrides and saturation(value) < 0.2:
                continue
            if role in TEXT_ROLES and contrast(value, colors.get("surface-raised", colors.get("surface", "#ffffff"))) < 4.5:
                picked = picked or (value, name, False)
                continue
            picked, source = (value, name, True), name
            break
        if not picked:
            continue
        value, name, readable = picked
        if not readable:
            card = str(colors.get("surface-raised", colors.get("surface", "#ffffff"))).lower()
            fixed = ensure_contrast(value, card)
            notes.append(f"{role}: no candidate reached 4.5:1 on {card}; {name} {value} darkened to {fixed}")
            value = fixed
        elif source and source != candidates[0]:
            notes.append(f"{role}: {source} ({value}), first readable of {', '.join(candidates)}")
        values[role] = value

    for role, surface in ON_FILL.items():
        fixed = ensure_contrast(values[role], values[surface])
        if fixed != values[role]:
            notes.append(f"{role}: {values[role]} unreadable on {values[surface]}, using {fixed}")
            values[role] = fixed

    typo = design.get("typography") or {}
    body = (typo.get("body-md") or typo.get("body") or {}).get("fontFamily")
    display = (typo.get("h1") or typo.get("display") or {}).get("fontFamily")
    mono = (typo.get("code") or typo.get("mono-label") or {}).get("fontFamily")
    values["font_body"] = _font_stack(body, FALLBACK_SANS)
    serif = display and str(display).lower() not in (str(body or "").lower(),) and _looks_serif(display)
    values["font_display"] = _font_stack(display, FALLBACK_SERIF if serif else FALLBACK_SANS)
    values["font_mono"] = _font_stack(mono, FALLBACK_MONO)
    # A second family is the hierarchy: display only for the title, and only
    # when it really is a different family.
    values["display_headings"] = bool(display and body and str(display) != str(body))

    dark_src = _dark_tokens(design)
    dark = dict(NEUTRAL_DARK)
    for role, candidates in DARK_ROLES.items():
        value = _pick(dark_src, candidates)
        if value:
            dark[role] = value
    for role in ("text", "text_muted", "link"):
        dark[role] = ensure_contrast(dark[role], dark["card_bg"])

    tokens = {k: str(v).lower() for k, v in colors.items() if HEX.match(str(v))}
    return Theme(values, dark, notes, "design", tokens)


def _looks_serif(family: str) -> bool:
    f = str(family).lower()
    return any(w in f for w in ("serif", "playfair", "georgia", "garamond", "times", "merriweather", "lora")) and "sans" not in f


def load(name: str, root: Path, overrides: dict | None = None, persona: str | None = None) -> Theme:
    if name in BUILTIN:
        return Theme(dict(BUILTIN[name]), dict(NEUTRAL_DARK), [], name)
    if name == "design":
        design = read_design(root, persona)
        if not design:
            return Theme(dict(BUILTIN["minimal"]), dict(NEUTRAL_DARK),
                         ["DESIGN.md has no frontmatter, using minimal"], "design")
        return build_design(design, overrides)
    from .config import ConfigError  # noqa: PLC0415
    raise ConfigError(f"unknown theme '{name}', use plain, minimal or design")
