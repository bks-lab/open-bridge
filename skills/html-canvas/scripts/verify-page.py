#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One quality gate for every single-file HTML deliverable, pages and decks.

The rules a deliverable has to meet used to live as prose in the build
checklist, and prose is read once and then trusted. This script turns them into
findings, so "done" means the gate is green, not that somebody remembered.

Static mode (default, stdlib only):
  external-url    a resource (src, link href, url(), @import) on another host
  local-ref       a resource next to the page: it breaks once the file travels alone
  external-link   an <a href> leaving the page (warning: fine for a cited source)
  placeholder     a leftover {{TEMPLATE}} placeholder
  sample          catalog sample text: a block new-page.py marked data-sample, or a
                  text that is only an ellipsis (--allow-sample: warning)
  design-source   the page names the DESIGN.md it was generated from, and the gate
                  reads another (warning)
  entity          an HTML entity or \\u escape spelling a non-ASCII letter (error),
                  or another non-ASCII character (warning); write the character
  hex             a hex colour not declared in the DESIGN.md front matter
  font-face       a family named without @font-face that is no system family
                  (warning: embedding is optional, the stack falls back)
  lang-pair       data-de without its data-en counterpart, or the other way round
  aria-pair       data-<x>-de without data-<x>-en (data-aria-de and friends)
  aria-lang       a static aria-label on a bilingual page, in one language only
  dead-anchor     an in-page #anchor no id or name resolves
  charset         no <meta charset>
  forbidden-char  a character from --forbid-chars / --forbid-chars-from in
                  visible text (off unless the instance passes a list)

--browser (needs playwright + chromium; without them browser-skipped is an
  ERROR, because the pass was asked for and nothing was measured):
  the file is copied ALONE into an empty temp dir and opened via file://, then
  rendered light/dark x de/en where the page supports them, under
  prefers-reduced-motion and as print. Findings: console-error, request-failed,
  network (any request leaving the file), both-languages (the inactive language
  visible), lang-hidden (an element carrying both data-de and data-en, shown in
  neither), contrast (body text under 4.5:1, 3:1 for large text; over a gradient,
  an image or a sibling layer such as a scrim, the ground is read from a
  screenshot with all text hidden; text inside aria-hidden="true" is decoration
  and not measured), code-font (code, kbd, pre or samp set in another family
  than the page's --font-mono, warning; only where the page declares one),
  reduced-motion
  (text left at opacity 0, warning). --out DIR keeps screenshots, >= 500 px wide.
  Dark mode is found where the page keeps it: html.dark, .theme-dark (with
  .theme-light), [data-theme="dark"], or prefers-color-scheme alone; any other
  switch on <html> is named with --dark-selector (.night, [data-mode="night"]).

--deck (implies --browser): every element matching --slide-selector is checked
  for overflow at 1280x720 and 1920x1080 (slide-overflow), the selector must
  match (slide-count), and print must give one page per slide (print-pages).

Output is a human-readable list, or JSON with --json. Exit 1 on any error,
0 with warnings only, 2 on a usage error.

Usage:
  verify-page.py page.html [more.html ...] [--design DESIGN.md] [--json]
  verify-page.py page.html --forbid-chars "<chars>" [--forbid-chars-from FILE]
  verify-page.py page.html --browser [--out shots/] [--width 1280 --width 500]
  verify-page.py page.html --browser --dark-selector .night
  verify-page.py deck.html --deck [--slide-selector .slide]
  # DESIGN.md: --design (a path or a design id), else the nearest one in the
  # page's folder or above, and inside the Bridge the design it resolves;
  # without one the hex check is skipped and the output says so.
"""
from __future__ import annotations

import argparse
import base64
import html
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ERROR, WARNING = "error", "warning"

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}

# Families every platform resolves without an @font-face. A family outside this
# list renders only where it happens to be installed. embed-fonts.py keeps the
# same SYSTEM_FAMILIES (a test holds the two together).
GENERIC_FAMILIES = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif",
    "ui-sans-serif", "ui-monospace", "ui-rounded", "emoji", "math", "fangsong",
    "inherit", "initial", "unset", "revert", "revert-layer",
}
SYSTEM_FAMILIES = {
    "-apple-system", "blinkmacsystemfont", "segoe ui", "segoe ui emoji", "segoe ui symbol",
    "roboto", "helvetica neue", "helvetica", "arial", "georgia", "times new roman", "times",
    "menlo", "monaco", "consolas", "liberation mono", "liberation sans", "liberation serif",
    "sfmono-regular", "sf mono", "sf pro", "sf pro text", "sf pro display", "courier new",
    "courier", "verdana", "tahoma", "trebuchet ms", "noto sans", "noto serif",
    "noto color emoji", "apple color emoji", "ubuntu", "cantarell", "oxygen",
    "dejavu sans", "dejavu sans mono", "dejavu serif", "lucida grande", "cascadia code",
}

# Attributes whose value a reader sees or a screen reader speaks.
VISIBLE_ATTRS = {"title", "alt", "aria-label", "aria-description", "placeholder", "label",
                 "value", "data-de", "data-en"}
PRESENTATION_COLOR_ATTRS = {"fill", "stroke", "stop-color", "flood-color", "lighting-color",
                            "color", "bgcolor"}
SAFE_SCHEMES = {"data", "blob", "about", "javascript", "mailto", "tel"}

HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})(?![0-9a-zA-Z_-])")
JS_HEX_RE = re.compile(r"""(['"`])#([0-9a-fA-F]{3,8})\1""")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}\n]{1,80}\}\}")
ENTITY_RE = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]{1,31});")
ESCAPE_RE = re.compile(r"\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.S)
CSS_IMPORT_RE = re.compile(r"@import\s+(['\"])(.+?)\1")  # the url() form is caught by CSS_URL_RE
CSS_BODY_RE = re.compile(r"\{([^{}]*)\}")
FONT_FACE_RE = re.compile(r"@font-face\s*\{([^}]*)\}", re.I)
FONT_DECL_RE = re.compile(
    r"(?:^|[;{\s])(font-family|--font-(?!size|weight|feature|variation|style|stretch|kerning)[\w-]+)"
    r"\s*:\s*([^;}]*)", re.I)
BILINGUAL_ATTR_RE = re.compile(r"^data-(.+)-(de|en)$")


def blank(text: str, pattern: re.Pattern) -> str:
    """Replace every match with spaces, keeping newlines, so offsets keep their line."""
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def line_at(text: str, offset: int, first_line: int = 1) -> int:
    return first_line + text.count("\n", 0, offset)


def norm_hex(digits: str) -> str | None:
    d = digits.lower()
    if len(d) in (3, 4):
        return "#" + "".join(c * 2 for c in d[:3])
    if len(d) in (6, 8):
        return "#" + d[:6]
    return None


# --- DESIGN.md ---------------------------------------------------------------------------

def bridge_design():
    """bridge_design.py, loaded by path (standard library only)."""
    spec = importlib.util.spec_from_file_location("bridge_design", Path(__file__).resolve().parent / "bridge_design.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_design(start: Path) -> Path | None:
    """The DESIGN.md a page at `start` is checked against, or None (bridge_design.py).

    The nearest DESIGN.md at or above `start`, never above the project root
    (the first folder holding .git or bridge-config.yaml); without one only the
    page's own folder counts. When the walk ends at the Bridge's own DESIGN.md,
    the Bridge resolves its instance default. A page that records the design it
    was built with is checked against that one before this runs (main).
    bridge_design.py needs no PyYAML, and without it the walk alone decides.
    """
    return bridge_design().resolve(target=start, fallback=False)


def declared_hex(design: Path) -> set[str]:
    """Hex values in the front matter only (DESIGN.md, Consumers section).

    The prose names retired values on purpose; counting them as declared would
    let exactly the drift through that this check exists to catch.
    """
    lines = design.read_text(encoding="utf-8", errors="replace").splitlines()
    front: list[str] = []
    if lines and lines[0].strip() == "---":
        for ln in lines[1:]:
            if ln.strip() == "---":
                break
            front.append(ln)
    found = set()
    for m in HEX_RE.finditer("\n".join(front)):
        h = norm_hex(m.group(1))
        if h:
            found.add(h)
    return found


BUILT_FROM_RE = re.compile(r"Generated from DESIGN\.md \(([^,)]+?)(?:,\s*([^)]+?))?\)")


def design_meta(design: Path) -> dict:
    """name and last_updated from the front matter, read without PyYAML."""
    meta, lines = {}, design.read_text(encoding="utf-8", errors="replace").splitlines()
    if lines and lines[0].strip() == "---":
        for ln in lines[1:]:
            if ln.strip() == "---":
                break
            m = re.match(r"(name|last_updated):\s*[\"']?([^\"'#]+?)[\"']?\s*(?:#.*)?$", ln)
            if m:
                meta[m.group(1)] = m.group(2).strip()
    return meta


def check_design_source(raw: str, rep: Report) -> None:
    """A page names the DESIGN.md it was generated from; warn when the gate reads another.

    Checking a deck against the wrong DESIGN.md reports its own tokens as stray hex
    values, which reads like a broken deck rather than a wrong lookup.
    """
    m = BUILT_FROM_RE.search(raw)
    if not m:
        return
    name, stamp = m.group(1).strip(), (m.group(2) or "").strip()
    meta = design_meta(rep.design)
    if meta.get("name") and name != meta["name"]:
        rep.add("design-source", WARNING, "the page was generated from DESIGN.md %r, the gate checks against %r "
                "(%s); pass --design with the one it was built from" % (name, meta["name"], rep.design))
    elif stamp and meta.get("last_updated") and stamp != meta["last_updated"]:
        rep.add("design-source", WARNING, "the page was generated from DESIGN.md %s of %s, the file now says %s; "
                "refresh it (new-page.py / new-deck.py --refresh)" % (name, stamp, meta["last_updated"]))


# --- parsing -----------------------------------------------------------------------------

class Page(HTMLParser):
    """Collects what the rules need: elements with parents, text, CSS and JS with lines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict] = []
        self.stack: list[int] = []
        self.texts: list[tuple[str, int]] = []
        self.styles: list[tuple[str, int]] = []
        self.scripts: list[tuple[str, int]] = []
        self._raw: str | None = None

    def _open(self, tag: str, attrs: list, void: bool) -> None:
        line = self.getpos()[0]
        parent = self.stack[-1] if self.stack else None
        el = {"tag": tag, "attrs": {k: v for k, v in attrs}, "line": line, "parent": parent}
        self.elements.append(el)
        style = el["attrs"].get("style")
        if style:
            self.styles.append((style, line))
        if not void and tag not in VOID:
            self.stack.append(len(self.elements) - 1)
        if tag in ("style", "script") and not void:
            self._raw = tag

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        self._raw = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.elements[self.stack[i]]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        line = self.getpos()[0]
        if self._raw == "style":
            self.styles.append((data, line))
        elif self._raw == "script":
            self.scripts.append((data, line))
        else:
            self.texts.append((data, line))


def parse(text: str) -> Page:
    p = Page()
    p.feed(text)
    p.close()
    return p


def ancestors(page: Page, idx: int):
    cur = page.elements[idx]["parent"]
    while cur is not None:
        yield page.elements[cur]
        cur = page.elements[cur]["parent"]


# --- static rules ------------------------------------------------------------------------

class Report:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[dict] = []
        self.notes: list[str] = []
        self.design: Path | None = None
        self.slides: int | None = None
        self._seen: set[tuple[str, str]] = set()

    def add(self, rule: str, level: str, message: str, line: int | None = None) -> None:
        key = (rule, message)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append({"rule": rule, "level": level, "line": line, "message": message})

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f["level"] == level)

    def as_dict(self) -> dict:
        out = {"page": str(self.path), "design": str(self.design) if self.design else None,
               "findings": self.findings, "notes": self.notes}
        if self.slides is not None:
            out["slides"] = self.slides
        return out


def classify_url(url: str, allow: set[str]) -> str | None:
    """None for fine, else 'anchor', 'external' or 'local'."""
    u = url.strip()
    if not u:
        return None
    if u.startswith("#"):
        return "anchor"
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", u)
    scheme = m.group(1).lower() if m else ""
    if scheme in SAFE_SCHEMES:
        return None
    if scheme in ("http", "https") or u.startswith("//"):
        host = (urlsplit(u if scheme else "https:" + u).hostname or "").lower()
        return None if host in allow else "external"
    if scheme == "file" or not scheme:
        return "local"
    return "external"


def check_urls(page: Page, rep: Report, allow: set[str]) -> None:
    def resource(url: str, line: int, where: str) -> None:
        kind = classify_url(url, allow)
        if kind == "external":
            rep.add("external-url", ERROR, "%s loads %s from another host; inline it" % (where, url), line)
        elif kind == "local":
            rep.add("local-ref", ERROR, "%s loads %s from next to the page; inline it as data:" % (where, url), line)

    for el in page.elements:
        tag, attrs, line = el["tag"], el["attrs"], el["line"]
        for name in ("src", "poster", "data", "href", "xlink:href"):
            val = attrs.get(name)
            if not val or (name == "data" and tag != "object"):
                continue
            if name in ("href", "xlink:href") and tag in ("a", "area"):
                if classify_url(val, allow) == "external":
                    rep.add("external-link", WARNING, "<%s href> leaves the page: %s" % (tag, val), line)
                continue
            resource(val, line, "<%s %s>" % (tag, name))
        for item in (attrs.get("srcset") or "").split(","):
            if item.strip():
                resource(item.split()[0], line, "<%s srcset>" % tag)

    for css, first in page.styles:
        clean = blank(css, CSS_COMMENT_RE)
        for m in CSS_URL_RE.finditer(clean):
            resource(m.group(2), line_at(clean, m.start(), first), "url()")
        for m in CSS_IMPORT_RE.finditer(clean):
            resource(m.group(2), line_at(clean, m.start(), first), "@import")


def check_placeholders(raw: str, rep: Report) -> None:
    for m in PLACEHOLDER_RE.finditer(raw):
        rep.add("placeholder", ERROR, "leftover template placeholder %s" % m.group(0), line_at(raw, m.start()))


ELLIPSIS_ONLY = {"…", "...", "…."}


def check_sample(page: Page, rep: Report, allow: bool) -> None:
    """Catalog sample text left in the page: blocks new-page.py marked data-sample, and
    text that is nothing but an ellipsis (the catalog's stand-in for content)."""
    level = WARNING if allow else ERROR
    marked = [el["line"] for el in page.elements if "data-sample" in el["attrs"]]
    if marked:
        rep.add("sample", level, "%d block%s still hold%s catalog sample text (data-sample); write the "
                "content, then drop the attribute" % (len(marked), "" if len(marked) == 1 else "s",
                                                      "s" if len(marked) == 1 else ""), marked[0])
    bare = [line for text, line in page.texts if text.strip() in ELLIPSIS_ONLY]
    if bare:
        rep.add("sample", level, "%d text%s nothing but an ellipsis, the catalog's stand-in for content"
                % (len(bare), " is" if len(bare) == 1 else "s are"), bare[0])


def check_entities(raw: str, page: Page, rep: Report) -> None:
    letters: dict[int, list[str]] = {}
    others: dict[int, list[str]] = {}

    def sort(line: int, spelled: str, char: str) -> None:
        if len(char) != 1 or ord(char) < 128:
            return
        cat = unicodedata.category(char)
        if cat.startswith("Z"):
            return
        target = letters if cat.startswith("L") else others
        target.setdefault(line, []).append("%s (%s)" % (spelled, char))

    for m in ENTITY_RE.finditer(raw):
        sort(line_at(raw, m.start()), m.group(0), html.unescape(m.group(0)))
    for js, first in page.scripts:
        for m in ESCAPE_RE.finditer(js):
            code = int(next(g for g in m.groups() if g), 16)
            if code <= sys.maxunicode:
                sort(line_at(js, m.start(), first), m.group(0), chr(code))
    for line, items in sorted(letters.items()):
        rep.add("entity", ERROR, "letters spelled as entity or escape: %s; write the UTF-8 character"
                % ", ".join(items), line)
    for line, items in sorted(others.items()):
        rep.add("entity", WARNING, "characters spelled as entity or escape: %s; write the UTF-8 character"
                % ", ".join(items), line)


def check_hex(page: Page, rep: Report, declared: set[str]) -> None:
    ids = {(el["attrs"].get("id") or "").lower() for el in page.elements}
    hits: dict[str, list[int]] = {}

    def take(digits: str, line: int) -> None:
        h = norm_hex(digits)
        if h and h not in declared:
            hits.setdefault(h if len(digits) in (3, 6) else "#" + digits.lower(), []).append(line)

    for css, first in page.styles:
        text = blank(blank(css, CSS_COMMENT_RE), CSS_URL_RE)
        # A style attribute is one declaration block; a sheet holds selectors
        # outside its braces, and "#face" in a selector is an id, not a colour.
        bodies = [(text, 0)] if "{" not in text else [(m.group(1), m.start(1)) for m in CSS_BODY_RE.finditer(text)]
        for body, off in bodies:
            for m in HEX_RE.finditer(body):
                take(m.group(1), line_at(text, off + m.start(), first))
    for el in page.elements:
        for name in PRESENTATION_COLOR_ATTRS:
            val = el["attrs"].get(name) or ""
            for m in HEX_RE.finditer(val):
                take(m.group(1), el["line"])
        if el["tag"] == "meta" and (el["attrs"].get("name") or "").lower() == "theme-color":
            for m in HEX_RE.finditer(el["attrs"].get("content") or ""):
                take(m.group(1), el["line"])
    for js, first in page.scripts:
        for m in JS_HEX_RE.finditer(js):
            if m.group(2).lower() not in ids:  # '#face' naming an element is a selector
                take(m.group(2), line_at(js, m.start(), first))
    for value, lines in hits.items():
        rep.add("hex", ERROR, "%s is not declared in the DESIGN.md front matter (%d use%s); use a token"
                % (value, len(lines), "" if len(lines) == 1 else "s"), lines[0])


def families(value: str) -> list[str]:
    out = []
    for part in value.replace("!important", "").split(","):
        name = part.strip().strip("'\"").strip()
        if name and "var(" not in name:
            out.append(name)
    return out


def check_fonts(page: Page, rep: Report) -> None:
    faces: set[str] = set()
    for css, _ in page.styles:
        for m in FONT_FACE_RE.finditer(css):
            for d in re.finditer(r"font-family\s*:\s*([^;]+)", m.group(1), re.I):
                faces.update(f.lower() for f in families(d.group(1)))
    for css, first in page.styles:
        text = blank(css, CSS_COMMENT_RE)
        text = blank(text, FONT_FACE_RE)
        for m in FONT_DECL_RE.finditer(text):
            named = families(m.group(2))
            # A stack that leads with a system family is a system stack by
            # choice; a later family in it is a fallback, not a dependency.
            if named and named[0].lower() in SYSTEM_FAMILIES | GENERIC_FAMILIES:
                continue
            for fam in named:
                low = fam.lower()
                if low in faces or low in GENERIC_FAMILIES or low in SYSTEM_FAMILIES:
                    continue
                rep.add("font-face", WARNING,
                        '"%s" is named without @font-face; it renders only where installed '
                        "(embed it, or rely on the fallback)" % fam, line_at(text, m.start(), first))


def check_bilingual(page: Page, rep: Report) -> None:
    per_parent: dict[object, dict[str, list[int]]] = {}
    bilingual = False
    for idx, el in enumerate(page.elements):
        attrs = el["attrs"]
        has = {lang: ("data-" + lang) in attrs for lang in ("de", "en")}
        if has["de"] or has["en"]:
            bilingual = True
        if has["de"] != has["en"]:
            lang = "de" if has["de"] else "en"
            if attrs.get("data-" + lang):
                # value form: the text rides in the attribute, so the pair is on this element
                other = "en" if lang == "de" else "de"
                rep.add("lang-pair", ERROR, "<%s data-%s> has no data-%s on the same element"
                        % (el["tag"], lang, other), el["line"])
            else:
                per_parent.setdefault(el["parent"], {"de": [], "en": []})[lang].append(el["line"])
        for name in attrs:
            m = BILINGUAL_ATTR_RE.match(name)
            if m:
                other = "data-%s-%s" % (m.group(1), "en" if m.group(2) == "de" else "de")
                if other not in attrs:
                    rep.add("aria-pair", ERROR, "<%s %s> has no %s counterpart" % (el["tag"], name, other),
                            el["line"])
    for parent, langs in per_parent.items():
        if len(langs["de"]) != len(langs["en"]):
            where = "<%s>" % page.elements[parent]["tag"] if parent is not None else "the document"
            rep.add("lang-pair", ERROR, "%d data-de but %d data-en children under %s"
                    % (len(langs["de"]), len(langs["en"]), where), min(langs["de"] + langs["en"]))
    if not bilingual:
        return
    for idx, el in enumerate(page.elements):
        attrs = el["attrs"]
        if "aria-label" not in attrs or any(BILINGUAL_ATTR_RE.match(n) and "aria" in n for n in attrs):
            continue
        chain = [el, *ancestors(page, idx)]
        if any("data-de" in a["attrs"] or "data-en" in a["attrs"] for a in chain):
            continue
        rep.add("aria-lang", WARNING, '<%s aria-label="%s"> speaks one language on a bilingual page; '
                "add data-aria-de / data-aria-en" % (el["tag"], attrs["aria-label"]), el["line"])


def check_anchors(page: Page, rep: Report) -> None:
    targets = {"top"}
    for el in page.elements:
        for name in ("id", "name"):
            if el["attrs"].get(name):
                targets.add(el["attrs"][name])
    for el in page.elements:
        for name in ("href", "xlink:href"):
            val = el["attrs"].get(name) or ""
            if val.startswith("#") and len(val) > 1 and unquote(val[1:]) not in targets:
                rep.add("dead-anchor", ERROR, "<%s %s=\"%s\"> points at no id or name" % (el["tag"], name, val),
                        el["line"])


def check_charset(page: Page, rep: Report) -> None:
    for el in page.elements:
        if el["tag"] != "meta":
            continue
        a = el["attrs"]
        if "charset" in a or ((a.get("http-equiv") or "").lower() == "content-type"
                              and "charset=" in (a.get("content") or "").lower()):
            return
    rep.add("charset", ERROR, 'no <meta charset="utf-8">; umlauts depend on the viewer\'s guess', 1)


def check_forbidden(page: Page, rep: Report, chars: str) -> None:
    if not chars:
        return
    runs: list[tuple[str, int]] = list(page.texts)
    for el in page.elements:
        for name, val in el["attrs"].items():
            if val and (name in VISIBLE_ATTRS or BILINGUAL_ATTR_RE.match(name)):
                runs.append((val, el["line"]))
    for ch in dict.fromkeys(chars):
        lines = [line_at(text, i, first) for text, first in runs for i, c in enumerate(text) if c == ch]
        if lines:
            name = unicodedata.name(ch, "")
            rep.add("forbidden-char", ERROR, "%r (U+%04X%s) appears %d time%s in visible text"
                    % (ch, ord(ch), " " + name if name else "", len(lines), "" if len(lines) == 1 else "s"),
                    min(lines))


def static_checks(path: Path, rep: Report, allow: set[str], forbid: str, allow_sample: bool = False) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    page = parse(text)
    raw = blank(text, COMMENT_RE)
    check_urls(page, rep, allow)
    check_placeholders(raw, rep)
    check_sample(page, rep, allow_sample)
    check_entities(raw, page, rep)
    if rep.design:
        rep.notes.append("checked against %s" % rep.design)
        check_design_source(text, rep)
        check_hex(page, rep, declared_hex(rep.design))
    else:
        rep.notes.append("no DESIGN.md found, hex check skipped (pass --design)")
    check_fonts(page, rep)
    check_bilingual(page, rep)
    check_anchors(page, rep)
    check_charset(page, rep)
    check_forbidden(page, rep, forbid)


# --- browser rules -----------------------------------------------------------------------

JS_DESC = """const desc = el => {
  const t = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  return '<' + el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '> "' + t + '"';
};"""

# How a page switches to dark, most specific first. `mode` is what JS_STATE
# applies to <html>: a class (with an optional light twin), an attribute value,
# or nothing but the emulated prefers-color-scheme.
JS_SUPPORT = """(given) => {
  let text = '';
  const walk = rules => { for (const r of rules) {
    text += (r.cssText || '') + '\\n';
    if (r.cssRules) walk(r.cssRules);
  } };
  for (const s of document.styleSheets) { try { walk(s.cssRules); } catch (e) {} }
  const lang = !!document.querySelector('[data-de],[data-en]');
  if (given) return {mode: given, lang};
  let mode = null;
  const attr = text.match(/\\[data-theme\\s*=\\s*["']?dark["']?\\s*\\]/);
  if (/\\.theme-dark\\b/.test(text)) mode = {kind: 'class', name: 'theme-dark',
    light: /\\.theme-light\\b/.test(text) ? 'theme-light' : null};
  else if (attr) mode = {kind: 'attr', name: 'data-theme', value: 'dark', light: 'light'};
  else if (/\\.dark\\b/.test(text)) mode = {kind: 'class', name: 'dark', light: null};
  else if (/prefers-color-scheme:\\s*dark/.test(text)) mode = {kind: 'media'};
  return {mode, lang};
}"""

JS_STATE = """([mode, dark, lang]) => {
  const r = document.documentElement;
  if (mode && mode.kind === 'class') {
    r.classList.toggle(mode.name, dark);
    if (mode.light) r.classList.toggle(mode.light, !dark);
  } else if (mode && mode.kind === 'attr') {
    if (dark) r.setAttribute(mode.name, mode.value);
    else if (mode.light) r.setAttribute(mode.name, mode.light);
    else r.removeAttribute(mode.name);
  }
  if (lang) { r.setAttribute('data-lang', lang); r.setAttribute('lang', lang); }
}"""

# Elements carrying both data-de and data-en are the same in both languages,
# so the swap must leave them alone; one that renders in neither is lost.
JS_DUAL_HIDDEN = """() => {
  %s
  return [...document.querySelectorAll('[data-de][data-en]')].filter(el => {
    const p = el.parentElement;
    return !el.getClientRects().length && (!p || p.getClientRects().length);
  }).map(el => ({key: [...document.querySelectorAll('*')].indexOf(el), desc: desc(el)}));
}""" % JS_DESC


def parse_dark_selector(sel: str) -> dict:
    """`.night`, `html.night`, `:root.night`, `[data-mode="night"]` or `[data-night]`."""
    s = sel.strip()
    for prefix in ("html", ":root"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    m = re.fullmatch(r"\.([A-Za-z_][\w-]*)", s)
    if m:
        return {"kind": "class", "name": m.group(1), "light": None}
    m = re.fullmatch(r"""\[\s*([A-Za-z_][\w-]*)\s*(?:=\s*(["']?)([^"'\]]+)\2\s*)?\]""", s)
    if m:
        return {"kind": "attr", "name": m.group(1), "value": m.group(3) or "", "light": None}
    raise ValueError(sel)


JS_BOTH = """(lang) => {
  %s
  const other = lang === 'de' ? 'en' : 'de', bad = [];
  for (const el of document.querySelectorAll('[data-' + other + ']')) {
    if (el.getAttribute('data-' + other) || el.hasAttribute('data-' + lang)) continue;
    if (el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden') bad.push(desc(el));
  }
  return bad;
}""" % JS_DESC

JS_CONTRAST = """() => {
  %s
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', {willReadFrequently: true});
  const rgba = c => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (top, under) => [0, 1, 2].map(i => top[i] * top[3] + under[i] * (1 - top[3])).concat([1]);
  const paints = cs => cs.backgroundImage !== 'none' || rgba(cs.backgroundColor)[3] > 0;
  // A positioned sibling of the text or of one of its ancestors that overlaps it
  // (a scrim, a gradient layer, a photo) paints behind the text without being an
  // ancestor, so the colour walk below cannot see it.
  const underlaid = el => {
    const r = el.getBoundingClientRect();
    for (let a = el; a && a.parentElement && a !== document.body; a = a.parentElement) {
      for (let s = a.parentElement.firstElementChild; s; s = s.nextElementSibling) {
        if (s === a) continue;
        const cs = getComputedStyle(s);
        if ((cs.position !== 'absolute' && cs.position !== 'fixed') || !paints(cs)) continue;
        if (cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
        const q = s.getBoundingClientRect();
        if (q.right > r.left && q.left < r.right && q.bottom > r.top && q.top < r.bottom) return true;
      }
    }
    return false;
  };
  // null: the ground is an image or a layer, measured from pixels (JS_LAYER_SAMPLE)
  const ground = el => {
    const layers = [];
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage !== 'none') return null;
      const c = rgba(cs.backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 0.99) break;
    }
    if (underlaid(el)) return null;
    let base = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  };
  const lum = c => { const v = c.slice(0, 3).map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const hasText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const els = [document.body, ...document.querySelectorAll('p, li, td, th, dd, dt, figcaption, blockquote, h1, h2, h3, h4, label, small, span')]
    .filter((el, i) => i === 0 || (hasText(el) && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden'
      && !el.closest('[aria-hidden="true"]')))
    .slice(0, 300);
  const bad = [], layered = [];
  for (const el of els) {
    const cs = getComputedStyle(el);
    const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight, 10) || 400;
    const need = (size >= 24 || (size >= 18.66 && weight >= 700)) ? 3 : 4.5;
    const bg = ground(el);
    if (!bg) {
      if (el !== document.body) layered.push({el, color: rgba(cs.color), need, desc: desc(el), done: false});
      continue;
    }
    const fg = over(rgba(cs.color), bg);
    const a = lum(fg), b = lum(bg), ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    if (ratio < need) bad.push({el: desc(el), ratio: Math.round(ratio * 100) / 100, need});
  }
  window.__vpLayered = layered;
  return {bad, layered: layered.length};
}""" % JS_DESC

# Code in another family than the page's own mono stack. Only pages that declare
# --font-mono are measured: that variable is the page saying which family code takes.
JS_CODE_FONT = """() => {
  %s
  const first = f => (f || '').split(',')[0].trim().replace(/^["']|["']$/g, '').toLowerCase();
  const mono = first(getComputedStyle(document.documentElement).getPropertyValue('--font-mono'));
  if (!mono) return [];
  return [...document.querySelectorAll('code, kbd, pre, samp')]
    .filter(el => el.getClientRects().length && el.textContent.trim() && first(getComputedStyle(el).fontFamily) !== mono)
    .map(el => desc(el) + ' in ' + first(getComputedStyle(el).fontFamily));
}""" % JS_DESC

# Text over an image, a gradient or a sibling layer: hide all text, bring the next
# unmeasured element into view, and read the ground from a screenshot of it.
HIDE_TEXT = ("*,*::before,*::after{color:transparent!important;-webkit-text-fill-color:transparent!important;"
             "text-shadow:none!important;text-decoration-color:transparent!important;caret-color:transparent!important}")
MAX_LAYER_SHOTS = 40

JS_LAYER_BEGIN = """(css) => {
  const st = document.createElement('style'); st.id = '__vp-hide-text'; st.textContent = css;
  document.head.appendChild(st);
  window.__vpScroll = [...document.querySelectorAll('*')].filter(e => e.scrollTop || e.scrollLeft)
    .map(e => [e, e.scrollTop, e.scrollLeft]);
  window.__vpScroll.push([document.scrollingElement, document.scrollingElement.scrollTop, document.scrollingElement.scrollLeft]);
}"""

JS_LAYER_END = """() => {
  const st = document.getElementById('__vp-hide-text'); if (st) st.remove();
  for (const [e, t, l] of (window.__vpScroll || [])) { e.scrollTop = t; e.scrollLeft = l; }
}"""

# The rects a text actually occupies: its own text nodes, not the whole block.
JS_LAYER_NEXT = """() => {
  const next = (window.__vpLayered || []).find(x => !x.done);
  if (!next) return false;
  next.el.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'});
  return true;
}"""

JS_LAYER_SAMPLE = """async (url) => {
  const img = new Image(); img.src = url; await img.decode();
  const cv = document.createElement('canvas'); cv.width = img.naturalWidth; cv.height = img.naturalHeight;
  const cx = cv.getContext('2d', {willReadFrequently: true}); cx.drawImage(img, 0, 0);
  const sx = img.naturalWidth / innerWidth, sy = img.naturalHeight / innerHeight;
  const px = (x, y) => { const d = cx.getImageData(Math.min(cv.width - 1, Math.max(0, Math.round(x * sx))),
    Math.min(cv.height - 1, Math.max(0, Math.round(y * sy))), 1, 1).data; return [d[0], d[1], d[2], 1]; };
  const over = (top, under) => [0, 1, 2].map(i => top[i] * top[3] + under[i] * (1 - top[3])).concat([1]);
  const lum = c => { const v = c.slice(0, 3).map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const rectsOf = el => { const out = [];
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const r of rg.getClientRects()) if (r.width > 1 && r.height > 1) out.push(r);
    }
    return out; };
  const bad = [];
  for (const x of window.__vpLayered || []) {
    if (x.done) continue;
    const rects = rectsOf(x.el);
    if (!rects.length) { x.done = true; continue; }
    if (!rects.every(r => r.top >= 0 && r.left >= 0 && r.bottom <= innerHeight && r.right <= innerWidth)) continue;
    x.done = true;
    let worst = Infinity;
    for (const r of rects) for (const fx of [0.1, 0.5, 0.9]) for (const fy of [0.3, 0.7]) {
      const bg = px(r.left + r.width * fx, r.top + r.height * fy), fg = over(x.color, bg);
      const a = lum(fg), b = lum(bg);
      worst = Math.min(worst, (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05));
    }
    if (worst < x.need) bad.push({el: x.desc, ratio: Math.round(worst * 100) / 100, need: x.need});
  }
  // an element that cannot come fully into view (taller than the viewport) is not measured
  const stuck = (window.__vpLayered || []).find(x => !x.done);
  if (stuck && stuck.tries > 1) stuck.done = true; else if (stuck) stuck.tries = (stuck.tries || 0) + 1;
  return bad;
}"""


def contrast_findings(page) -> list[dict]:
    """Low-contrast text in the current state: colour walk first, pixels where it cannot see."""
    res = page.evaluate(JS_CONTRAST)
    bad = list(res["bad"])
    if not res["layered"]:
        return bad
    page.evaluate(JS_LAYER_BEGIN, HIDE_TEXT)
    try:
        for _ in range(MAX_LAYER_SHOTS):
            if not page.evaluate(JS_LAYER_NEXT):
                break
            page.wait_for_timeout(60)
            png = base64.b64encode(page.screenshot(type="png")).decode("ascii")
            bad += page.evaluate(JS_LAYER_SAMPLE, "data:image/png;base64," + png)
    finally:
        page.evaluate(JS_LAYER_END)
        page.wait_for_timeout(30)
    return bad

JS_HIDDEN = """() => {
  %s
  return [...document.querySelectorAll('body *')].filter(el => {
    if (!el.getClientRects().length) return false;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return false;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      /* a step not yet reached (html-slides steps): its module shows it in print, PDF and read */
      if (e.classList.contains('step-hidden')) return false;
      if (parseFloat(getComputedStyle(e).opacity) === 0) return true;
    }
    return false;
  }).map(desc);
}""" % JS_DESC

JS_SLIDES = """(sel) => [...document.querySelectorAll(sel)].map(el => (
  {sh: el.scrollHeight, ch: el.clientHeight, sw: el.scrollWidth, cw: el.clientWidth}))"""

NO_TRANSITIONS = "*,*::before,*::after{transition:none!important}"
DECK_SIZES = ((1280, 720), (1920, 1080))


def browser_checks(path: Path, rep: Report, args) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        rep.add("browser-skipped", ERROR, "playwright is not installed; the browser checks that were "
                "asked for did not run")
        return
    work = Path(tempfile.mkdtemp(prefix="verify-page-"))
    try:
        target = work / path.name
        shutil.copyfile(path, target)  # alone: nothing the page needs may sit next to it
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as exc:  # browser binary not installed
                rep.add("browser-skipped", ERROR, "chromium not available (%s); the browser checks that "
                        "were asked for did not run" % str(exc).splitlines()[0])
                return
            try:
                run_browser(browser, target, rep, args)
            finally:
                browser.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def open_page(browser, target: Path, rep: Report, allow: set[str], **ctx_opts):
    ctx = browser.new_context(**ctx_opts)
    own = target.as_uri()

    def route(r):
        url = r.request.url
        scheme = url.split(":", 1)[0].lower()
        if scheme in ("data", "blob", "about", "file"):
            # a sibling file is missing in the empty temp dir and fails as request-failed
            return r.continue_()
        if scheme in ("http", "https") and (urlsplit(url).hostname or "").lower() in allow:
            return r.continue_()
        rep.add("network", ERROR, "the page requests %s; a single-file page loads nothing" % url)
        return r.abort()

    ctx.route("**/*", route)
    page = ctx.new_page()

    def console(msg):
        # a failed load is reported once, as request-failed or network, not again here
        if msg.type == "error" and not msg.text.startswith("Failed to load resource"):
            rep.add("console-error", ERROR, "console: %s" % msg.text)

    page.on("console", console)
    page.on("pageerror", lambda exc: rep.add("console-error", ERROR, "uncaught: %s" % exc))
    page.on("requestfailed", lambda req: req.url.startswith("file:")
            and rep.add("request-failed", ERROR, "%s did not load (%s)" % (req.url.rsplit("/", 1)[-1], req.failure)))
    page.goto(own, wait_until="load")
    page.wait_for_timeout(150)
    return ctx, page


def shot(page, out: Path | None, stem: str, state: str, width: int, full: bool = True) -> None:
    if out:
        page.screenshot(path=str(out / ("%s-%s-%d.png" % (stem, state, width))), full_page=full)


def run_browser(browser, target: Path, rep: Report, args) -> None:
    allow = set(args.allow_host)
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    stem = target.stem
    for n, width in enumerate(args.width):
        ctx, page = open_page(browser, target, rep, allow, viewport={"width": width, "height": 800})
        support = page.evaluate(JS_SUPPORT, getattr(args, "dark_mode", None))
        mode = support["mode"]
        themes = (False, True) if mode else (False,)
        langs = ("en", "de") if support["lang"] else (None,)
        page.add_style_tag(content=NO_TRANSITIONS)
        hidden_in: dict[str, dict] = {}
        for dark in themes:
            for lang in langs:
                page.emulate_media(color_scheme="dark" if dark else "light")
                page.evaluate(JS_STATE, [mode, dark, lang])
                page.wait_for_timeout(50)
                state = ("dark" if dark else "light") + ("-" + lang if lang else "")
                if n == 0:
                    if lang and not dark:  # the theme does not change which language shows
                        both = page.evaluate(JS_BOTH, lang)
                        if both:
                            rep.add("both-languages", ERROR, "%s: %d element%s of the other language visible, e.g. %s"
                                    % (lang, len(both), "" if len(both) == 1 else "s", both[0]))
                        hidden_in[lang] = {h["key"]: h["desc"] for h in page.evaluate(JS_DUAL_HIDDEN)}
                    for low in contrast_findings(page)[:1]:
                        rep.add("contrast", ERROR, "%s: %s:1 under %s:1 for %s" % (state, low["ratio"], low["need"], low["el"]))
                    if not dark and lang == langs[0]:
                        off = page.evaluate(JS_CODE_FONT)
                        if off:
                            rep.add("code-font", WARNING, "%d code element%s outside the page's --font-mono, e.g. %s"
                                    % (len(off), "" if len(off) == 1 else "s", off[0]))
                shot(page, out, stem, state, width)
        if len(hidden_in) == 2:
            lost = [d for k, d in hidden_in["en"].items() if k in hidden_in["de"]]
            if lost:
                rep.add("lang-hidden", ERROR, "%d element%s carrying both data-de and data-en show%s in neither "
                        "language, e.g. %s; the swap must skip them (:not([data-en]) / :not([data-de]))"
                        % (len(lost), "" if len(lost) == 1 else "s", "s" if len(lost) == 1 else "", lost[0]))
        page.emulate_media(media="print", color_scheme="light")
        page.evaluate(JS_STATE, [mode, False, langs[0]])
        shot(page, out, stem, "print", width)
        ctx.close()

        ctx, page = open_page(browser, target, rep, allow, viewport={"width": width, "height": 800},
                              reduced_motion="reduce")
        page.wait_for_timeout(300)
        if n == 0:
            hidden = page.evaluate(JS_HIDDEN)
            if hidden:
                rep.add("reduced-motion", WARNING, "%d text element%s stay at opacity 0 under reduced motion, e.g. %s"
                        % (len(hidden), "" if len(hidden) == 1 else "s", hidden[0]))
        shot(page, out, stem, "reduced-motion", width)
        ctx.close()
    if args.deck:
        deck_checks(browser, target, rep, args, allow)


def deck_checks(browser, target: Path, rep: Report, args, allow: set[str]) -> None:
    sel = args.slide_selector
    for w, h in DECK_SIZES:
        ctx, page = open_page(browser, target, rep, allow, viewport={"width": w, "height": h})
        slides = page.evaluate(JS_SLIDES, sel)
        rep.slides = len(slides)
        for i, s in enumerate(slides, 1):
            over_y, over_x = s["sh"] - s["ch"], s["sw"] - s["cw"]
            if s["ch"] and (over_y > 1 or over_x > 1):
                rep.add("slide-overflow", ERROR, "slide %d overflows at %dx%d by %d px%s"
                        % (i, w, h, max(over_y, over_x), " (horizontal)" if over_x > over_y else ""))
        ctx.close()
    if not rep.slides:
        rep.add("slide-count", ERROR, "no element matches %r; pass --slide-selector" % sel)
        return
    ctx, page = open_page(browser, target, rep, allow, viewport={"width": DECK_SIZES[0][0], "height": DECK_SIZES[0][1]})
    page.emulate_media(media="print")
    pdf = page.pdf(prefer_css_page_size=True, print_background=True)
    ctx.close()
    pages = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", pdf))
    if pages != rep.slides:
        rep.add("print-pages", ERROR, "print gives %d page%s for %d slides; give each slide its own page"
                % (pages, "" if pages == 1 else "s", rep.slides))


# --- CLI ---------------------------------------------------------------------------------

def plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def human(reports: list[Report]) -> str:
    lines = []
    for rep in reports:
        if not rep.findings:
            lines.append("%s: ok" % rep.path)
        else:
            lines.append(str(rep.path))
            order = sorted(rep.findings, key=lambda f: (f["level"] != ERROR, f["line"] or 0))
            for f in order:
                where = "L%d" % f["line"] if f["line"] else "-"
                lines.append("  %-5s  %-15s %-6s %s" % ("ERROR" if f["level"] == ERROR else "WARN",
                                                       f["rule"], where, f["message"]))
        for note in rep.notes:
            lines.append("  note: %s" % note)
    errors = sum(r.count(ERROR) for r in reports)
    warnings = sum(r.count(WARNING) for r in reports)
    lines.append("verify-page: %s, %s (%s)" % (plural(errors, "error"), plural(warnings, "warning"),
                                                plural(len(reports), "page")))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="quality gate for single-file HTML pages and decks")
    ap.add_argument("pages", nargs="+", help="HTML file(s) to check")
    ap.add_argument("--design", help="DESIGN.md to check hex colours against (default: nearest one above the page)")
    ap.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                    help="a host resources may come from (repeatable)")
    ap.add_argument("--forbid-chars", default="", metavar="CHARS",
                    help="characters not allowed in visible text (off by default)")
    ap.add_argument("--forbid-chars-from", metavar="FILE",
                    help="file with forbidden characters; whitespace and lines starting with # are ignored")
    ap.add_argument("--browser", action="store_true", help="also render the page (playwright)")
    ap.add_argument("--deck", action="store_true", help="also check slides; implies --browser")
    ap.add_argument("--slide-selector", default=".slide", help="CSS selector of one slide (default: .slide)")
    ap.add_argument("--dark-selector", metavar="SELECTOR",
                    help="what puts <html> in dark mode when it is none of html.dark, .theme-dark, "
                         "[data-theme=dark]: a class (.night) or an attribute ([data-mode=night])")
    ap.add_argument("--out", help="directory for screenshots (browser mode)")
    ap.add_argument("--width", type=int, action="append", metavar="PX",
                    help="viewport width for the browser pass, at least 500 (repeatable, default 1280)")
    ap.add_argument("--allow-sample", action="store_true",
                    help="report catalog sample text as a warning, not an error (a fresh skeleton)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the list")
    args = ap.parse_args()

    args.width = args.width or [1280]
    args.dark_mode = None
    if args.dark_selector is not None:
        try:
            args.dark_mode = parse_dark_selector(args.dark_selector)
        except ValueError:
            ap.error("--dark-selector takes a class or an attribute on <html>, e.g. .night or "
                     '[data-mode="night"]; got %r' % args.dark_selector)
    if min(args.width) < 500:
        ap.error("--width must be at least 500 px: headless chromium clamps narrower viewports")
    forbid = args.forbid_chars
    if args.forbid_chars_from:
        fpath = Path(args.forbid_chars_from)
        if not fpath.is_file():
            ap.error("--forbid-chars-from: %s not found" % fpath)
        for ln in fpath.read_text(encoding="utf-8").splitlines():
            if not ln.lstrip().startswith("#"):
                forbid += "".join(ln.split())
    try:
        design = bridge_design().resolve(args.design) if args.design else None
    except ValueError as e:
        ap.error(str(e))
    if design and not design.is_file():
        ap.error("--design: %s not found" % design)
    paths = [Path(p) for p in args.pages]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        ap.error("no such page: %s" % ", ".join(missing))
    allow = {h.lower() for h in args.allow_host}
    args.allow_host = sorted(allow)

    reports = []
    for path in paths:
        rep = Report(path)
        try:
            # the design the page records it was built with, else the one found from where it sits
            rep.design = (design or bridge_design().recorded(path.read_text(encoding="utf-8", errors="replace"))
                          or find_design(path.resolve()))
        except ValueError as e:
            ap.error(str(e))
        static_checks(path, rep, allow, forbid, args.allow_sample)
        if args.browser or args.deck:
            browser_checks(path, rep, args)
        reports.append(rep)

    errors = sum(r.count(ERROR) for r in reports)
    if args.json:
        print(json.dumps({"pages": [r.as_dict() for r in reports], "errors": errors,
                          "warnings": sum(r.count(WARNING) for r in reports)}, ensure_ascii=False, indent=2))
    else:
        print(human(reports))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
