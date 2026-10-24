"""embed-fonts.py turns a font list from DESIGN.md or a preset into a base64 @font-face block."""
from __future__ import annotations

import base64
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[1]
SCRIPT = SKILL / "scripts" / "embed-fonts.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fonts"


def _load():
    spec = importlib.util.spec_from_file_location("embed_fonts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["embed_fonts"] = mod
    spec.loader.exec_module(mod)
    return mod


def _faces(css: str) -> list[dict]:
    """Parse every @font-face rule into {family, weight, display, range, bytes}."""
    out = []
    for body in re.findall(r"@font-face\s*\{(.*?)\}", css, re.S):
        def get(prop):
            m = re.search(prop + r"\s*:\s*([^;]+);", body)
            return m.group(1).strip() if m else None
        b64 = re.search(r"base64,([A-Za-z0-9+/=]+)", body)
        out.append({
            "family": (get("font-family") or "").strip("\"'"),
            "weight": get("font-weight"),
            "display": get("font-display"),
            "range": get("unicode-range"),
            "bytes": base64.b64decode(b64.group(1)) if b64 else b"",
        })
    return out


def _covers(face: dict, weight: int) -> bool:
    parts = [int(p) for p in face["weight"].split()]
    return parts[0] <= weight <= parts[-1]


def test_inter_400_and_600_are_both_covered():
    mod = _load()
    css = mod.build_font_face_css({"Inter": [400, 600]}, [])
    faces = [f for f in _faces(css) if f["family"] == "Inter"]
    assert faces
    for w in (400, 600):
        assert any(_covers(f, w) for f in faces), w
    for f in faces:
        assert f["bytes"][:4] == b"wOF2"
        assert f["display"] == "swap"
        assert "format(\"woff2\")" in css
        assert f["range"] and f["range"].startswith("U+")


def test_static_weights_become_one_face_each():
    mod = _load()
    css = mod.build_font_face_css({"Fixture Sans": [400, 600]}, [FIXTURES])
    faces = _faces(css)
    assert sorted(f["weight"] for f in faces) == ["400", "600"]
    assert faces[0]["bytes"] != faces[1]["bytes"]


def test_variable_font_is_embedded_once_for_many_weights():
    mod = _load()
    css = mod.build_font_face_css({"Fixture Var": [300, 400, 700]}, [FIXTURES])
    faces = _faces(css)
    assert len(faces) == 1
    assert faces[0]["weight"] == "100 900"


def test_missing_weight_warns_and_skips(capsys):
    mod = _load()
    css = mod.build_font_face_css({"Fixture Sans": [400, 800]}, [FIXTURES])
    err = capsys.readouterr().err
    assert "800" in err and "Fixture Sans" in err
    assert [f["weight"] for f in _faces(css)] == ["400"]


def test_unknown_family_warns_and_emits_nothing(capsys):
    mod = _load()
    css = mod.build_font_face_css({"No Such Family": [400]}, [])
    assert "No Such Family" in capsys.readouterr().err
    assert "@font-face" not in css


def test_font_dir_overrides_bundled_family(tmp_path):
    mod = _load()
    bundled = _faces(mod.build_font_face_css({"Inter": [400]}, []))[0]["bytes"]
    (tmp_path / "inter-latin-400.woff2").write_bytes((FIXTURES / "fixture-sans-latin-400.woff2").read_bytes())
    css = mod.build_font_face_css({"Inter": [400]}, [tmp_path])
    assert _faces(css)[0]["bytes"] != bundled


def test_no_google_fonts_and_no_external_urls():
    mod = _load()
    css = mod.build_font_face_css({"Inter": [400], "Playfair Display": [500]}, [])
    assert "fonts.googleapis" not in css and "fonts.gstatic" not in css
    assert not re.search(r"url\((?!data:)", css)


def test_families_from_design_md(tmp_path):
    mod = _load()
    design = tmp_path / "DESIGN.md"
    design.write_text(
        "---\nname: t\ntypography:\n"
        "  display:\n    fontFamily: Playfair Display\n    fontWeight: 500\n"
        "  body-md:\n    fontFamily: \"Inter, system-ui, sans-serif\"\n    fontWeight: 400\n"
        "  h3:\n    fontFamily: Inter\n    fontWeight: 600\n"
        "---\n# body\n", encoding="utf-8")
    fams = mod.collect_families(design)
    assert fams == {"Playfair Display": [500], "Inter": [400, 600]}


def test_families_from_repo_design_md():
    mod = _load()
    fams = mod.collect_families(REPO / "DESIGN.md")
    assert "Inter" in fams
    assert all(w == int(w) for ws in fams.values() for w in ws)


def test_preset_flat_entries_use_fonts_weights(tmp_path):
    mod = _load()
    preset = tmp_path / "p.yaml"
    preset.write_text(
        "fonts:\n  display: Inter\n  body: Inter\n  mono: Fixture Sans\n  weights: [400, 600, 700]\n",
        encoding="utf-8")
    fams = mod.collect_families(preset)
    assert fams == {"Inter": [400, 600, 700], "Fixture Sans": [400, 600, 700]}


def test_preset_nested_entries_keep_their_own_weights(tmp_path):
    mod = _load()
    preset = tmp_path / "p.yaml"
    preset.write_text(
        "fonts:\n  display:\n    family: Playfair Display\n    weights: [500]\n"
        "  body: Inter\n  weights: [400, 600]\n", encoding="utf-8")
    fams = mod.collect_families(preset)
    assert fams == {"Playfair Display": [500], "Inter": [400, 600]}


def test_preset_system_only_yields_nothing(tmp_path):
    mod = _load()
    preset = tmp_path / "p.yaml"
    preset.write_text("fonts:\n  system_only: true\n  display: Menlo\n", encoding="utf-8")
    assert mod.collect_families(preset) == {}


def test_cli_prints_css_and_warns_on_stderr(tmp_path):
    preset = tmp_path / "p.yaml"
    preset.write_text("fonts:\n  body: Fixture Sans\n  weights: [400, 900]\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(preset), "--font-dir", str(FIXTURES)],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.count("@font-face") == 1
    assert "900" in r.stderr
    strict = subprocess.run([sys.executable, str(SCRIPT), str(preset), "--font-dir", str(FIXTURES),
                             "--strict"], capture_output=True, text=True)
    assert strict.returncode != 0


def test_cli_style_flag_wraps_in_style_tag():
    r = subprocess.run([sys.executable, str(SCRIPT), str(REPO / "DESIGN.md"), "--style"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.lstrip().startswith("<style>") and r.stdout.rstrip().endswith("</style>")


def test_every_bundled_family_ships_its_license():
    fonts = SKILL / "assets" / "fonts"
    assert (fonts / "OFL-inter.txt").read_text("utf-8").count("SIL OPEN FONT LICENSE") >= 1
    assert (fonts / "OFL-playfair-display.txt").exists()
    for woff in fonts.glob("*.woff2"):
        assert woff.read_bytes()[:4] == b"wOF2"


def test_embedded_page_loads_font_from_empty_dir(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    mod = _load()
    css = mod.build_font_face_css({"Fixture Sans": [400, 600], "Inter": [400]}, [FIXTURES])
    page_file = tmp_path / "page.html"
    page_file.write_text(
        "<!doctype html><html><head><meta charset=\"utf-8\"><style>" + css + "</style></head>"
        "<body style=\"font-family:'Fixture Sans'\"><p>abc</p></body></html>", encoding="utf-8")
    assert [p.name for p in tmp_path.iterdir()] == ["page.html"]
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:  # no chromium installed
            pytest.skip(f"chromium unavailable: {exc}")
        try:
            page = browser.new_page(viewport={"width": 800, "height": 600})
            errors = []
            page.on("requestfailed", lambda r: errors.append(r.url))
            page.goto(page_file.as_uri())
            result = page.evaluate("""async () => {
                const out = {};
                for (const spec of ['400 16px "Fixture Sans"', '600 16px "Fixture Sans"',
                                    '400 16px "Inter"', '400 16px "Never Declared"']) {
                    const faces = await document.fonts.load(spec, 'abc');
                    out[spec] = faces.map(f => f.status);
                }
                out.check = document.fonts.check('600 16px "Fixture Sans"');
                return out;
            }""")
            assert result['400 16px "Fixture Sans"'] == ["loaded"]
            assert result['600 16px "Fixture Sans"'] == ["loaded"]
            assert result['400 16px "Inter"'] == ["loaded"]
            assert result['400 16px "Never Declared"'] == []
            assert result["check"] is True
            assert not errors
        finally:
            browser.close()
