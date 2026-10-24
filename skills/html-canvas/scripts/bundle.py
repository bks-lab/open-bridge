#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fold a page and everything it loads into ONE file with no external references.

The send variant: a page that is mailed, attached or dropped into a download
folder has no sibling files, no network and no font install. This script reads
an entry page and rewrites it so it needs none of them.

What happens to each reference (paths resolve against the file that holds them):
  <img|source|video|audio|track|embed|object|svg image> src/poster/data/href/srcset
                          -> data: URI
  <link rel="stylesheet"> -> <style> block (its url() and @import follow)
  <link rel="icon"|...>   -> data: URI
  <script src>            -> inline <script> (defer/async/integrity dropped)
  <style> and style="..." -> url() and @import resolved the same way
  <iframe src>            -> base64 payload plus a loader that sets srcdoc from
                             the decoded UTF-8 bytes (TextDecoder over atob), so
                             umlauts survive; the child page is bundled first, so
                             its own assets and iframes are folded in too
  <iframe data-src>       -> same payload, but loaded on demand: the parent calls
                             window.__bundle.load(iframe) (lazy stage frames)
  .stage data-src         -> same payload, referenced as data-srcdoc-ref (html-slides
                             live stage; payloads carry data-encoding="base64")
  <a href="page.html">    -> only with --pages: payload that opens in a new tab
                             from a Blob URL; without --pages it is an error
  <a href="file.pdf">     -> data: URI with a download name
Fonts are always embedded: an existing @font-face keeps its data, a local font
url() is inlined, and families named by a DESIGN.md (given with --design, else the
nearest DESIGN.md above the entry) that the page uses but does not declare are
added through embed-fonts.py.

Remote resources (http, https, protocol-relative) are refused unless
--allow-remote; hyperlinks to the web are navigation, not loads, and stay.
Every missing or refused reference is collected and reported at once, and
nothing is written unless all of them are resolved.

A sha256 per inlined source goes to stderr, or to --manifest in the sha256sum
layout ("<hash>  <path>", paths relative to the entry's directory).

Not followed: URLs built in JavaScript, srcdoc attributes written by hand, JS
module imports, and <use href="sprite.svg#id">. A deferred script runs where it
sits once inlined. An inline script string naming a local .html file that
exists is reported as a WARNING, since the send copy will not find it.

Usage:
  bundle.py <entry.html> --out <file> [--pages] [--allow-remote]
            [--manifest FILE] [--design DESIGN.md] [--font-dir DIR ...]

From Python:
  bundle(Path("page.html"), pages=False, allow_remote=False) -> Result
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html as htmllib
import importlib.util
import mimetypes
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent

MIME_OVERRIDES = {
    ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
    ".svg": "image/svg+xml", ".js": "text/javascript", ".mjs": "text/javascript",
    ".css": "text/css", ".json": "application/json", ".webp": "image/webp",
    ".avif": "image/avif", ".ico": "image/x-icon", ".mp4": "video/mp4", ".webm": "video/webm",
    ".pdf": "application/pdf",
}
HTML_EXT = {".html", ".htm", ".xhtml"}
# <link rel> values that load something; canonical, alternate, preconnect and
# friends only describe or hint, so they are left alone.
LOADING_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "apple-touch-icon-precomposed",
                "mask-icon", "manifest", "preload", "modulepreload", "prefetch"}
URL_ATTRS = {
    "img": ("src", "srcset"), "source": ("src", "srcset"), "video": ("src", "poster"),
    "audio": ("src",), "track": ("src",), "embed": ("src",), "object": ("data",),
    "input": ("src",), "image": ("href", "xlink:href"), "link": ("href", "imagesrcset"),
}
SKIP_PREFIXES = ("data:", "blob:", "about:", "javascript:", "mailto:", "tel:", "sms:")
LOADER_VERSION = "bundle-loader v1"

LOADER = """<script>
/* %s: decodes the payload blocks above; UTF-8 safe */
(function () {
  function bytes(id) {
    var s = atob(document.getElementById(id).textContent.replace(/\\s+/g, ''));
    var u = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    return u;
  }
  function load(frame) {
    var id = frame.getAttribute('data-bundle');
    if (id && !frame.hasAttribute('srcdoc')) frame.srcdoc = new TextDecoder('utf-8').decode(bytes(id));
  }
  window.__bundle = { load: load };
  var frames = document.querySelectorAll('iframe[data-bundle]:not([data-bundle-lazy])');
  for (var i = 0; i < frames.length; i++) load(frames[i]);
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[data-bundle-page]') : null;
    if (!a) return;
    e.preventDefault();
    var blob = new Blob([bytes(a.getAttribute('data-bundle-page'))], { type: 'text/html;charset=utf-8' });
    window.open(URL.createObjectURL(blob) + (a.getAttribute('data-bundle-hash') || ''), '_blank');
  });
})();
</script>""" % LOADER_VERSION

SEGMENT_RE = re.compile(
    r"<!--.*?-->"
    r"|<script\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>.*?</script\s*>"
    r"|<style\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>.*?</style\s*>",
    re.S | re.I)
TAG_RE = re.compile(r"<([A-Za-z][\w:-]*)((?:\s+[^\s\"'<>/=]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?)*)\s*(/?)>")
ATTR_RE = re.compile(r"([^\s\"'<>/=]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+)))?")
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
CSS_URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\s]*))\s*\)", re.I)
CSS_IMPORT_RE = re.compile(r"@import\s+(?:url\(\s*)?([\"']?)([^\"')\s;]+)\1\s*\)?([^;]*);", re.I)
FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*\}", re.I | re.S)
B64_RE = re.compile(r"base64,[A-Za-z0-9+/=]+")


def find_design(start: Path) -> Path | None:
    """The nearest DESIGN.md at or above `start`, never above the project root.

    Same rule as design-to-css.find_design: the walk stops at the first folder
    holding .git or bridge-config.yaml, and without one only `start` counts.
    """
    start = Path(start).resolve()
    if not start.is_dir():
        start = start.parent
    chain = [start, *start.parents]
    root = next((d for d in chain if any((d / m).exists() for m in (".git", "bridge-config.yaml"))), None)
    for d in chain if root else [start]:
        if (d / "DESIGN.md").is_file():
            return d / "DESIGN.md"
        if d == root:
            break
    return None


@dataclass
class Result:
    html: str = ""
    sources: dict = field(default_factory=dict)   # rel path -> sha256, in discovery order
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class Attr:
    __slots__ = ("name", "raw", "value", "new")

    def __init__(self, name: str, raw: str, value: str | None):
        self.name, self.raw, self.value, self.new = name, raw, value, None


class Bundler:
    def __init__(self, entry: Path, pages=False, allow_remote=False, design: Path | None = None,
                 font_dirs: Sequence[Path] = ()):
        self.entry = entry.resolve()
        self.root = self.entry.parent
        self.pages, self.allow_remote = pages, allow_remote
        self.design = Path(design).resolve() if design else None
        self.font_dirs = [Path(d) for d in font_dirs]
        self.result = Result()
        self._pages: dict[Path, bytes] = {}
        self._stack: list[Path] = []
        self._families: dict[Path, dict] = {}
        self._embed = None

    # ---- bookkeeping ------------------------------------------------------
    def rel(self, path: Path) -> str:
        return Path(os.path.relpath(path, self.root)).as_posix()

    def read(self, path: Path) -> bytes:
        data = path.read_bytes()
        self.result.sources.setdefault(self.rel(path), hashlib.sha256(data).hexdigest())
        return data

    def error(self, where: Path, msg: str) -> None:
        self.result.errors.append(f"{self.rel(where)}: {msg}")

    # ---- reference classification ------------------------------------------
    def resolve(self, ref: str, base: Path, doc: Path, what: str):
        """-> ("local", Path, fragment) | ("skip",) | ("remote",) | ("error",).

        `base` is the directory the reference resolves against, `doc` the file that holds it.
        """
        ref = htmllib.unescape(ref).strip()
        low = ref.lower()
        if not ref or ref.startswith("#") or low.startswith(SKIP_PREFIXES):
            return ("skip",)
        if low.startswith("//") or re.match(r"^[a-z][a-z0-9+.-]*:", low):
            if low.startswith(("http:", "https:", "//")):
                if self.allow_remote:
                    return ("skip",)
                self.error(doc, f"remote {what} {ref} (use --allow-remote to keep it)")
            else:
                self.error(doc, f"unsupported {what} {ref}")
            return ("error",)
        if ref.startswith("/"):
            self.error(doc, f"root-relative {what} {ref} cannot be resolved; use a relative path")
            return ("error",)
        path_part, frag = ref, ""
        if "#" in path_part:
            path_part, frag = path_part.split("#", 1)
            frag = "#" + frag
        path_part = path_part.split("?", 1)[0]
        target = (base / unquote(path_part)).resolve()
        if not target.is_file():
            self.error(doc, f"missing local {what} {ref}")
            return ("error",)
        return ("local", target, frag)

    @staticmethod
    def mime(path: Path) -> str:
        ext = path.suffix.lower()
        return MIME_OVERRIDES.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def data_uri(self, path: Path) -> str:
        return f"data:{self.mime(path)};base64,{base64.b64encode(self.read(path)).decode('ascii')}"

    # ---- CSS ----------------------------------------------------------------
    def css(self, text: str, base: Path, doc: Path, seen: tuple = ()) -> str:
        parts, last = [], 0
        for m in CSS_COMMENT_RE.finditer(text):
            parts.append(self._css_code(text[last:m.start()], base, doc, seen))
            parts.append(m.group(0))
            last = m.end()
        parts.append(self._css_code(text[last:], base, doc, seen))
        return "".join(parts)

    def _css_code(self, code: str, base: Path, doc: Path, seen: tuple) -> str:
        def imp(m):
            res = self.resolve(m.group(2), base, doc, "@import")
            if res[0] == "skip":
                return m.group(0)
            if res[0] == "error":
                return m.group(0)
            target = res[1]
            if target in seen or target == doc:
                self.error(doc, f"@import cycle at {m.group(2)}")
                return m.group(0)
            inner = self.css(self.read(target).decode("utf-8"), target.parent, target, seen + (target,))
            media = m.group(3).strip()
            return f"@media {media} {{\n{inner}\n}}" if media else inner

        code = CSS_IMPORT_RE.sub(imp, code)

        def url(m):
            ref = next(g for g in m.groups() if g is not None)
            res = self.resolve(ref, base, doc, "url()")
            if res[0] != "local":
                return m.group(0)
            return f'url("{self.data_uri(res[1])}")'

        return CSS_URL_RE.sub(url, code)

    # ---- markup -------------------------------------------------------------
    def markup(self, text: str, doc: Path, payloads: dict) -> str:
        out, last = [], 0
        for m in SEGMENT_RE.finditer(text):
            out.append(self._tags(text[last:m.start()], doc, payloads))
            out.append(self._segment(m.group(0), doc, payloads))
            last = m.end()
        out.append(self._tags(text[last:], doc, payloads))
        return "".join(out)

    def _segment(self, seg: str, doc: Path, payloads: dict) -> str:
        low = seg[:8].lower()
        if seg.startswith("<!--"):
            return seg
        if low.startswith("<script"):
            open_end = TAG_RE.match(seg)
            tag = open_end.group(0)
            body = seg[len(tag):]
            new = self._script_tag(tag, doc)
            if new is None:
                self._named_pages(body, doc)
            return new if new is not None else tag + body
        # <style> block
        open_end = TAG_RE.match(seg)
        tag = open_end.group(0)
        close = re.search(r"</style\s*>\s*$", seg, re.I)
        body = seg[len(tag):close.start()]
        return tag + self.css(body, doc.parent, doc) + seg[close.start():]

    def _script_tag(self, tag: str, doc: Path):
        m = TAG_RE.match(tag)
        attrs = self._attrs(m.group(2))
        src = next((a for a in attrs if a.name.lower() == "src"), None)
        if src is None or src.value is None:
            return None
        res = self.resolve(src.value, doc.parent, doc, "script")
        if res[0] != "local":
            return None
        target = res[1]
        code = self.read(target).decode("utf-8")
        code = re.sub(r"</(script)", r"<\\/\1", code, flags=re.I).replace("<!--", "<\\!--")
        drop = {"src", "integrity", "crossorigin", "defer", "async", "referrerpolicy"}
        keep = [a.raw for a in attrs if a.name.lower() not in drop]
        attr_text = "".join(" " + r for r in keep)
        return f'<script{attr_text} data-source="{self.rel(target)}">\n{code}\n</script>'

    @staticmethod
    def _attrs(text: str) -> list[Attr]:
        out = []
        for m in ATTR_RE.finditer(text):
            value = next((g for g in m.groups()[1:] if g is not None), None)
            out.append(Attr(m.group(1), m.group(0), value))
        return out

    def _tags(self, text: str, doc: Path, payloads: dict) -> str:
        return TAG_RE.sub(lambda m: self._tag(m, doc, payloads), text)

    def _tag(self, m: re.Match, doc: Path, payloads: dict) -> str:
        name = m.group(1).lower()
        attrs = self._attrs(m.group(2))
        by = {a.name.lower(): a for a in attrs}
        replace_tag = None   # whole-tag replacement (stylesheet link)
        extra: list[str] = []  # attributes appended
        dropped: set[str] = set()

        style = by.get("style")
        if style and style.value and "url(" in style.value.lower():
            style.new = self.css(htmllib.unescape(style.value), doc.parent, doc).replace('"', "&quot;")

        if name == "link":
            rels = set((by["rel"].value or "").lower().split()) if "rel" in by else set()
            if rels & LOADING_RELS and "href" in by and by["href"].value is not None:
                if "stylesheet" in rels:
                    res = self.resolve(by["href"].value, doc.parent, doc, "stylesheet")
                    if res[0] == "local":
                        target = res[1]
                        css = self.css(self.read(target).decode("utf-8"), target.parent, target, (target,))
                        media = by.get("media")
                        media_attr = f' media="{media.value}"' if media and media.value else ""
                        replace_tag = f'<style{media_attr} data-source="{self.rel(target)}">\n{css}\n</style>'
                else:
                    self._rewrite_url(by["href"], doc)
                    if "imagesrcset" in by:
                        self._rewrite_srcset(by["imagesrcset"], doc)
        elif name == "iframe":
            for key in ("src", "data-src"):
                a = by.get(key)
                if not a or a.value is None:
                    continue
                res = self.resolve(a.value, doc.parent, doc, "iframe")
                if res[0] != "local":
                    continue
                target = res[1]
                dropped.add(key)
                if target.suffix.lower() in HTML_EXT:
                    extra.append(f'data-bundle="{self.payload(target, doc, payloads)}"')
                    if key == "data-src":
                        extra.append("data-bundle-lazy")
                else:
                    extra.append(f'{key}="{self.data_uri(target)}"')
        elif "data-buehne" in by or ("stage" in (by["class"].value or "").split() if "class" in by else False):
            # a live stage (html-slides slide-stage.js): its page travels as a base64 payload
            for key in ("data-src", "data-buehne"):
                a = by.get(key)
                if not a or a.value is None:
                    continue
                res = self.resolve(a.value, doc.parent, doc, "stage")
                if res[0] == "local" and res[1].suffix.lower() in HTML_EXT:
                    dropped.add(key)
                    if "data-srcdoc-ref" not in by:
                        extra.append(f'data-srcdoc-ref="{self.payload(res[1], doc, payloads)}"')
                    break
        elif name == "a" and "href" in by and by["href"].value is not None:
            a = by["href"]
            ref = htmllib.unescape(a.value).strip().lower()
            external = ref.startswith("//") or re.match(r"^[a-z][a-z0-9+.-]*:", ref)
            res = ("skip",) if external else self.resolve(a.value, doc.parent, doc, "link")
            if res[0] == "local":
                target, frag = res[1], res[2]
                if target.suffix.lower() in HTML_EXT:
                    if not self.pages:
                        self.error(doc, f"link to local page {htmllib.unescape(a.value)} (use --pages to bundle it)")
                    else:
                        a.new = "#"
                        extra.append(f'data-bundle-page="{self.payload(target, doc, payloads)}"')
                        if frag:
                            extra.append(f'data-bundle-hash="{frag}"')
                else:
                    a.new = self.data_uri(target)
                    if "download" not in by:
                        extra.append(f'download="{target.name}"')
        elif name in URL_ATTRS:
            for key in URL_ATTRS[name]:
                a = by.get(key)
                if a is None or a.value is None:
                    continue
                if key in ("srcset", "imagesrcset"):
                    self._rewrite_srcset(a, doc)
                else:
                    self._rewrite_url(a, doc)

        if replace_tag is not None:
            return replace_tag
        changed = bool(extra or dropped) or any(a.new is not None for a in attrs)
        if not changed:
            return m.group(0)
        pieces = []
        for a in attrs:
            if a.name.lower() in dropped:
                continue
            pieces.append(f'{a.name}="{a.new}"' if a.new is not None else a.raw)
        pieces.extend(extra)
        return "<" + m.group(1) + "".join(" " + p for p in pieces) + (" /" if m.group(3) else "") + ">"

    def _rewrite_url(self, a: Attr, doc: Path) -> None:
        res = self.resolve(a.value, doc.parent, doc, "resource")
        if res[0] == "local":
            a.new = self.data_uri(res[1])

    def _rewrite_srcset(self, a: Attr, doc: Path) -> None:
        items, changed = [], False
        for item in htmllib.unescape(a.value).split(","):
            bits = item.split()
            if not bits:
                continue
            res = self.resolve(bits[0], doc.parent, doc, "resource")
            if res[0] == "local":
                bits[0] = self.data_uri(res[1])
                changed = True
            items.append(" ".join(bits))
        if changed:
            a.new = ", ".join(items)

    def _named_pages(self, code: str, doc: Path) -> None:
        """Warn about a local page an inline script names: it is not followed."""
        for m in re.finditer(r"""["'`]([\w./%-]+\.html?)(?:[#?][^"'`]*)?["'`]""", code):
            ref = m.group(1)
            if "//" in ref:
                continue
            target = (doc.parent / ref).resolve()
            if target.is_file() and target != doc.resolve():
                msg = (f"{self.rel(doc)}: a script names {self.rel(target)}; URLs built in JavaScript "
                       "are not followed, so the send copy will not find it")
                if msg not in self.result.warnings:
                    self.result.warnings.append(msg)

    # ---- payloads -----------------------------------------------------------
    def payload(self, target: Path, doc: Path, payloads: dict) -> str:
        """Id of the payload block for `target` inside the document being built."""
        if target in payloads:
            return payloads[target][0]
        if target not in self._pages:
            if target in self._stack:
                self.error(doc, f"page cycle through {self.rel(target)}")
                self._pages[target] = b""
            else:
                self._pages[target] = self.page(target)
        pid = f"bundle-{len(payloads) + 1}"
        payloads[target] = (pid, self._pages[target])
        return pid

    def page(self, path: Path) -> bytes:
        self._stack.append(path)
        try:
            text = self.read(path).decode("utf-8")
            return self.document(text, path).encode("utf-8")
        finally:
            self._stack.pop()

    def document(self, text: str, path: Path) -> str:
        payloads: dict[Path, tuple[str, bytes]] = {}
        html = self.markup(text, path, payloads)
        html = self.embed_fonts(html, path)
        if payloads:
            blocks = "\n".join(
                f'<script type="text/plain" class="bundle-payload" id="{pid}" data-source="{self.rel(p)}" data-encoding="base64">'
                f'{base64.b64encode(data).decode("ascii")}</script>'
                for p, (pid, data) in payloads.items())
            extra = blocks + ("\n" + LOADER if LOADER_VERSION not in html else "") + "\n"
            idx = html.lower().rfind("</body>")
            html = html[:idx] + extra + html[idx:] if idx >= 0 else html + "\n" + extra
        return html

    # ---- fonts --------------------------------------------------------------
    def _load_embed(self):
        if self._embed is None:
            spec = importlib.util.spec_from_file_location("bundle_embed_fonts", HERE / "embed-fonts.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            self._embed = mod
        return self._embed

    def find_design(self, path: Path) -> Path | None:
        return self.design or find_design(path)

    def embed_fonts(self, html: str, path: Path) -> str:
        design = self.find_design(path)
        if design is None:
            return html
        embed = self._load_embed()
        if design not in self._families:
            try:
                self._families[design] = embed.collect_families(design)
            except SystemExit as exc:
                self.result.notes.append(f"fonts skipped: {exc}")
                self._families[design] = {}
        declared = set()
        for face in FONT_FACE_RE.findall(html):
            for fam in re.findall(r"font-family\s*:\s*([^;}]+)", face, re.I):
                declared.add(fam.strip().strip("\"'").lower())
        probe = B64_RE.sub("", FONT_FACE_RE.sub("", html)).lower()
        wanted = {fam: ws for fam, ws in self._families[design].items()
                  if fam.lower() not in declared and fam.lower() in probe}
        if not wanted:
            return html
        css = embed.build_font_face_css(wanted, self.font_dirs)
        if not css:
            return html
        self.result.notes.append("fonts embedded for " + path.name + ": " + ", ".join(sorted(wanted)))
        block = f"<style data-bundle-fonts>\n{css}</style>\n"
        m = re.search(r"</head\s*>", html, re.I)
        return html[:m.start()] + block + html[m.start():] if m else block + html

    # ---- driver -------------------------------------------------------------
    def run(self) -> Result:
        self.result.sources.clear()
        try:
            text = self.read(self.entry).decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.result.errors.append(f"{self.entry.name}: cannot read entry: {exc}")
            return self.result
        self._stack.append(self.entry)
        out = self.document(text, self.entry)
        # Safety net on the finished text: no loading reference may survive.
        for problem in leftover_refs(out, self.allow_remote):
            self.result.errors.append(f"output still references {problem}")
        self.result.html = out
        return self.result


def _open_tags(html: str):
    """Start tags outside comments, script bodies and style bodies (script start tags included)."""
    last = 0
    for seg in SEGMENT_RE.finditer(html):
        yield from TAG_RE.finditer(html[last:seg.start()])
        if seg.group(0)[:7].lower() == "<script":
            m = TAG_RE.match(seg.group(0))
            if m:
                yield m
        last = seg.end()
    yield from TAG_RE.finditer(html[last:])


def leftover_refs(html: str, allow_remote: bool = False) -> list[str]:
    """References in the finished page that would load something from outside it."""
    html = re.sub(r'<script type="text/plain" class="bundle-payload"[^>]*>[^<]*</script>', "", html)
    found = []

    def check(value: str, anchor=False):
        v = htmllib.unescape(value).strip()
        low = v.lower()
        if not v or v.startswith("#") or low.startswith(SKIP_PREFIXES):
            return
        remote = low.startswith(("http:", "https:", "//"))
        if remote and (allow_remote or anchor):
            return
        if anchor and re.match(r"^[a-z][a-z0-9+.-]*:", low):
            return
        found.append(v[:80])

    for m in _open_tags(html):
        name = m.group(1).lower()
        attrs = Bundler._attrs(m.group(2))
        rels = set()
        if name == "link":
            rels = set(((next((x.value for x in attrs if x.name.lower() == "rel"), "")) or "").lower().split())
        for a in attrs:
            key = a.name.lower()
            if a.value is None:
                continue
            if name == "a" and key == "href":
                check(a.value, anchor=True)
            elif name == "iframe" and key in ("src", "data-src"):
                check(a.value)
            elif name == "script" and key == "src":
                check(a.value)
            elif name == "link" and key == "href":
                if rels & LOADING_RELS:
                    check(a.value)
            elif key in URL_ATTRS.get(name, ()):
                if key in ("srcset", "imagesrcset"):
                    for item in a.value.split(","):
                        if item.split():
                            check(item.split()[0])
                else:
                    check(a.value)
    css_text = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style\s*>", html, re.S | re.I))
    css_text += "\n" + "\n".join(htmllib.unescape(v) for v in re.findall(r'\bstyle\s*=\s*"([^"]*)"', html, re.I))
    css_text = CSS_COMMENT_RE.sub("", css_text)
    for m in CSS_URL_RE.finditer(css_text):
        check(next(g for g in m.groups() if g is not None))
    for m in CSS_IMPORT_RE.finditer(css_text):
        check(m.group(2))
    return found


def bundle(entry: Path, pages: bool = False, allow_remote: bool = False, design: Path | None = None,
           font_dirs: Sequence[Path] = ()) -> Result:
    return Bundler(Path(entry), pages, allow_remote, design, font_dirs).run()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fold a page and everything it loads into one file")
    ap.add_argument("entry", help="entry HTML page")
    ap.add_argument("--out", required=True, help="output file")
    ap.add_argument("--pages", action="store_true", help="bundle linked local HTML pages as payloads")
    ap.add_argument("--allow-remote", action="store_true", help="keep remote resource URLs instead of refusing")
    ap.add_argument("--manifest", help="write the sha256 list here instead of stderr")
    ap.add_argument("--design", help="DESIGN.md naming the fonts to embed (default: nearest above the entry)")
    ap.add_argument("--font-dir", action="append", default=[], metavar="DIR",
                    help="extra font directory for embed-fonts.py, searched first")
    args = ap.parse_args(argv)

    entry = Path(args.entry)
    if not entry.is_file():
        print(f"bundle: ERROR input file does not exist: {entry}", file=sys.stderr)
        return 1
    result = bundle(entry, args.pages, args.allow_remote, Path(args.design) if args.design else None,
                    [Path(d) for d in args.font_dir])
    for note in result.notes:
        print(f"bundle: {note}", file=sys.stderr)
    for warning in result.warnings:
        print(f"bundle: WARNING {warning}", file=sys.stderr)
    if result.errors:
        for err in result.errors:
            print(f"bundle: ERROR {err}", file=sys.stderr)
        print(f"bundle: {len(result.errors)} problem(s), nothing written", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.html, encoding="utf-8")
    lines = [f"{digest}  {rel}" for rel, digest in result.sources.items()]
    if args.manifest:
        Path(args.manifest).write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        print("bundle: sha256 of every inlined source", file=sys.stderr)
        for ln in lines:
            print(ln, file=sys.stderr)
    size = out.stat().st_size
    print(f"bundle: wrote {out} ({size:,} bytes, {len(lines)} sources)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
