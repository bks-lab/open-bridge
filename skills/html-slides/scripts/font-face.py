#!/usr/bin/env python3
"""Preset font families -> an embedded @font-face <style> block, no font CDN.

A thin wrapper: the work is done by html-canvas/scripts/embed-fonts.py, the one
font embedder every HTML skill shares. This script only knows where a preset
lives (presets/<slug>.yaml) and where this skill keeps its woff2 files
(assets/fonts/, searched before html-canvas's bundled fonts), and wraps the
rules in a <style> element ready for a deck's deck-fonts region.

Every weight a preset names is embedded (a display weight 800 is the real
800 cut, not a synthesised bold), and a weight with no file is reported on
stderr instead of being dropped in silence.

Usage:
    python3 scripts/font-face.py <preset-slug>                # to stdout
    python3 scripts/font-face.py <preset-slug> --out block.css

A `system_only: true` preset (terminal-mono, for example) has nothing to embed.
scripts/new-deck.py calls the same functions, so a deck's font region and this
script's output are the same bytes.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
PRESETS_DIR = SKILL_DIR / "presets"
FONTS_DIR = SKILL_DIR / "assets" / "fonts"
EMBED_FONTS = SKILL_DIR.parent / "html-canvas" / "scripts" / "embed-fonts.py"

HEADER = "/* Self-hosted preset fonts, embedded (no font CDN). */"

_EMBED = None


def embed_fonts():
    """html-canvas/scripts/embed-fonts.py, imported by path (hyphenated name)."""
    global _EMBED
    if _EMBED is None:
        if not EMBED_FONTS.is_file():
            sys.exit("font-face: %s not found; html-slides needs the html-canvas skill next to it"
                     % EMBED_FONTS)
        spec = importlib.util.spec_from_file_location("html_canvas_embed_fonts", EMBED_FONTS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _EMBED = mod
    return _EMBED


def collect_roles(preset: dict | Path) -> list[tuple[str, list[int]]]:
    """(family, weights) per family a preset names, through embed-fonts' reader.

    Accepts the parsed preset or its path. Flat roles (`body: Inter`) take
    `fonts.weights`; nested roles carry their own; `system_only` embeds nothing.
    """
    if isinstance(preset, Path):
        families = embed_fonts().collect_families(preset)
    else:
        with tempfile.TemporaryDirectory(prefix="font-face-") as tmp:
            path = Path(tmp) / "preset.yaml"
            path.write_text(yaml.safe_dump({"fonts": preset.get("fonts") or {}}), encoding="utf-8")
            families = embed_fonts().collect_families(path)
    return list(families.items())


def font_face_block(roles: list[tuple[str, list[int]]], font_dirs: list[Path] | None = None) -> str:
    """A <style> block with one base64 @font-face rule per family and weight."""
    dirs = [FONTS_DIR] + list(font_dirs or [])
    css = embed_fonts().build_font_face_css(dict(roles), dirs)
    return "<style>\n%s\n%s</style>" % (HEADER, css)


def main() -> None:
    parser = argparse.ArgumentParser(description="Preset font families -> embedded @font-face block")
    parser.add_argument("preset", help="preset slug, e.g. swiss-modern (without .yaml)")
    parser.add_argument("--out", help="write to this file instead of stdout")
    args = parser.parse_args()

    preset_path = PRESETS_DIR / f"{args.preset}.yaml"
    if not preset_path.exists():
        print(f"ERROR: preset not found: {preset_path}", file=sys.stderr)
        sys.exit(1)

    preset = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
    if preset.get("source") == "design":
        print("ERROR: the design preset takes its fonts from DESIGN.md; "
              "use scripts/new-deck.py or html-canvas/scripts/embed-fonts.py DESIGN.md", file=sys.stderr)
        sys.exit(1)
    roles = collect_roles(preset)
    if not roles:
        print("/* system_only: true, no font to embed. */")
        return

    block = font_face_block(roles)
    if args.out:
        Path(args.out).write_text(block + "\n", encoding="utf-8")
        print(f"-> wrote {args.out} ({len(block)} characters)", file=sys.stderr)
    else:
        print(block)


if __name__ == "__main__":
    main()
