#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a single-file html-canvas PAGE from the section catalog, or bring one up to date.

    python3 skills/html-canvas/scripts/new-page.py \
        --title "Option review" --lang de --blocks doc-header,decision-page,callout \
        --out work/tasks/<slug>/deliverables/review.html

Takes assets/shell.html (theme toggle, DE/EN toggle, print), the brand tokens of
the design that applies (design-to-css.py; --design, a DESIGN.md of the repository
the page is written into, --context, --persona, the theme's design, else the
instance's DESIGN.md, see bridge_design.py) and assets/sections.css, and writes ONE
offline file: the example markup of every requested block from references/sections.md
inside <main>, and the CSS of those blocks (plus whatever they require) once, in a
marked region. Then it runs verify-page.py (static) on the result and exits non-zero
when that finds errors.

The page owns three marked regions inside its <style>, and only these are ever rewritten:

    /* design-tokens:begin */ ... /* design-tokens:end */   tokens from DESIGN.md
    /* page-fonts:begin */    ... /* page-fonts:end */      base64 @font-face, opt in
    /* sections:begin */      ... /* sections:end */        the CSS of the chosen blocks

    python3 skills/html-canvas/scripts/new-page.py --refresh review.html

Blocks with a behaviour (glossary, toc, alt-table, print) also bring their part of
assets/sections.js, in a fourth region inside a <script> at the end of <body>:

    /* section-scripts:begin */ ... /* section-scripts:end */  the script of the chosen blocks

It exists only on a page that needs it. A glossary always lands at the end of <main>,
and a toc lists the blocks that follow it.

re-renders those regions (and normalises the DE/EN swap rules, old or new form, to the
one pair the shell ships), leaves <main> and every hand-written rule alone, and does
nothing on a page that is already current. --blocks on a refresh swaps the block set.

--list shows the block names. --blocks all takes the whole catalog.
"""
from __future__ import annotations

import argparse
import datetime
import html
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
ASSETS = SKILL / "assets"
SECTIONS_MD = SKILL / "references" / "sections.md"

TOKENS = "design-tokens"
FONTS = "page-fonts"
SECTIONS = "sections"
SCRIPTS = "section-scripts"

HEADER_BLOCKS = ("doc-header", "hero")
UNWRAPPED = HEADER_BLOCKS + ("section-nav",)
LAST_BLOCKS = ("glossary",)     # placed at the end of <main>, whatever the order asked for

# Nav labels, de / en. Short on purpose: they name a block on a scaffold page.
LABELS = {
    "doc-header": ("Kopf", "Header"), "hero": ("Einstieg", "Hero"),
    "section-opener": ("Abschnitt", "Section"), "pipeline": ("Ablauf", "Pipeline"),
    "swimlane": ("Bahnen", "Swimlane"), "c4-boxes": ("Architektur", "Architecture"),
    "ladder": ("Ebenen", "Levels"), "svg-diagram": ("Diagramm", "Diagram"),
    "message-flow": ("Nachrichtenfluss", "Message flow"), "kpi-row": ("Kennzahlen", "Metrics"),
    "matrix": ("Matrix", "Matrix"), "kanban": ("Board", "Board"), "table": ("Tabelle", "Table"),
    "bar-chart": ("Balken", "Bars"), "timeline": ("Zeitleiste", "Timeline"),
    "decision-page": ("Entscheidung", "Decision"), "spec-card": ("Steckbrief", "Spec card"),
    "callout": ("Hinweis", "Note"), "not-vs-is": ("Abgrenzung", "Contrast"),
    "chips": ("Tags", "Tags"), "people": ("Personen", "People"), "terminal": ("Terminal", "Terminal"),
    "collapsible": ("Details", "Details"), "legend": ("Legende", "Legend"), "index": ("Index", "Index"),
    "glossary": ("Glossar", "Glossary"), "toc": ("Inhalt", "Contents"),
    "alt-table": ("Grafik und Tabelle", "Chart and table"), "print": ("Druck", "Print"),
}

# The shell's DE/EN swap, in the two spellings a page can carry. The pair-safe form
# (an element with BOTH attributes is never hidden) is the one written.
SWAP_LINE = (r':root(?::not\(\[data-lang="(?:de|en)"\]\)|\[data-lang="(?:de|en)"\])\s*'
             r'\[data-(?:de|en)\](?::not\(\[data-(?:de|en)\]\))?\{display:none\}')
SWAP_PAIR = re.compile(SWAP_LINE + r"\s*" + SWAP_LINE)
SWAP = {
    "en": (':root:not([data-lang="de"]) [data-de]:not([data-en]){display:none}\n'
           ':root[data-lang="de"] [data-en]:not([data-de]){display:none}'),
    "de": (':root:not([data-lang="en"]) [data-en]:not([data-de]){display:none}\n'
           ':root[data-lang="en"] [data-de]:not([data-en]){display:none}'),
}

CSS_BLOCK = re.compile(r"^/\* @block: ([a-z0-9-]+)(?: requires: ([a-z0-9, -]+))? \*/$", re.M)
JS_BLOCK = re.compile(r"^/\* @block: ([a-z0-9-]+) \*/$", re.M)
MD_HEADING = re.compile(r'^## <a id="([a-z0-9-]+)"></a>', re.M)
BLOCKS_LINE = re.compile(r"^/\* blocks: (.*?) \*/$", re.M)


def fail(msg: str) -> NoReturn:
    sys.stderr.write("new-page: %s\n" % msg)
    sys.exit(1)


def note(msg: str) -> None:
    sys.stderr.write("new-page: %s\n" % msg)


def read(path: Path) -> str:
    if not path.is_file():
        fail("missing file: %s" % path)
    return path.read_text(encoding="utf-8")


def load(filename: str):
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_").removesuffix(".py"), HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the catalog ----------------------------------------------------------------------

def css_blocks() -> dict[str, tuple[list[str], str]]:
    """{name: (requires, section text from its marker line on)} from assets/sections.css."""
    text = read(ASSETS / "sections.css")
    marks = list(CSS_BLOCK.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        reqs = [r.strip() for r in (m.group(2) or "").split(",") if r.strip()]
        out[m.group(1)] = (reqs, text[m.start():end].strip("\n"))
    # the animation layer is its own asset; blocks name it in `requires:` like any other block
    out["animations"] = ([], "/* @block: animations */\n" + read(ASSETS / "animations.css").strip("\n"))
    return out


def catalog() -> list[str]:
    return MD_HEADING.findall(read(SECTIONS_MD))


NO_MARKUP = "*Markup: none.*"


def markup(name: str) -> str:
    """The block's example markup; "" for a block that is rules only (its entry says NO_MARKUP)."""
    text = read(SECTIONS_MD)
    start = text.index('<a id="%s"></a>' % name)
    nxt = text.find("\n## ", start)
    body = text[start: nxt if nxt != -1 else len(text)]
    m = re.search(r"```html\n(.*?)```", body, re.S)
    if not m:
        if NO_MARKUP in body:
            return ""
        fail("sections.md has no html example for block %s" % name)
    return m.group(1).strip("\n")


def parse_blocks(raw: str | None) -> list[str]:
    names = catalog()
    if not raw:
        return []
    wanted = [b for b in re.split(r"[,\s]+", raw.strip()) if b]
    if wanted == ["all"]:
        return names
    unknown = [b for b in wanted if b not in names]
    if unknown:
        fail("unknown block(s): %s (see --list)" % ", ".join(unknown))
    return list(dict.fromkeys(wanted))


def resolve(blocks: list[str]) -> list[str]:
    """Requested blocks plus what they require, dependencies first, each once."""
    table = css_blocks()
    order: list[str] = []

    def walk(name: str) -> None:
        if name in order:
            return
        if name not in table:
            fail("sections.css has no block %s" % name)
        for r in table[name][0]:
            walk(r)
        order.append(name)

    walk("base")
    for b in blocks:
        walk(b)
    return order


def sections_body(blocks: list[str]) -> str:
    table = css_blocks()
    parts = ["/* blocks: %s */" % ", ".join(blocks)]
    for name in resolve(blocks):
        parts.append(table[name][1])
    return "\n\n".join(parts)


def js_blocks() -> dict[str, str]:
    """{name: script text from its marker line on} from assets/sections.js."""
    text = read(ASSETS / "sections.js")
    marks = list(JS_BLOCK.finditer(text))
    return {m.group(1): text[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip("\n")
            for i, m in enumerate(marks)}


def scripts_body(blocks: list[str]) -> str:
    table = js_blocks()
    return "\n\n".join(table[n] for n in resolve(blocks) if n in table)


def apply_scripts(text: str, blocks: list[str]) -> str:
    """Fill the section-scripts region; add it (a <script> before </body>) only when a block needs it."""
    body = scripts_body(blocks)
    if not has_region(text, SCRIPTS):
        if not body:
            return text
        b, e = marker_pair(SCRIPTS)
        i = text.rfind("</body>")
        if i == -1:
            fail("page has no </body> to hold the %s region" % SCRIPTS)
        text = text[:i] + "<script>\n%s\n%s\n</script>\n" % (b, e) + text[i:]
    return set_region(text, SCRIPTS, body)


# --- regions --------------------------------------------------------------------------

def marker_pair(name: str) -> tuple[str, str]:
    return "/* %s:begin */" % name, "/* %s:end */" % name


def has_region(text: str, name: str) -> bool:
    b, e = marker_pair(name)
    return text.count(b) == 1 and text.count(e) == 1 and text.index(b) < text.index(e)


def region_body(text: str, name: str) -> str:
    b, e = marker_pair(name)
    return text.split(b, 1)[1].split(e, 1)[0].strip("\n")


def set_region(text: str, name: str, body: str) -> str:
    b, e = marker_pair(name)
    if not has_region(text, name):
        fail("page needs exactly one %s and one %s marker" % (b, e))
    head, rest = text.split(b, 1)
    tail = rest.split(e, 1)[1]
    inner = "\n" + body.strip("\n") + "\n" if body.strip() else "\n"
    return head + b + inner + e + tail


def ensure_region(text: str, name: str, before: str | None = None) -> str:
    """Add an empty region: ahead of region `before`, else at the end of the last <style> in <head>."""
    if has_region(text, name):
        return text
    b, e = marker_pair(name)
    block = "%s\n%s\n\n" % (b, e)
    if before and has_region(text, before):
        i = text.index(marker_pair(before)[0])
        return text[:i] + block + text[i:]
    head_end = text.find("</head>")
    close = text.rfind("</style>", 0, head_end if head_end != -1 else len(text))
    if close == -1:
        fail("page has no <style> element to hold the %s region" % name)
    return text[:close].rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n" + text[close:]


# --- the steps shared by build and refresh --------------------------------------------

def find_design(start: Path, args=None) -> Path | None:
    """The design the Bridge resolves for a page at `start` (bridge_design.py).

    --design (a path or an id) wins, then a DESIGN.md of the repository the page
    is written into (never the Bridge's own root), --context, --persona, the
    theme's design, and last the instance's own DESIGN.md.
    """
    try:
        return load("bridge_design.py").resolve(
            getattr(args, "design", None), context=getattr(args, "context", None),
            persona=getattr(args, "persona", None), target=start)
    except ValueError as e:
        fail(str(e))


def apply_tokens(text: str, design: Path | None, d2c) -> str:
    if design is None:
        note("no DESIGN.md found, the page keeps its neutral system colours (pass --design)")
        return text
    css, skipped = d2c.build_css(d2c.frontmatter(design))
    if skipped:
        note("DESIGN.md keys not mapped: %s" % ", ".join(skipped))
    try:
        return d2c.inject(text, css)
    except ValueError as e:
        fail(str(e))


def apply_fonts(text: str, design: Path | None, font_dirs: list[Path], d2c, wanted: bool) -> str:
    present = has_region(text, FONTS)
    if not (wanted or (present and region_body(text, FONTS))):
        return text
    if design is None:
        fail("--embed-fonts needs a DESIGN.md (pass --design)")
    text = ensure_region(text, FONTS, before=SECTIONS)
    return set_region(text, FONTS, d2c.font_faces(design, font_dirs))


def apply_swap(text: str) -> str:
    """One DE/EN swap pair, in the form that matches <html lang>; a stray second pair is dropped."""
    m = re.search(r'<html[^>]*\blang="(de|en)"', text)
    lang = m.group(1) if m else "en"
    seen = []

    def one(_m):
        seen.append(1)
        return SWAP[lang] if len(seen) == 1 else ""

    out = SWAP_PAIR.sub(one, text)
    if not seen:
        note("no DE/EN swap rules found, left alone")
    return out


def unescape_symbols(markup_text: str) -> str:
    """&rarr; and friends become the character itself; markup-significant entities stay."""
    def one(m):
        ch = html.unescape(m.group(0))
        return ch if len(ch) == 1 and ord(ch) > 127 else m.group(0)
    return re.sub(r"&#?\w+;", one, markup_text)


# --- building -------------------------------------------------------------------------

def ordered(blocks: list[str]) -> list[str]:
    """The order on the page: as asked, the LAST_BLOCKS moved to the end."""
    return [b for b in blocks if b not in LAST_BLOCKS] + [b for b in blocks if b in LAST_BLOCKS]


def linked(blocks: list[str], after: str | None = None) -> list[str]:
    """Blocks a nav or toc links to: wrapped, with markup, and (for a toc) after it."""
    out = [b for b in ordered(blocks) if b not in UNWRAPPED and b != "toc" and markup(b)]
    if after and after in blocks:
        order = ordered(blocks)
        out = [b for b in out if order.index(b) > order.index(after)]
    return out


def label(b: str) -> str:
    de, en = LABELS.get(b, (b, b))
    return '<a href="#blk-%s"><span data-de>%s</span><span data-en>%s</span></a>' % (b, de, en)


def nav(blocks: list[str]) -> str:
    links = ["  " + label(b) for b in linked(blocks)]
    return '<nav class="secnav">\n%s\n</nav>' % "\n".join(links)


def toc_list(blocks: list[str]) -> str:
    items = ["    <li>%s</li>" % label(b) for b in linked(blocks, after="toc")]
    return "<ol>\n%s\n  </ol>" % "\n".join(items) if items else "<ol></ol>"


def main_html(blocks: list[str], title_de: str, title_en: str) -> str:
    title_h1 = "<span data-de>%s</span><span data-en>%s</span>" % (title_de, title_en)
    parts = []
    headerish = [b for b in blocks if b in HEADER_BLOCKS]
    if not headerish:
        parts.append("<h1>%s</h1>" % title_h1)
    titled = False
    for b in ordered(blocks):
        body = unescape_symbols(markup(b))
        if not body:
            continue
        if b == "section-nav":
            parts.append(nav(blocks))
            continue
        if b == "toc":
            body = re.sub(r"<ol>.*?</ol>", lambda _: toc_list(blocks), body, count=1, flags=re.S)
        if b in HEADER_BLOCKS:
            if not titled:
                body = re.sub(r"(<h1[^>]*>).*?(</h1>)", lambda m: m.group(1) + title_h1 + m.group(2), body,
                              count=1, flags=re.S)
                titled = True
            parts.append(re.sub(r"^(<[a-z][a-z0-9]*\b)", r"\1 data-sample", body, count=1))
            continue
        parts.append('<div class="blk" id="blk-%s" data-sample>\n%s\n</div>' % (b, body))
    return '<main class="wrap">\n\n' + "\n\n".join(parts) + "\n\n</main>"


def build(args, design: Path | None, d2c) -> str:
    text = read(ASSETS / "shell.html")
    blocks = parse_blocks(args.blocks)
    title = html.escape(args.title, quote=False)
    title_de = html.escape(args.title_de, quote=False) if args.title_de else title
    title_en = html.escape(args.title_en, quote=False) if args.title_en else title
    date = args.date or datetime.date.today().isoformat()
    source = html.escape(args.footer or "html-canvas / new-page", quote=False)

    if args.lang == "de":
        text = text.replace('<html lang="en" class="">', '<html lang="de" class="">', 1)
        text = text.replace("|| 'en')", "|| 'de')").replace("'data-lang', 'en')", "'data-lang', 'de')")
    text = apply_swap(text)

    text = text.replace("\n</style>\n</head>",
                        "\n\n%s\n%s\n\n%s\n%s\n</style>\n</head>"
                        % (*marker_pair(FONTS), *marker_pair(SECTIONS)), 1)
    text = apply_tokens(text, design, d2c)
    text = apply_fonts(text, design, [Path(d) for d in args.font_dir], d2c, args.embed_fonts)
    text = set_region(text, SECTIONS, sections_body(blocks))
    text = apply_scripts(text, blocks)

    m = re.search(r'<main class="wrap">.*?</main>', text, re.S)
    if not m:
        fail('no <main class="wrap"> ... </main> block in the shell')
    text = text[: m.start()] + main_html(blocks, title_de, title_en) + text[m.end():]

    page_title = title_en if args.lang == "en" else title_de
    text = text.replace("{{TITLE}}", page_title).replace("{{DATE}}", date).replace("{{SOURCE_PATH}}", source)
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        fail("unfilled placeholders left in the output: %s" % ", ".join(sorted(set(left))))
    return text


def refresh(args, page: Path, design: Path | None, d2c) -> tuple[str, list[str]]:
    original = read(page)
    text = original
    changed = []

    if has_region(text, TOKENS):
        text = apply_tokens(text, design, d2c)
    else:
        note("no %s region, tokens left alone" % TOKENS)

    text = apply_fonts(text, design, [Path(d) for d in args.font_dir], d2c, args.embed_fonts)

    if has_region(text, SECTIONS):
        m = BLOCKS_LINE.search(region_body(text, SECTIONS))
        blocks = parse_blocks(args.blocks) if args.blocks else (
            [b for b in re.split(r",\s*", m.group(1)) if b] if m else None)
        if blocks is None:
            note("sections region records no block list, left alone (pass --blocks)")
        else:
            unknown = [b for b in blocks if b not in catalog()]
            if unknown:
                fail("the page names block(s) the catalog no longer has: %s" % ", ".join(unknown))
            text = set_region(text, SECTIONS, sections_body(blocks))
            text = apply_scripts(text, blocks)
    else:
        note("no %s region, block CSS left alone (this page was not built by new-page.py)" % SECTIONS)

    text = apply_swap(text)

    if text != original:
        for what, name in (("tokens", TOKENS), ("fonts", FONTS), ("sections", SECTIONS), ("scripts", SCRIPTS)):
            if has_region(text, name) and (not has_region(original, name)
                                           or region_body(text, name) != region_body(original, name)):
                changed.append(what)
        if SWAP_PAIR.findall(original) != SWAP_PAIR.findall(text) or not changed:
            changed.append("language swap")
    return text, changed


def run_verify(page: Path, design: Path | None) -> int:
    # A fresh page holds catalog sample text by design; the send gate (verify-page
    # without --allow-sample) is where it has to be gone.
    cmd = [sys.executable, str(HERE / "verify-page.py"), str(page), "--allow-sample"]
    if design:
        cmd += ["--design", str(design)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", help="path of the single-file page to write")
    p.add_argument("--refresh", metavar="PAGE", help="re-render the marked regions of an existing page in place")
    p.add_argument("--blocks", help="section blocks, comma separated (see --list), or 'all'")
    p.add_argument("--title", default="Untitled page", help="title, used for both languages unless overridden")
    p.add_argument("--title-de", dest="title_de")
    p.add_argument("--title-en", dest="title_en")
    p.add_argument("--lang", choices=("de", "en"), default="en", help="default language of the page")
    p.add_argument("--date", help="footer date (default: today)")
    p.add_argument("--footer", help="footer source note")
    p.add_argument("--design", help="DESIGN.md or design id for the tokens (default: the design the Bridge "
                                    "resolves, see bridge_design.py)")
    p.add_argument("--context", help="workflow/contexts/<name>.yaml whose design_ref the page wears")
    p.add_argument("--persona", help="identity/personas/<id>.yaml whose design_ref the page wears")
    p.add_argument("--embed-fonts", action="store_true",
                   help="embed the DESIGN.md font families as base64 @font-face (off by default)")
    p.add_argument("--font-dir", action="append", default=[], metavar="DIR",
                   help="with --embed-fonts: extra directory of <family>-latin-<weight>.woff2 files")
    p.add_argument("--list", action="store_true", help="list the section blocks and exit")
    p.add_argument("--force", action="store_true", help="overwrite an existing output file")
    args = p.parse_args()

    if args.list:
        table = css_blocks()
        print("blocks:")
        for name in catalog():
            req = [r for r in table.get(name, ([], ""))[0]]
            print("  %-15s%s" % (name, ("  (needs %s)" % ", ".join(req)) if req else ""))
        return 0
    if args.font_dir and not args.embed_fonts:
        p.error("--font-dir needs --embed-fonts")
    if args.refresh and args.out:
        p.error("--refresh works in place; drop --out")
    if not args.refresh and not args.out:
        fail("--out is required (or --refresh PAGE, or --list)")

    d2c = load("design-to-css.py")
    if args.refresh:
        page = Path(args.refresh)
        if not page.is_file():
            fail("no such page: %s" % page)
        design = find_design(page.parent, args)
        if design and not design.is_file():
            fail("--design: %s not found" % design)
        text, changed = refresh(args, page, design, d2c)
        if changed:
            page.write_text(text, encoding="utf-8")
            print("refreshed %s (%s)" % (page, ", ".join(changed)))
        else:
            print("%s is already current" % page)
        return 1 if run_verify(page, design) else 0

    dest = Path(args.out)
    if dest.exists() and not args.force:
        fail("%s exists; pass --force to overwrite" % dest)
    design = find_design(dest.parent, args)
    if design and not design.is_file():
        fail("--design: %s not found" % design)
    text = build(args, design, d2c)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print("wrote %s (%d bytes, default lang %s)" % (dest, len(text.encode("utf-8")), args.lang))
    return 1 if run_verify(dest, design) else 0


if __name__ == "__main__":
    sys.exit(main())
