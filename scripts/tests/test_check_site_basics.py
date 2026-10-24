#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for scripts/check-site-basics.py, the site's house rules.

The Pages site under docs/ is hand authored with no build step, so every rule
the rest of the repo gets from a generator or a schema has to be held by a
check here instead: each page names its canonical URL and sits in the
sitemap, the bilingual pages say so to link previews, the palette the site
wears is the one DESIGN.md declares, and no schema `$id` points at a Pages
address that answers 404.

Two layers, as elsewhere in this directory. The live test runs the checker on
the real tree. The fixture tests build a small fake repo per rule and break it
one way at a time, so a green live run is not the only evidence the checker
reads anything.

Run: python3 -m pytest scripts/tests/test_check_site_basics.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import textwrap

REPO = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "check_site_basics", REPO / "scripts" / "check-site-basics.py"
)
assert _spec and _spec.loader, "cannot load scripts/check-site-basics.py"
csb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csb)

SITE = csb.SITE


def page(name: str, *, canonical: bool = True, locale: bool = True, bilingual: bool = True) -> str:
    url = SITE if name == "index.html" else SITE + name
    head = [f'<meta property="og:url" content="{url}">']
    if canonical:
        head.append(f'<link rel="canonical" href="{url}">')
    if locale:
        head.append('<meta property="og:locale" content="en_US">')
        head.append('<meta property="og:locale:alternate" content="de_DE">')
    body = '<p data-lang="en">Hi</p><p data-lang="de">Hallo</p>' if bilingual else "<p>Hi</p>"
    return "<!DOCTYPE html><html><head>" + "".join(head) + "</head><body>" + body + "</body></html>"


NOT_FOUND = (
    '<!DOCTYPE html><html><head><base href="/open-bridge/">'
    '<meta name="robots" content="noindex"></head>'
    '<body><a href="index.html">Home</a></body></html>'
)

DESIGN = textwrap.dedent(
    """\
    ---
    name: demo
    colors:
      primary: "#111111"
    site:
      stylesheet: docs/assets/brand.css
      fonts:
        display: Playfair Display
        body: Inter
      colors:
        ink: "#0F2A4A"
        surface: "#FAF7F3"
      colorsDark:
        ink: "#E7EAEE"
        surface: "#101419"
    ---

    # Demo
    """
)

BRAND = textwrap.dedent(
    """\
    :root{ --ink:#999999; --surface:#FFFFFF; }
    /* Site palette. Source: DESIGN.md `site:` */
    @font-face{font-family:"Inter";src:url("fonts/i.woff2")}
    @font-face{font-family:"Playfair Display";src:url("fonts/p.woff2")}
    :root{
      --ink:#0F2A4A; --surface:#FAF7F3;
      --shadow-soft:none;
      --font-display:"Playfair Display",Georgia,serif;
    }
    html.dark{
      --ink:#E7EAEE; --surface:#101419;
    }
    """
)


def sitemap(*names: str) -> str:
    locs = "".join(f"<url><loc>{SITE if n == 'index.html' else SITE + n}</loc></url>" for n in names)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'


def build(tmp: pathlib.Path, **override: str) -> pathlib.Path:
    """A minimal repo that passes every rule; `override` replaces files by relative path."""
    files = {
        "docs/index.html": page("index.html"),
        "docs/demo.html": page("demo.html"),
        "docs/cockpit.html": page("cockpit.html", canonical=False),
        "docs/404.html": NOT_FOUND,
        "docs/sitemap.xml": sitemap("index.html", "demo.html", "cockpit.html"),
        "docs/robots.txt": f"User-agent: *\nSitemap: {SITE}sitemap.xml\n",
        "docs/assets/brand.css": BRAND,
        "DESIGN.md": DESIGN,
        "infra/things/_schema.yaml": '$schema: "https://json-schema.org/draft/2020-12/schema"\n$id: "urn:open-bridge:schema:thing"\n',
    }
    files.update(override)
    for rel, text in files.items():
        if text is None:
            continue
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


def problems(root: pathlib.Path) -> list[str]:
    return csb.collect(root)


# ---- live -------------------------------------------------------------------

def test_live_tree_is_clean():
    assert csb.collect(REPO) == []


# ---- fixture: the baseline passes -------------------------------------------

def test_fixture_baseline_passes(tmp_path):
    assert problems(build(tmp_path)) == []


# ---- canonical ----------------------------------------------------------------

def test_page_without_canonical_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/demo.html": page("demo.html", canonical=False)})
    assert any("demo.html" in p and "canonical" in p for p in problems(root))


def test_canonical_must_match_page_url(tmp_path):
    wrong = page("demo.html").replace(f'rel="canonical" href="{SITE}demo.html"', f'rel="canonical" href="{SITE}other.html"')
    root = build(tmp_path, **{"docs/demo.html": wrong})
    assert any("demo.html" in p and "canonical" in p for p in problems(root))


def test_cockpit_pages_are_exempt_from_canonical_only(tmp_path):
    root = build(tmp_path, **{"docs/sitemap.xml": sitemap("index.html", "demo.html")})
    found = problems(root)
    assert any("cockpit.html" in p and "sitemap" in p for p in found)
    assert not any("cockpit.html" in p and "canonical" in p for p in found)


# ---- sitemap ------------------------------------------------------------------

def test_page_missing_from_sitemap_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/sitemap.xml": sitemap("index.html", "cockpit.html")})
    assert any("demo.html" in p and "sitemap" in p for p in problems(root))


def test_sitemap_entry_without_page_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/sitemap.xml": sitemap("index.html", "demo.html", "cockpit.html", "gone.html")})
    assert any("gone.html" in p for p in problems(root))


def test_404_must_not_be_in_sitemap(tmp_path):
    root = build(tmp_path, **{"docs/sitemap.xml": sitemap("index.html", "demo.html", "cockpit.html", "404.html")})
    assert any("404.html" in p for p in problems(root))


def test_missing_sitemap_is_reported(tmp_path):
    root = build(tmp_path)
    (root / "docs/sitemap.xml").unlink()
    assert any("sitemap.xml" in p for p in problems(root))


# ---- robots, 404 ------------------------------------------------------------

def test_robots_must_name_the_sitemap(tmp_path):
    root = build(tmp_path, **{"docs/robots.txt": "User-agent: *\n"})
    assert any("robots.txt" in p for p in problems(root))


def test_404_needs_a_way_back_noindex_and_a_base(tmp_path):
    for broken in (
        NOT_FOUND.replace('<a href="index.html">Home</a>', ""),
        NOT_FOUND.replace('<meta name="robots" content="noindex">', ""),
        NOT_FOUND.replace('<base href="/open-bridge/">', ""),
    ):
        root = build(tmp_path, **{"docs/404.html": broken})
        assert any("404.html" in p for p in problems(root)), broken


# ---- locale -------------------------------------------------------------------

def test_bilingual_page_without_og_locale_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/demo.html": page("demo.html", locale=False)})
    assert any("demo.html" in p and "og:locale" in p for p in problems(root))


def test_english_only_page_needs_no_alternate(tmp_path):
    only_en = page("demo.html", bilingual=False).replace(
        '<meta property="og:locale:alternate" content="de_DE">', "")
    root = build(tmp_path, **{"docs/demo.html": only_en})
    assert problems(root) == []


# ---- DESIGN.md site block ---------------------------------------------------

def test_design_value_drift_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/assets/brand.css": BRAND.replace("--ink:#0F2A4A", "--ink:#0F2A4B")})
    assert any("--ink" in p for p in problems(root))


def test_dark_value_drift_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/assets/brand.css": BRAND.replace("--surface:#101419", "--surface:#000000")})
    assert any("--surface" in p and "dark" in p for p in problems(root))


def test_token_only_in_css_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/assets/brand.css": BRAND.replace("--surface:#FAF7F3;", "--surface:#FAF7F3; --extra:#123456;")})
    assert any("--extra" in p for p in problems(root))


def test_violet_layer_before_the_marker_is_not_read(tmp_path):
    # The first :root (#999999) is the CORE default layer and owned by the
    # top-level `colors:` block, not by `site:`.
    assert problems(build(tmp_path)) == []


def test_font_drift_is_reported(tmp_path):
    root = build(tmp_path, **{"DESIGN.md": DESIGN.replace("display: Playfair Display", "display: Lora")})
    assert any("font" in p.lower() for p in problems(root))


def test_missing_site_block_is_reported(tmp_path):
    root = build(tmp_path, **{"DESIGN.md": "---\nname: demo\n---\n"})
    assert any("site" in p for p in problems(root))


def test_missing_marker_is_reported(tmp_path):
    root = build(tmp_path, **{"docs/assets/brand.css": BRAND.replace("Source: DESIGN.md `site:`", "")})
    assert any("brand.css" in p for p in problems(root))


# ---- schema $id ---------------------------------------------------------------

def test_schema_id_on_a_pages_url_without_file_is_reported(tmp_path):
    root = build(tmp_path, **{"infra/things/_schema.yaml": f'$id: "{SITE}schemas/thing.yaml"\n'})
    assert any("$id" in p and "thing.yaml" in p for p in problems(root))


def test_schema_id_on_a_pages_url_with_file_passes(tmp_path):
    root = build(tmp_path, **{
        "infra/things/_schema.yaml": f'$id: "{SITE}schemas/thing.yaml"\n',
        "docs/schemas/thing.yaml": "type: object\n",
    })
    assert problems(root) == []


def test_duplicate_schema_id_is_reported(tmp_path):
    root = build(tmp_path, **{"infra/other/_schema.yaml": '$id: "urn:open-bridge:schema:thing"\n'})
    assert any("urn:open-bridge:schema:thing" in p for p in problems(root))


def test_nested_id_is_not_a_root_id(tmp_path):
    nested = '$id: "urn:open-bridge:schema:thing"\n$defs:\n  x:\n    $id: "urn:open-bridge:schema:thing"\n'
    root = build(tmp_path, **{"infra/things/_schema.yaml": nested})
    assert problems(root) == []
