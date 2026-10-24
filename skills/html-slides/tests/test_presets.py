"""Every shipped preset follows the schema presets/_template.yaml documents.

The template is the schema: the colour keys a preset must define are read from
it, not from a second list here, so a key added to the template is enforced on
every preset at once.
"""
from __future__ import annotations

import re

import pytest
import yaml

from slides_testlib import ASSETS, PRESETS, preset_files

TEMPLATE = yaml.safe_load((PRESETS / "_template.yaml").read_text("utf-8"))
REQUIRED_TOP = ("name", "slug", "default", "mood", "use_for", "personality", "fonts", "colors")
ROLES = ("display", "body", "mono")
COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))$")
PRESETS_SHIPPED = preset_files()


def _slugify(family: str) -> str:
    return family.strip().lower().replace(" ", "-")


def test_presets_exist():
    assert len(PRESETS_SHIPPED) >= 1


def test_template_lists_color_keys_for_both_modes():
    for mode in ("dark", "light"):
        assert len(TEMPLATE["colors"][mode]) >= 20, mode


@pytest.mark.parametrize("path", PRESETS_SHIPPED, ids=lambda p: p.stem)
def test_preset_top_level(path):
    data = yaml.safe_load(path.read_text("utf-8"))
    missing = [k for k in REQUIRED_TOP if k not in data]
    assert not missing, "missing keys: %s" % missing
    assert data["slug"] == path.stem, "slug must match the filename"
    assert isinstance(data["default"], bool)
    assert isinstance(data["mood"], list) and 2 <= len(data["mood"]) <= 4
    for key in ("name", "use_for", "personality"):
        assert isinstance(data[key], str) and data[key].strip(), key
    unknown = set(data) - set(REQUIRED_TOP) - {"css_overrides"}
    assert not unknown, "keys the template does not document: %s" % sorted(unknown)
    if "css_overrides" in data:
        assert isinstance(data["css_overrides"], str)


@pytest.mark.parametrize("path", PRESETS_SHIPPED, ids=lambda p: p.stem)
def test_preset_colors_match_template(path):
    data = yaml.safe_load(path.read_text("utf-8"))
    for mode in ("dark", "light"):
        want = set(TEMPLATE["colors"][mode])
        have = set(data["colors"][mode])
        assert have == want, "%s: missing %s, extra %s" % (mode, sorted(want - have), sorted(have - want))
        bad = {k: v for k, v in data["colors"][mode].items() if not COLOR_RE.match(str(v).strip())}
        assert not bad, "%s: not a colour: %s" % (mode, bad)


@pytest.mark.parametrize("path", PRESETS_SHIPPED, ids=lambda p: p.stem)
def test_preset_fonts_are_shipped(path):
    """Each role names a family with weights; a non-system family has a woff2 per weight."""
    fonts = yaml.safe_load(path.read_text("utf-8"))["fonts"]
    missing = []
    for role in ROLES:
        entry = fonts.get(role)
        assert isinstance(entry, dict), "%s: use the nested form {family, weights, fallback}" % role
        assert entry.get("family") and entry.get("fallback"), role
        weights = entry.get("weights")
        assert isinstance(weights, list) and weights and all(isinstance(w, int) for w in weights), role
        if entry.get("system_only"):
            continue
        for w in weights:
            f = ASSETS / "fonts" / ("%s-latin-%d-normal.woff2" % (_slugify(entry["family"]), w))
            if not f.exists():
                missing.append(f.name)
    assert not missing, "font files not shipped: %s" % missing


def test_exactly_one_default():
    defaults = [p.stem for p in PRESETS_SHIPPED
                if yaml.safe_load(p.read_text("utf-8")).get("default") is True]
    assert len(defaults) == 1, defaults


def test_template_is_not_a_default():
    assert TEMPLATE.get("default") is False


def test_every_shipped_font_has_a_license():
    families = {f.name.split("-latin-")[0] for f in (ASSETS / "fonts").glob("*.woff2")}
    licenses = {f.name[len("LICENSE-"):-len(".txt")] for f in (ASSETS / "fonts").glob("LICENSE-*.txt")}
    assert families and families <= licenses, sorted(families - licenses)


def test_fonts_css_points_at_shipped_woff2():
    css = (ASSETS / "fonts.css").read_text("utf-8")
    refs = re.findall(r'url\("fonts/([^"]+)"\)', css)
    assert refs and all(r.endswith(".woff2") for r in refs)
    assert all((ASSETS / "fonts" / r).exists() for r in refs)
    assert not list((ASSETS / "fonts").glob("*.woff")), "only woff2 ships"
