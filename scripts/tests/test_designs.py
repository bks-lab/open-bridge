#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Contract for scripts/designs.py: which design a piece of work wears.

A Bridge holds a default design (the root `DESIGN.md`) and any number of
further ones under `identity/designs/<id>.md`. Contexts and personas point at
one with `design_ref:`, the active theme with `branding.design:`. The resolver
walks six steps and the first that answers wins:

    1 --design <id|path>      2 a target repo with its own DESIGN.md
    3 context design_ref      4 persona design_ref
    5 theme branding.design   6 the root DESIGN.md

An id nobody declared is an error that names the file pointing at it, never a
quiet fall back to the root: a page in the wrong brand looks plausible.

Every test builds a synthetic Bridge in tmp_path, so the file runs the same in
any clone, open-bridge included.

Run: python3 -m pytest scripts/tests/test_designs.py -q
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "designs.py"

_spec = importlib.util.spec_from_file_location("designs", SCRIPT)
designs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(designs)


def design_md(name: str, colors: dict, *, scope: str | None = "user", extra: str = "", prose: str = "") -> str:
    lines = ["---", "version: alpha"]
    if scope:
        lines.append(f"scope: {scope}")
    lines += [f"name: {name}", f"description: The {name} brand."]
    if extra:
        lines.append(extra.rstrip("\n"))
    lines.append("colors:")
    lines += [f'  {k}: "{v}"' for k, v in colors.items()]
    lines += ["---", f"# {name}", "", prose]
    return "\n".join(lines) + "\n"


@pytest.fixture
def bridge(tmp_path):
    """A Bridge with a root DESIGN.md, three designs, and nothing pointing at them yet."""
    root = tmp_path / "bridge"
    (root / ".git").mkdir(parents=True)

    def write(rel: str, text: str) -> Path:
        return put(root, rel, text)

    write("DESIGN.md", design_md("default", {"primary": "#111111"}, scope=None))
    for name, hexv in (("ctx-brand", "#222222"), ("persona-brand", "#333333"),
                       ("theme-brand", "#444444"), ("picked", "#555555")):
        write(f"identity/designs/{name}.md", design_md(name, {"primary": hexv}))
    write("themes/professional.yaml", "schema_version: 1\nmeta: {name: professional, display_name: P, description: d}\n")
    return root


def put(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def rel(res, root):
    return res.path.relative_to(root).as_posix() if res.path else None


# --- resolution order ---------------------------------------------------------------------

def test_an_empty_family_resolves_to_the_root(bridge):
    res = designs.resolve(bridge)
    assert (res.id, rel(res, bridge), res.step) == (None, "DESIGN.md", 6)


def test_theme_beats_the_root(bridge):
    put(bridge, "bridge-config.yaml", "theme: brand\n")
    put(bridge, "themes/brand.yaml", "schema_version: 1\nmeta: {name: brand, display_name: B, description: d}\n"
                                      "branding:\n  design: theme-brand\n")
    res = designs.resolve(bridge)
    assert (res.id, rel(res, bridge), res.step) == ("theme-brand", "identity/designs/theme-brand.md", 5)


def test_theme_branding_is_inherited_through_extends(bridge):
    put(bridge, "bridge-config.yaml", "theme: child\n")
    put(bridge, "themes/parent.yaml", "schema_version: 1\nmeta: {name: parent, display_name: P, description: d}\n"
                                       "branding: {design: theme-brand}\n")
    put(bridge, "themes/child.yaml", "schema_version: 1\nmeta: {name: child, display_name: C, description: d, "
                                      "extends: parent}\nbranding: {label: CHILD}\n")
    assert designs.resolve(bridge).id == "theme-brand"


def test_persona_beats_the_theme(bridge):
    test_theme_beats_the_root(bridge)
    put(bridge, "identity/personas/second.yaml", "schema_version: 1\nid: second\ndesign_ref: persona-brand\n")
    res = designs.resolve(bridge, persona="second")
    assert (res.id, res.step) == ("persona-brand", 4)


def test_context_beats_the_persona(bridge):
    test_persona_beats_the_theme(bridge)
    put(bridge, "workflow/contexts/client.yaml", "id: client\ndesign_ref: ctx-brand\n")
    res = designs.resolve(bridge, context="client", persona="second")
    assert (res.id, res.step) == ("ctx-brand", 3)


def test_a_context_without_a_design_falls_through(bridge):
    put(bridge, "workflow/contexts/plain.yaml", "id: plain\n")
    assert designs.resolve(bridge, context="plain").step == 6


def test_a_target_repo_with_its_own_design_beats_the_context(bridge, tmp_path):
    test_context_beats_the_persona(bridge)
    site = tmp_path / "website"
    (site / ".git").mkdir(parents=True)
    (site / "DESIGN.md").write_text(design_md("site", {"primary": "#666666"}), encoding="utf-8")
    deep = site / "public" / "decks"
    deep.mkdir(parents=True)
    res = designs.resolve(bridge, context="client", persona="second", target=deep / "deck.html")
    assert (res.id, res.path, res.step) == (None, site / "DESIGN.md", 2)


def test_the_bridge_root_never_counts_as_a_target_repo(bridge):
    test_context_beats_the_persona(bridge)
    inside = bridge / "work" / "tasks" / "x"
    inside.mkdir(parents=True)
    res = designs.resolve(bridge, context="client", target=inside / "page.html")
    assert (res.id, res.step) == ("ctx-brand", 3), (
        "a page written inside the Bridge found the Bridge's own DESIGN.md walking up; "
        "that is step 6, never step 2, or no context or theme could ever brand it"
    )
    assert designs.resolve(bridge, target=inside).step == 5, "inside the Bridge, the theme still answers"


def test_a_target_outside_any_project_is_no_step_two(bridge, tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    (tmp_path / "DESIGN.md").write_text(design_md("stray", {"primary": "#777777"}), encoding="utf-8")
    assert designs.resolve(bridge, target=loose / "page.html").step == 6


def test_explicit_design_beats_everything(bridge, tmp_path):
    test_a_target_repo_with_its_own_design_beats_the_context(bridge, tmp_path)
    res = designs.resolve(bridge, design="picked", context="client", persona="second",
                          target=tmp_path / "website" / "x.html")
    assert (res.id, res.step) == ("picked", 1)
    own = tmp_path / "own.md"
    own.write_text(design_md("own", {"primary": "#888888"}), encoding="utf-8")
    res = designs.resolve(bridge, design=str(own), context="client")
    assert (res.id, res.path, res.step) == (None, own, 1)
    res = designs.resolve(bridge, design=str(bridge / "identity" / "designs" / "picked.md"))
    assert (res.id, res.step) == ("picked", 1), "a path into the family still names its id"


# --- an unknown id is an error that names the file pointing at it --------------------------

@pytest.mark.parametrize("where", ["context", "persona", "theme"])
def test_an_unknown_id_names_the_referencing_file(bridge, where):
    if where == "context":
        put(bridge, "workflow/contexts/client.yaml", "id: client\ndesign_ref: nobody\n")
        call, needle = dict(context="client"), "workflow/contexts/client.yaml"
    elif where == "persona":
        put(bridge, "identity/personas/second.yaml", "id: second\ndesign_ref: nobody\n")
        call, needle = dict(persona="second"), "identity/personas/second.yaml"
    else:
        put(bridge, "bridge-config.yaml", "theme: brand\n")
        put(bridge, "themes/brand.yaml", "meta: {name: brand}\nbranding: {design: nobody}\n")
        call, needle = {}, "themes/brand.yaml"
    with pytest.raises(designs.DesignError) as err:
        designs.resolve(bridge, **call)
    assert "nobody" in str(err.value) and needle in str(err.value), str(err.value)


def test_an_unknown_explicit_design_is_an_error(bridge):
    with pytest.raises(designs.DesignError, match="nobody"):
        designs.resolve(bridge, design="nobody")


@pytest.mark.parametrize("value", ["../DESIGN", "_template", "a/b", ""])
def test_a_ref_that_is_not_an_id_is_an_error(bridge, value):
    put(bridge, "identity/designs/_template.md", design_md("t", {"primary": "#000000"}))
    put(bridge, "workflow/contexts/client.yaml", f"id: client\ndesign_ref: '{value}'\n")
    with pytest.raises(designs.DesignError, match="workflow/contexts/client.yaml"):
        designs.resolve(bridge, context="client")


def test_a_named_context_that_does_not_exist_is_an_error(bridge):
    with pytest.raises(designs.DesignError, match="workflow/contexts/ghost.yaml"):
        designs.resolve(bridge, context="ghost")
    with pytest.raises(designs.DesignError, match="identity/personas/ghost.yaml"):
        designs.resolve(bridge, persona="ghost")


# --- list: the reverse direction, derived and never hand-kept --------------------------------

def test_list_shows_who_points_at_each_design(bridge):
    test_context_beats_the_persona(bridge)
    put(bridge, "identity/designs/team.md", design_md(
        "team", {"primary": "#999999"}, scope="org",
        extra="use_for: [mail, slides]\nsource:\n  repo: example-org/website\n  taken_at: abc1234"))
    put(bridge, "identity/designs/loose.md", design_md("loose", {"primary": "#aaaaaa"}, scope=None))
    rows = {row["id"]: row for row in designs.catalogue(bridge)}
    assert rows["ctx-brand"]["referenced_by"] == ["context client"]
    assert rows["persona-brand"]["referenced_by"] == ["persona second"]
    assert rows["theme-brand"]["referenced_by"] == ["theme brand (active)"]
    assert rows["team"]["scope"] == "org" and rows["team"]["use_for"] == ["mail", "slides"]
    assert rows["team"]["source"] == "example-org/website@abc1234"
    assert rows["loose"]["scope"] == "user (undeclared)"
    assert rows["picked"]["referenced_by"] == []
    assert rows[None]["path"] == "DESIGN.md", "the root design is listed as the default"


def test_list_cli_prints_every_design(bridge):
    proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(bridge), "list"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    for name in ("ctx-brand", "persona-brand", "theme-brand", "picked", "DESIGN.md"):
        assert name in proc.stdout


def test_resolve_cli_prints_the_path_and_the_step(bridge):
    put(bridge, "workflow/contexts/client.yaml", "id: client\ndesign_ref: ctx-brand\n")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(bridge), "resolve", "--context", "client"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split()[0] == "identity/designs/ctx-brand.md"
    assert "step 3" in proc.stdout
    bad = subprocess.run([sys.executable, str(SCRIPT), "--root", str(bridge), "resolve", "--design", "nobody"],
                         capture_output=True, text=True)
    assert bad.returncode == 2 and "nobody" in bad.stderr


# --- check: every colour a render uses is declared by its design -----------------------------

RENDER = """<style>
  :root { --primary: #123456; --line: #FFF; --muted: #abc; --glass: #12345680; }
  #header { color: var(--primary); }
</style>
<a href="#bad">jump</a><p>&#123; entity</p>
"""


def test_check_reports_undeclared_hex_and_expands_short_forms(bridge, tmp_path):
    put(bridge, "identity/designs/brand.md", design_md(
        "brand", {"primary": "#123456", "surface": "#ffffff"},
        prose="The old primary was #abcabc, retired in favour of the current one; prose never declares."))
    page = tmp_path / "render.html"
    page.write_text(RENDER + "<i style='color:#ABCABC'>x</i>\n", encoding="utf-8")
    found = designs.undeclared(page.read_text(encoding="utf-8"),
                               bridge / "identity" / "designs" / "brand.md")
    assert set(found) == {"#aabbcc", "#abcabc"}, found
    assert "#ffffff" not in found, "#FFF is #ffffff, which the design declares"


def test_check_cli_exit_codes(bridge, tmp_path):
    put(bridge, "identity/designs/brand.md", design_md("brand", {"primary": "#123456", "surface": "#ffffff"}))
    clean = tmp_path / "clean.css"
    clean.write_text(":root { --p: #123456; --s: #fff; }\n", encoding="utf-8")
    dirty = tmp_path / "dirty.css"
    dirty.write_text(":root { --p: #123456; --x: #00ff00; }\n", encoding="utf-8")
    base = [sys.executable, str(SCRIPT), "--root", str(bridge), "check"]
    ok = subprocess.run(base + [str(clean), "--design", "brand"], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = subprocess.run(base + [str(dirty), "--design", "brand"], capture_output=True, text=True)
    assert bad.returncode == 1 and "#00ff00" in bad.stdout, bad.stdout


# --- the family's own files ----------------------------------------------------------------

SCHEMA = REPO / "identity" / "designs" / "_schema.yaml"
TEMPLATE = REPO / "identity" / "designs" / "_template.md"


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema.Draft202012Validator(yaml.safe_load(SCHEMA.read_text(encoding="utf-8")))


def test_schema_takes_a_minimal_design(tmp_path):
    path = tmp_path / "minimal.md"
    path.write_text(design_md("minimal", {"primary": "#000000"}), encoding="utf-8")
    assert not list(_validator().iter_errors(designs.front_matter(path)))


@pytest.mark.parametrize("drop", ["name", "colors", "scope", "description"])
def test_schema_refuses_a_design_without_a_required_key(drop):
    fm = {"version": "alpha", "scope": "user", "name": "x", "description": "d", "colors": {"primary": "#000000"}}
    fm.pop(drop)
    assert list(_validator().iter_errors(fm)), f"a design without `{drop}` passed the schema"


def test_schema_holds_use_for_to_its_vocabulary():
    fm = {"version": "alpha", "scope": "user", "name": "x", "description": "d", "colors": {"primary": "#000000"}}
    assert not list(_validator().iter_errors({**fm, "use_for": ["mail", "slides", "cockpit"]}))
    assert list(_validator().iter_errors({**fm, "use_for": ["billboard"]}))
    assert list(_validator().iter_errors({**fm, "source": "a string"}))


def test_the_template_passes_its_own_schema():
    assert TEMPLATE.is_file()
    assert not list(_validator().iter_errors(designs.front_matter(TEMPLATE)))
