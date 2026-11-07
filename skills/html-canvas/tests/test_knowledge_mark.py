"""How a knowledge term looks is the design's choice: a DESIGN.md may carry a
`components.knowledge-term` entry (line style, colour role, thickness, a symbol and
its side), design-to-css turns it into the --kp-* tokens, and a page can still
override it with data-kp-mark on <html>. Without the entry nothing changes: a dashed
accent underline and no symbol."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from canvas_testlib import SCRIPTS
from test_knowledge import DESIGN, PACK, USAGE, build_pack, run

NEW_PAGE = SCRIPTS / "new-page.py"
spec = importlib.util.spec_from_file_location("d2c", SCRIPTS / "design-to-css.py")
d2c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d2c)

HIGHLIGHT_LIGHT, HIGHLIGHT_DARK = "#A3249E", "#D84CFF"


def design_with(tmp_path: Path, component: str, extra_colors: bool = True) -> Path:
    """The token fixture with a highlight role in both modes and a knowledge-term entry."""
    text = DESIGN.read_text("utf-8")
    if extra_colors:
        text = re.sub(r"^colors:\n", "colors:\n  highlight: \"%s\"\n" % HIGHLIGHT_LIGHT, text, count=1, flags=re.M)
        text = re.sub(r"^colorsDark:\n", "colorsDark:\n  highlight: \"%s\"\n" % HIGHLIGHT_DARK, text, count=1, flags=re.M)
    head, sep, body = text.partition("\n---\n")
    head += "\ncomponents:\n  knowledge-term:\n" + "".join("    %s\n" % l for l in component.strip().splitlines())
    out = tmp_path / "DESIGN.md"
    out.write_text(head + sep + body, encoding="utf-8")
    return out


SOLID_BULB = """
underline: solid
underlineColor: "{colors.highlight}"
underlineThickness: 0.12em
icon: bulb
iconColor: "{colors.highlight}"
"""


def tokens(design: Path) -> tuple[dict, dict]:
    css, _ = d2c.build_css(d2c.frontmatter(design))
    groups = {}
    body = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
        groups[sel.strip()] = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", decls))
    return groups[":root"], groups.get("html.dark", {})


# ---------- the generator ----------

def test_without_the_entry_no_knowledge_token_is_written():
    root, dark = tokens(DESIGN)
    assert not [k for k in {**root, **dark} if k.startswith("kp-")]


def test_the_entry_becomes_tokens_in_both_modes(tmp_path):
    root, dark = tokens(design_with(tmp_path, SOLID_BULB))
    assert root["kp-line"] == "solid"
    assert root["kp-line-color"] == HIGHLIGHT_LIGHT and dark["kp-line-color"] == HIGHLIGHT_DARK
    assert root["kp-line-width"] == "0.12em"
    assert root["kp-icon"] == "var(--kp-icon-bulb)"
    assert root["kp-icon-after"] == "inline-block" and root["kp-icon-before"] == "none"
    assert root["kp-icon-paint"] == HIGHLIGHT_LIGHT and dark["kp-icon-paint"] == HIGHLIGHT_DARK


def test_a_glyph_is_written_as_content_and_drawn_unmasked(tmp_path):
    root, _ = tokens(design_with(tmp_path, 'icon: "💡"\niconPosition: before'))
    assert root["kp-glyph"] == '"💡"' and root["kp-icon"] == "none"
    assert root["kp-icon-before"] == "inline-block" and root["kp-icon-after"] == "none"
    assert root["kp-icon-paint"] == "transparent"


@pytest.mark.parametrize("bad", [
    'underlineColor: "#ff00ff"',          # a hand-picked colour, not a role
    'underlineColor: "{colors.nope}"',    # a role the design does not have
    "underline: zigzag",
    "underlineThickness: thick",
    "icon: lamp-and-more-than-four",
    "iconPosition: middle",
    'icon: "a\\nb"',                     # a control character would break the stylesheet
    'icon: "a}b"',
    "bogus: 1",                           # an unknown key
])
def test_a_wrong_value_is_refused_with_its_name(tmp_path, bad):
    design = design_with(tmp_path, bad)
    with pytest.raises(ValueError, match="knowledge-term"):
        d2c.build_css(d2c.frontmatter(design))


# ---------- on the page ----------

def page(tmp_path: Path, design: Path, attr: str = "") -> str:
    out = tmp_path / "page.html"
    r = run(NEW_PAGE, "--out", out, "--design", design, "--blocks", "doc-header,knowledge")
    assert r.returncode == 0, r.stdout + r.stderr
    build_pack(tmp_path)
    assert run(PACK, "embed", out, "--pack", tmp_path / "pack.json").returncode == 0
    html = out.read_text("utf-8").replace('<main class="wrap">', '<main class="wrap">\n' + USAGE, 1)
    if attr:
        html = html.replace("<html ", "<html %s " % attr, 1)
    return html


def look(pg) -> dict:
    return pg.evaluate("""() => { const t = document.querySelector('#usage [data-know="latency"]');
        const s = getComputedStyle(t), a = getComputedStyle(t, '::after'), b = getComputedStyle(t, '::before');
        return {style: s.textDecorationStyle, colour: s.textDecorationColor, width: s.textDecorationThickness,
                after: a.display, afterMask: a.webkitMaskImage || a.maskImage, afterBg: a.backgroundColor,
                before: b.display, beforeContent: b.content}; }""")


def rgb(hexv: str) -> str:
    h = hexv.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def test_the_design_draws_a_solid_line_with_a_bulb(open_page, tmp_path):
    st = look(open_page(page(tmp_path, design_with(tmp_path, SOLID_BULB))))
    assert st["style"] == "solid" and st["colour"] == rgb(HIGHLIGHT_LIGHT), st
    assert st["after"] == "inline-block" and "svg" in st["afterMask"], st
    assert st["afterBg"] == rgb(HIGHLIGHT_LIGHT) and st["before"] == "none", st


def test_the_design_colour_follows_dark_mode(open_page, tmp_path):
    pg = open_page(page(tmp_path, design_with(tmp_path, SOLID_BULB)))
    pg.evaluate("document.documentElement.classList.add('dark')")
    pg.wait_for_timeout(400)  # the colour change is a .15s transition
    assert look(pg)["colour"] == rgb(HIGHLIGHT_DARK)


def test_a_glyph_before_the_term(open_page, tmp_path):
    st = look(open_page(page(tmp_path, design_with(tmp_path, 'icon: "💡"\niconPosition: before'))))
    assert st["before"] == "inline-block" and st["beforeContent"] == '"💡"' and st["after"] == "none", st


def test_the_page_attribute_wins_over_the_design(open_page, tmp_path):
    st = look(open_page(page(tmp_path, design_with(tmp_path, SOLID_BULB), 'data-kp-mark="dashed"')))
    assert st["style"] == "dashed" and st["after"] == "none" and st["before"] == "none", st


def test_the_bulb_is_an_option_on_any_page(open_page, tmp_path):
    st = look(open_page(page(tmp_path, DESIGN, 'data-kp-mark="bulb"')))
    assert st["style"] == "dashed" and st["after"] == "inline-block" and "svg" in st["afterMask"], st


def test_in_a_compound_the_symbol_follows_the_whole_word(open_page, tmp_path):
    html = page(tmp_path, design_with(tmp_path, SOLID_BULB))
    html = html.replace('</main>', '<p id="compound"><span class="kp-nobr"><button type="button" class="kp-term" '
                        'data-know="latency">latency</button>-budget</span> here</p></main>', 1)
    pg = open_page(html)
    st = pg.evaluate("""() => { const w = document.querySelector('#compound .kp-nobr'), t = w.querySelector('.kp-term');
        const r = {term: getComputedStyle(t, '::after').display, word: getComputedStyle(w, '::after').display,
                   withSymbol: w.getBoundingClientRect().width};
        document.documentElement.setAttribute('data-kp-mark', 'dashed');
        r.without = w.getBoundingClientRect().width; return r; }""")
    assert st["term"] == "none" and st["word"] == "inline-block", st
    assert st["withSymbol"] > st["without"] + 5, "the symbol takes room at the end of the word: %s" % st


def test_the_page_attribute_wins_in_dark_mode_too(open_page, tmp_path):
    pg = open_page(page(tmp_path, design_with(tmp_path, SOLID_BULB), 'data-kp-mark="dashed"'))
    pg.evaluate("document.documentElement.classList.add('dark')")
    pg.wait_for_timeout(400)
    st = look(pg)
    assert st["style"] == "dashed" and st["after"] == "none", st
    assert st["colour"] != rgb(HIGHLIGHT_DARK), st


def test_a_disabled_term_has_no_symbol_and_no_design_colour(open_page, tmp_path):
    design = design_with(tmp_path, SOLID_BULB + 'textColor: "{colors.highlight}"')
    pg = open_page(page(tmp_path, design).replace('</main>', '<p id="off">a <button type="button" class="kp-term" '
                   'data-know="no-such-term">ghost</button></p></main>', 1))
    st = pg.evaluate("""() => { const t = document.querySelector('#off .kp-term');
        return {dis: t.getAttribute('aria-disabled'), after: getComputedStyle(t, '::after').content,
                colour: getComputedStyle(t).color, parent: getComputedStyle(t.parentElement).color}; }""")
    assert st["dis"] == "true" and st["after"] == "none" and st["colour"] == st["parent"], st


def test_print_keeps_the_light_colours_and_no_symbol(open_page, tmp_path):
    root, _ = tokens(design_with(tmp_path, SOLID_BULB))
    css, _ = d2c.build_css(d2c.frontmatter(design_with(tmp_path, SOLID_BULB)))
    printed = css[css.index("@media print"):]
    assert "--kp-line-color: %s;" % HIGHLIGHT_LIGHT in printed, printed
    html = page(tmp_path, design_with(tmp_path, SOLID_BULB)).replace('</main>', '<p id="compound"><span class="kp-nobr">'
           '<button type="button" class="kp-term" data-know="latency">latency</button>-budget</span></p></main>', 1)
    pg = open_page(html)
    pg.emulate_media(media="print")
    st = pg.evaluate("""() => { const w = document.querySelector('#compound .kp-nobr');
        return {word: getComputedStyle(w, '::after').content, term: getComputedStyle(w.firstChild, '::after').content}; }""")
    assert st["word"] == "none" and st["term"] == "none", st
