# SPDX-License-Identifier: MIT
"""The cockpit's colours, read from the Bridge's own design (served as /colors.css).

The cockpit is the instance's own page, so it wears the instance default that scripts/designs.py
resolves: the active theme's `branding.design` (a file under identity/designs/), else the root
DESIGN.md (AGENTS.md, Design System). The page takes its palette from there at run time instead of
a fixed copy: every Bridge shows its own colours, and no colour file of the cockpit diverges.

The front matter may name the cockpit's tokens directly (`colors:` and `colorsDark:`, same keys),
or only the smaller open-bridge set (`colors:` with `dark-*` keys for the dark pair). A token the
file does not name falls back along a chain of related keys; the four status colours, which a
brand rarely declares, fall back to the neutral defaults in STATUS_DEFAULTS, and a token no key
answers at all (no DESIGN.md) to the plain neutrals in BASE_DEFAULTS.
"""
from __future__ import annotations

import functools
import importlib.util
import re
import sys
import threading
from pathlib import Path

import yaml

# the resolver ships beside this package: scripts/designs.py
RESOLVER = Path(__file__).resolve().parents[2] / "designs.py"

# every colour token the page uses, light and dark, with the keys that stand in when one is missing
CHAIN = {
    "primary": ["primary"],
    "primary-hover": ["primary-hover", "primary"],
    "secondary": ["secondary"],
    "accent": ["accent", "accent-from", "secondary"],
    "accent-subtle": ["accent-subtle", "surface-subtle", "surface-muted"],
    "accent-line": ["accent-line", "border"],
    "surface": ["surface"],
    "surface-raised": ["surface-raised", "surface"],
    "surface-muted": ["surface-muted", "surface-subtle"],
    "on-surface": ["on-surface"],
    "on-surface-muted": ["on-surface-muted", "secondary"],
    "on-surface-faint": ["on-surface-faint", "on-surface-muted", "secondary"],
    "on-primary": ["on-primary"],
    "border": ["border"],
    "border-strong": ["border-strong", "on-surface-muted", "secondary"],
    "success": ["success"],
    "warning": ["warning"],
    "danger": ["danger", "error"],
    "info": ["info", "accent"],
}
# dark mode looks in the dark pair first; what it lacks comes from the light set, except that the light
# primary (often near black) would vanish on a dark ground, so there the accent stands in for it
DARK_CHAIN = {**CHAIN, "primary": ["primary", "accent"], "primary-hover": ["primary-hover", "accent-secondary", "accent"]}
DARK_FROM_LIGHT = {**CHAIN, "primary": ["accent"], "primary-hover": ["accent-secondary", "accent"]}
# the status colours a brand rarely names: neutral defaults, readable on light and on dark grounds
STATUS_DEFAULTS = {
    "light": {"success": "#2D7A5F", "warning": "#B4762A", "danger": "#A33B36", "info": "#2D5B8F"},
    "dark": {"success": "#43A37B", "warning": "#D29E56", "danger": "#CE6964", "info": "#5690D2"},
}
# a Bridge without any DESIGN.md (or one that names almost nothing) still gets a readable page: plain neutrals
BASE_DEFAULTS = {
    "light": {"primary": "#111827", "primary-hover": "#1F2937", "secondary": "#6B7280", "accent": "#4F46E5",
              "accent-subtle": "#EEF2FF", "accent-line": "#C7D2FE", "surface": "#FFFFFF", "surface-raised": "#FFFFFF",
              "surface-muted": "#F3F4F6", "on-surface": "#1F2937", "on-surface-muted": "#4B5563",
              "on-surface-faint": "#6B7280", "on-primary": "#FFFFFF", "border": "#E5E7EB", "border-strong": "#9CA3AF"},
    "dark": {"primary": "#818CF8", "primary-hover": "#A5B4FC", "secondary": "#9CA3AF", "accent": "#818CF8",
             "accent-subtle": "#1E1B4B", "accent-line": "#4338CA", "surface": "#111827", "surface-raised": "#1F2937",
             "surface-muted": "#1F2937", "on-surface": "#F3F4F6", "on-surface-muted": "#D1D5DB",
             "on-surface-faint": "#9CA3AF", "on-primary": "#111827", "border": "#374151", "border-strong": "#6B7280"},
}
DEFAULTS = {mode: {**BASE_DEFAULTS[mode], **STATUS_DEFAULTS[mode]} for mode in STATUS_DEFAULTS}
# the inner room stays dark in both modes: its colours are dark tokens under their own names
VOID = {"void": "surface", "void-raised": "surface-raised", "void-line": "border", "void-text": "on-surface",
        "void-muted": "on-surface-muted", "void-faint": "on-surface-faint", "void-identity": "accent",
        "void-infra": "accent-line", "void-workflow": "success", "void-work": "warning", "void-core": "on-primary",
        "void-docs": "on-surface-muted", "void-other": "on-surface-faint", "void-live-working": "secondary",
        "void-live-asks": "warning", "void-live-answer": "success", "void-live-alarm": "danger"}
# the derived values that follow the mode, by reference only (no colour of their own)
DERIVED = {
    "light": {"primary-edge": "var(--primary)", "counter": "var(--secondary)", "series-2": "var(--accent)",
              "ink": "var(--primary)", "scrim": "rgb(4 14 26 / 0.32)"},
    "dark": {"primary-edge": "var(--accent-line)", "counter": "var(--accent)", "series-2": "var(--accent-line)",
             "ink": "var(--on-surface)", "scrim": "rgb(0 0 0 / 0.55)"},
}
HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\Z")


def front_matter(path: Path) -> dict:
    """The YAML between the first two `---` lines of DESIGN.md; empty when there is none or it does not parse."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(\n|\Z)", text, re.S)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _hexes(block) -> dict:
    return {str(k): str(v) for k, v in (block or {}).items() if isinstance(v, str) and HEX.match(v.strip())} \
        if isinstance(block, dict) else {}


def palette(design: dict) -> dict:
    """{"light": {token: hex}, "dark": {token: hex}} for every token in CHAIN."""
    colors = _hexes(design.get("colors"))
    light_src = {k: v for k, v in colors.items() if not k.startswith("dark-")}
    dark_src = _hexes(design.get("colorsDark")) or {k[5:]: v for k, v in colors.items() if k.startswith("dark-")}
    out = {"light": {}, "dark": {}}
    for mode, lookups in (("light", [(light_src, CHAIN)]), ("dark", [(dark_src, DARK_CHAIN), (light_src, DARK_FROM_LIGHT)])):
        for token in CHAIN:
            value = next((src[k] for src, chain in lookups for k in chain[token] if k in src), None)
            out[mode][token] = value or DEFAULTS[mode][token]
    return out


def _block(selector: str, values: dict, scheme: str | None = None, indent: str = "  ") -> str:
    head = f"{indent}color-scheme: {scheme};\n" if scheme else ""
    return f"{selector} {{\n{head}" + "".join(f"{indent}--{k}: {v};\n" for k, v in values.items()) + "}\n"


def colors_css(design: dict) -> str:
    """The stylesheet: light colours on :root, dark ones under .dark and under prefers-color-scheme when the page
    set no .light, and the inner room's always-dark colours."""
    pal = palette(design)
    light = {**pal["light"], **DERIVED["light"]}
    dark = {**pal["dark"], **DERIVED["dark"]}
    void = {name: pal["dark"][token] for name, token in VOID.items()}
    nested = _block("  :root:not(.light)", dark, "dark", "    ").replace("\n}\n", "\n  }\n")
    return ("/* generated from DESIGN.md by scripts/lib/bridge_cockpit/design.py: edit DESIGN.md, not this */\n"
            + _block(":root", light, "light") + _block(":root.dark", dark, "dark")
            + "@media (prefers-color-scheme: dark) {\n" + nested + "}\n" + _block(":root", void))


SERIF_WORDS = ("serif", "playfair", "georgia", "garamond", "times")


def _stack(name: str) -> str:
    if name == "system-ui":
        return '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'
    family = f'"{name}"' if " " in name else name
    if any(w in name.lower() for w in SERIF_WORDS) and "sans" not in name.lower():
        return f'{family}, Georgia, "Times New Roman", serif'
    return f'{family}, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'


def fonts_css(design: dict) -> str:
    """--font-display and --font-ui from DESIGN.md typography (display or h1; a body style), system stacks behind."""
    typo = design.get("typography") if isinstance(design.get("typography"), dict) else {}

    def family(*names):
        for name in names:
            style = typo.get(name)
            value = style.get("fontFamily") if isinstance(style, dict) else None
            if isinstance(value, str) and value.strip():
                return value.split(",")[0].strip().strip('"')
        return None
    ui = family("body-md", "body", "body-lg") or "system-ui"
    display = family("display", "h1") or ui
    return f":root {{\n  --font-display: {_stack(display)};\n  --font-ui: {_stack(ui)};\n}}\n"


@functools.lru_cache(maxsize=1)
def _resolver():
    """scripts/designs.py, loaded once: /colors.css asks on every request."""
    spec = importlib.util.spec_from_file_location("bridge_designs", RESOLVER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RESOLVED: dict[str, tuple[tuple, tuple[Path, str | None]]] = {}
_RESOLVED_LOCK = threading.Lock()


def _stat(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _inputs(root: Path) -> tuple:
    """Everything a resolution reads: bridge-config.yaml, every theme, the design family (its folder's
    mtime moves when a design is added or removed) and whether DESIGN.md exists. Stats only, no parsing."""
    themes = sorted((root / "themes").glob("*.yaml"))
    return (_stat(root / "bridge-config.yaml"), tuple((p.name, _stat(p)) for p in themes),
            _stat(root / "identity" / "designs"), (root / "DESIGN.md").is_file())


def resolved(root: Path) -> tuple[Path, str | None]:
    """The design file the cockpit wears, and the reason when it had to fall back to DESIGN.md.

    Only the instance default applies (steps 5 and 6 of scripts/designs.py): the cockpit belongs to no
    context and no persona. A theme naming an unknown design still gets a page, with the error said
    in the stylesheet and on stderr, never swallowed. Kept until a file the resolution reads changes,
    since /colors.css asks on every request."""
    root = Path(root)
    inputs = _inputs(root)
    with _RESOLVED_LOCK:
        hit = _RESOLVED.get(str(root))
        if hit and hit[0] == inputs:
            return hit[1]
    answer = _resolve(root)
    with _RESOLVED_LOCK:
        _RESOLVED[str(root)] = (inputs, answer)
    return answer


def _resolve(root: Path) -> tuple[Path, str | None]:
    default = Path(root) / "DESIGN.md"
    if not RESOLVER.is_file():
        return default, None
    designs = _resolver()
    try:
        return designs.resolve(Path(root)).path or default, None
    except designs.DesignError as err:
        print(f"cockpit: {err}; showing DESIGN.md", file=sys.stderr)
        return default, str(err)


def design_file(root: Path) -> Path:
    return resolved(root)[0]


def stylesheet(root: Path) -> str:
    path, error = resolved(root)
    design = front_matter(path)
    note = f"/* design error: {error.replace('*/', '* /')}; showing DESIGN.md */\n" if error else ""
    return note + colors_css(design) + fonts_css(design)
