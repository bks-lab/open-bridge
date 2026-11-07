#!/usr/bin/env python3
"""Render an html-slides deck to an editable 16:9 PowerPoint file (optional).

Hybrid by default: every slide becomes a full-slide picture of the rendered slide
with its text left out, and on top of it the text as native, editable PowerPoint
text boxes and every HTML table as a native PowerPoint table. Images, SVG
diagrams, gradients, cards and glows keep their exact look because they are part
of the picture; the words stay editable. `--mode image` writes the plain
screenshot only (pixel exact, nothing editable).

Every slide is exported in its end state, like print: reveals shown, `motion`
counters at their final number, `steps` items all visible, stages loaded.
Speaker notes (`aside.notes`) go to the notes page of their slide.

Usage:
    uv run --with python-pptx --with playwright python render-pptx.py deck.html deck.pptx
        [--mode hybrid|image] [--size 1920x1080|1280x720] [--theme light|dark]
        [--lang de|en] [--track NAME] [--font-fallback "Montserrat=Arial,Heebo=Arial"]

Needs python-pptx and playwright with its chromium (`playwright install chromium`).
Exit codes: 0 written, 1 render failed, 2 wrong usage or a missing dependency.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

SLIDE_W_EMU = 12192000  # 13.333 in
SLIDE_H_EMU = 6858000   # 7.5 in
SIZES = {"1920x1080": (1920, 1080), "1280x720": (1280, 720)}
INSTALL = ("render-pptx: needs python-pptx and playwright (chromium); run it as "
           "`uv run --with python-pptx --with playwright python render-pptx.py IN OUT` "
           "after `playwright install chromium`")


def die(message: str, code: int = 2) -> None:
    print(message, file=sys.stderr)
    sys.exit(code)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="render-pptx.py", description="html-slides deck to an editable PPTX")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--mode", choices=("hybrid", "image"), default="hybrid",
                   help="hybrid: picture background plus editable text and tables (default); image: screenshots only")
    p.add_argument("--size", choices=sorted(SIZES), default="1920x1080", help="browser viewport the slides render at")
    p.add_argument("--theme", choices=("light", "dark"), help="theme to render (default: as the deck opens, light)")
    p.add_argument("--lang", choices=("de", "en"), help="language of a bilingual deck")
    p.add_argument("--track", help="export only this track (default: every slide, like print)")
    p.add_argument("--font-fallback", default="",
                   help='replace font families in the PPTX, e.g. "Montserrat=Arial,Heebo=Arial"')
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        sys.exit(2 if exc.code else 0)
    args.fallback = {}
    for pair in filter(None, (s.strip() for s in args.font_fallback.split(","))):
        if "=" not in pair:
            die("render-pptx: --font-fallback takes NAME=NAME pairs, got %r" % pair)
        a, b = (s.strip() for s in pair.split("=", 1))
        args.fallback[a.lower()] = b
    return args


# --------------------------------------------------------------------------- page side
# One function per slide, run in the page. It returns the slide rect, its text blocks,
# tables and notes, and (hybrid mode) makes that text transparent for the screenshot.
EXTRACT_JS = r"""
({index, hide}) => {
  const D = window.SlideDeck;
  const slide = D.slides()[index];
  const sr = slide.getBoundingClientRect();
  const root = document.documentElement;
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = 'rgba(0,0,0,0)'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], +(d[3] / 255).toFixed(3)];
  };
  const accent = getComputedStyle(root).getPropertyValue('--accent').trim() || '#000';
  const COLOR_RE = /(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color)\([^()]*\)|#[0-9a-fA-F]{3,8}\b/;
  const SKIP = 'aside.notes, svg, iframe, canvas, video, audio, script, style, noscript, template, select, textarea, input, [aria-hidden="true"], .deck-print-notes, .stage';
  const zoomOf = (el) => (typeof el.currentCSSZoom === 'number' ? el.currentCSSZoom : 1);
  const visible = (el) => el.checkVisibility ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) : true;
  const isBlock = (el) => { const d = getComputedStyle(el).display; return d !== 'inline' && d !== 'contents'; };
  const blockOf = (node) => { let e = node.parentElement; while (e && e !== slide && !isBlock(e)) e = e.parentElement; return e || slide; };
  const opacityOf = (el) => { let o = 1; for (let e = el; e && e !== document.body; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity) || 0; return o; };
  const inside = (r) => r.width > 0 && r.height > 0 && r.right > sr.left && r.left < sr.right && r.bottom > sr.top && r.top < sr.bottom;
  const gradOf = (cs) => {
    const clip = (cs.webkitBackgroundClip || '') + ' ' + (cs.backgroundClip || '');
    if (!/text/.test(clip) || !cs.backgroundImage || cs.backgroundImage === 'none') return null;
    const m = COLOR_RE.exec(cs.backgroundImage);
    return rgba(m ? m[0] : accent);
  };
  const textColor = (el, cs) => {
    let g = gradOf(cs);
    if (g) return { c: g, clip: el };
    let c = rgba(cs.webkitTextFillColor || cs.color);
    if (c[3] > 0) return { c, clip: null };
    // transparent fill: the paint comes from an ancestor's background clipped to the text
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      g = gradOf(getComputedStyle(e));
      if (g) return { c: g, clip: e };
      if (e === slide) break;
    }
    return { c: rgba(accent), clip: null };
  };
  const transform = (t, cs) => {
    const tt = cs.textTransform;
    if (tt === 'lowercase') return t.toLowerCase();
    if (tt === 'capitalize') return t.replace(/(^|\s)(\S)/g, (a, s, ch) => s + ch.toUpperCase());
    return t;
  };
  const styleOf = (el) => {
    const cs = getComputedStyle(el), z = zoomOf(el), col = textColor(el, cs);
    const fam = cs.fontFamily.split(',').map((f) => f.trim().replace(/^["']|["']$/g, ''));
    const ls = parseFloat(cs.letterSpacing);
    return {
      family: fam, size: parseFloat(cs.fontSize) * z, weight: parseInt(cs.fontWeight, 10) || 400,
      italic: cs.fontStyle === 'italic' || cs.fontStyle.startsWith('oblique'),
      underline: /underline/.test(cs.textDecorationLine || ''),
      color: col.c.slice(0, 3), alpha: +(col.c[3] * opacityOf(el)).toFixed(3), clip: col.clip,
      spacing: isNaN(ls) ? 0 : ls * z,
      caps: cs.textTransform === 'uppercase' ? 'all' : (/small-caps/.test(cs.fontVariantCaps || cs.fontVariant || '') ? 'small' : null),
    };
  };

  // ---- walk the slide: text nodes grouped by their nearest block element
  const blocks = new Map(), order = [], wrapped = [], clipped = new Set();
  const walker = document.createTreeWalker(slide, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (n.nodeType === 1) {
        if (n.matches(SKIP) || n.tagName === 'TABLE') return NodeFilter.FILTER_REJECT;
        return n.tagName === 'BR' ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      }
      return /\S/.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const range = document.createRange();
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    if (t.nodeType === 1) { const bb = blocks.get(blockOf(t)); if (bb) bb.tokens.push({ br: true }); continue; }
    const parent = t.parentElement;
    if (!parent || !visible(parent)) continue;
    const cs = getComputedStyle(parent);
    const st = styleOf(parent);
    if (st.alpha < 0.02) continue;
    range.selectNodeContents(t);
    const all = range.getBoundingClientRect();
    if (!inside(all)) continue;
    const blk = blockOf(t);
    let b = blocks.get(blk);
    if (!b) { b = { el: blk, tokens: [] }; blocks.set(blk, b); order.push(b); }
    const pre = /^(pre|pre-wrap|break-spaces|pre-line)$/.test(cs.whiteSpace);
    const text = t.nodeValue;
    const re = /\s+|\S+/g; let m;
    const measure = (from, len) => {
      range.setStart(t, from); range.setEnd(t, from + len);
      const rs = range.getClientRects(); if (!rs.length) return null;
      const r = rs[0], last = rs[rs.length - 1];
      return { l: r.left, t: r.top, r: last.right, b: r.bottom, h: r.height };
    };
    while ((m = re.exec(text))) {
      const tok = m[0];
      if (/^\s/.test(tok)) {
        if (!pre) { b.tokens.push({ space: ' ', st }); continue; }
        // preformatted: newlines break the line, the spaces keep their width (indentation)
        const parts = tok.split('\n');
        let at = m.index;
        parts.forEach((part, k) => {
          if (k) { b.tokens.push({ br: true }); at += 1; }
          if (part && cs.whiteSpace !== 'pre-line') {
            const r = measure(at, part.length);
            if (r) b.tokens.push({ text: part, st, r, ws: true });
          }
          at += part.length;
        });
        continue;
      }
      const r = measure(m.index, tok.length);
      if (r) b.tokens.push({ text: transform(tok, cs), st, r });
    }
    if (st.clip) clipped.add(st.clip);
    wrapped.push(t);
  }
  // ---- tokens into lines, lines into a box
  const out = [], ids = new Map();
  const pid = (e) => { if (!ids.has(e)) ids.set(e, ids.size + 1); return ids.get(e); };
  for (const b of order) {
    const cs = getComputedStyle(b.el), z = zoomOf(b.el);
    const fs = parseFloat(cs.fontSize) * z;
    let lh = parseFloat(cs.lineHeight); lh = isNaN(lh) ? fs * 1.2 : lh * z;
    const lines = [[]]; let prev = null, pendingSpace = null;
    for (const tk of b.tokens) {
      if (tk.br) { lines.push([]); prev = null; pendingSpace = null; continue; }
      if (tk.space != null) { if (lines[lines.length - 1].length) pendingSpace = tk; continue; }
      // a soft wrap: the browser put this word on the next line
      if (!tk.ws && prev && tk.r.t > prev.r.t + prev.r.h * 0.5) { lines.push([]); pendingSpace = null; }
      const cur = lines[lines.length - 1];
      if (cur.length && pendingSpace) cur.push({ text: ' ', st: pendingSpace.st });
      // no space in the source but a visible gap (flex gap, margin): keep the words apart
      else if (cur.length && !tk.ws && prev && !prev.ws && tk.r.l - prev.r.r > 0.25 * tk.st.size) cur.push({ text: ' ', st: tk.st });
      pendingSpace = null;
      cur.push(tk);
      prev = tk;
    }
    while (lines.length && !lines[lines.length - 1].length) lines.pop();
    while (lines.length && !lines[0].length) lines.shift();
    if (!lines.length) continue;
    let L = Infinity, R = -Infinity, T = Infinity, B = -Infinity;
    const lineBoxes = lines.map((ln) => {
      let l = Infinity, r = -Infinity, t = Infinity, bt = -Infinity;
      ln.forEach((tk) => { if (!tk.r) return; l = Math.min(l, tk.r.l); r = Math.max(r, tk.r.r); t = Math.min(t, tk.r.t); bt = Math.max(bt, tk.r.b); });
      return { l, r, t, b: bt };
    });
    lineBoxes.forEach((x) => { if (x.l < Infinity) { L = Math.min(L, x.l); R = Math.max(R, x.r); T = Math.min(T, x.t); B = Math.max(B, x.b); } });
    const first = lineBoxes.find((x) => x.t < Infinity);
    const glyphH = first ? first.b - first.t : fs;
    const top = T - Math.max(0, (lh - glyphH) / 2);
    const bottom = top + lh * lines.length;
    let align = cs.textAlign;
    if (align === 'start' || align === 'justify' || align === '-webkit-auto') align = cs.direction === 'rtl' ? 'right' : 'left';
    if (align === 'end') align = cs.direction === 'rtl' ? 'left' : 'right';
    if (align === '-webkit-center') align = 'center';
    const li = b.el.tagName === 'LI' ? b.el : null;
    let bullet = null;
    if (li && cs.display === 'list-item' && cs.listStyleType !== 'none') {
      bullet = { type: cs.listStyleType, n: [].indexOf.call(li.parentElement.children, li) + 1,
                 start: parseInt(li.parentElement.getAttribute('start'), 10) || 1 };
      if (hide) li.setAttribute('data-pptx-marker', '');
    }
    out.push({
      tag: b.el.tagName.toLowerCase(), parent: pid(b.el.parentElement),
      align, lineHeight: lh, fontSize: fs, bullet,
      box: { l: L - sr.left, r: R - sr.left, t: top - sr.top, b: bottom - sr.top },
      lines: lines.map((ln) => ln.map((tk) => ({ text: tk.text, st: tk.st }))),
    });
  }

  // ---- tables
  // the cell text as written (innerText would apply text-transform), <br> and blocks as line breaks
  const cellText = (td) => {
    let s = '';
    const w = document.createTreeWalker(td, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (n.nodeType === 1) { if (n.tagName === 'BR' || (isBlock(n) && s)) s += '\n'; continue; }
      if (visible(n.parentElement)) s += n.nodeValue.replace(/\s+/g, ' ');
    }
    return s.replace(/ +/g, ' ').replace(/ *\n+ */g, '\n').trim();
  };
  const tables = [];
  [].forEach.call(slide.querySelectorAll('table'), (tb) => {
    if (tb.parentElement.closest(SKIP) || !visible(tb)) return;
    const r = tb.getBoundingClientRect(); if (!inside(r)) return;
    const rows = [].slice.call(tb.rows);
    const grid = [], cells = [];
    rows.forEach((tr, ri) => {
      grid[ri] = grid[ri] || [];
      let ci = 0;
      [].forEach.call(tr.cells, (td) => {
        while (grid[ri][ci]) ci++;
        const cs = getComputedStyle(td), z = zoomOf(td);
        const leaf = (() => { const w = document.createTreeWalker(td, NodeFilter.SHOW_TEXT); for (let n = w.nextNode(); n; n = w.nextNode()) if (/\S/.test(n.nodeValue) && visible(n.parentElement)) return n.parentElement; return td; })();
        const st = styleOf(leaf);
        let bg = rgba(cs.backgroundColor);
        if (bg[3] === 0) bg = rgba(getComputedStyle(tr).backgroundColor);
        if (bg[3] === 0 && tr.parentElement) bg = rgba(getComputedStyle(tr.parentElement).backgroundColor);
        const bw = parseFloat(cs.borderBottomWidth) * z;
        const txt = transform(cellText(td), getComputedStyle(leaf));
        let align = cs.textAlign; if (align === 'start' || align === 'justify') align = 'left'; if (align === 'end') align = 'right';
        cells.push({ w: td.getBoundingClientRect().width, r: ri, c: ci, rs: td.rowSpan || 1, cs: td.colSpan || 1, text: txt, st, th: td.tagName === 'TH',
          align, valign: cs.verticalAlign, bg: bg[3] > 0 ? bg : null,
          pad: ['Left', 'Right', 'Top', 'Bottom'].map((s) => parseFloat(cs['padding' + s]) * z),
          border: bw > 0 && cs.borderBottomStyle !== 'none' ? { w: bw, c: rgba(cs.borderBottomColor) } : null });
        for (let a = 0; a < (td.rowSpan || 1); a++) for (let k = 0; k < (td.colSpan || 1); k++) {
          grid[ri + a] = grid[ri + a] || []; grid[ri + a][ci + k] = true;
        }
        ci += td.colSpan || 1;
      });
    });
    const ncols = Math.max(0, ...grid.map((g) => g.length));
    const colW = new Array(ncols).fill(0);
    cells.forEach((c) => { if (c.cs === 1) colW[c.c] = Math.max(colW[c.c], c.w); });
    const known = colW.reduce((a, b) => a + b, 0), missing = colW.filter((w) => !w).length;
    for (let i = 0; i < ncols; i++) if (!colW[i]) colW[i] = missing ? Math.max(1, (r.width - known) / missing) : 1;
    tables.push({ box: { l: r.left - sr.left, t: r.top - sr.top, w: r.width, h: r.height },
      cols: colW, rows: rows.map((tr) => tr.getBoundingClientRect().height), ncols,
      cells });
    if (hide) tb.setAttribute('data-pptx-hide', '');
  });

  // ---- notes, in the active language
  let notes = '';
  const aside = slide.querySelector('aside.notes');
  if (aside) {
    const lang = (D.state && D.state().lang) || 'en', other = lang === 'de' ? 'en' : 'de';
    const copy = aside.cloneNode(true);
    copy.querySelectorAll('[data-' + other + ']:not([data-' + lang + '])').forEach((e) => e.remove());
    const parts = [];
    const blocksIn = copy.querySelectorAll('p, li, h1, h2, h3, h4, div:not(:has(p, li, div))');
    if (blocksIn.length) blocksIn.forEach((e) => { const s = e.textContent.replace(/\s+/g, ' ').trim(); if (s) parts.push((e.tagName === 'LI' ? '- ' : '') + s); });
    else parts.push(copy.textContent.replace(/\s+/g, ' ').trim());
    notes = parts.join('\n');
  }

  // ---- hide what the PPTX rebuilds, so the picture does not carry it twice
  if (hide) {
    wrapped.forEach((t) => {
      if (!t.parentNode) return;
      const w = document.createElement('pptx-t');
      t.parentNode.insertBefore(w, t); w.appendChild(t);
    });
    clipped.forEach((e) => e && e.setAttribute('data-pptx-clip', ''));
  }
  const clean = (st) => { const { clip, ...rest } = st; return rest; };
  out.forEach((o) => o.lines.forEach((ln) => ln.forEach((tk) => { tk.st = clean(tk.st); })));
  tables.forEach((tb) => tb.cells.forEach((c) => { c.st = clean(c.st); }));
  return { w: sr.width, h: sr.height, blocks: out, tables, notes };
}
"""

HIDE_CSS = """
pptx-t { color: transparent !important; -webkit-text-fill-color: transparent !important;
         text-shadow: none !important; -webkit-text-stroke: 0 !important; }
[data-pptx-clip] { background: none !important; }
[data-pptx-hide] { visibility: hidden !important; }
li[data-pptx-marker]::marker { color: transparent !important; }
"""

# End states for the screenshot: steps shown, reveals in, no engine chrome over the slide.
END_STATE_CSS = """
.slide .step-hidden, .slide .step-shown, .slide .step-past, .code-line {
  visibility: visible !important; opacity: 1 !important; transform: none !important; transition: none !important; }
.code-line.is-on { box-shadow: none !important; }
.slide .reveal { opacity: 1 !important; transform: none !important; transition: none !important; }
*, *::before, *::after { transition-duration: 0s !important; animation-delay: 0s !important; caret-color: transparent !important; }
body > :not(.deck) { visibility: hidden !important; }
.deck-zoom-hint, .deck-hints, .deck-progress, .deck-dots, .deck-counter, .deck-track, .deck-help, .deck-notes { display: none !important; }
"""


def load_deck(page, src: Path, args):
    page.goto(src.as_uri(), wait_until="load")
    page.wait_for_function("() => window.SlideDeck && typeof window.SlideDeck.count === 'function'", timeout=15000)
    page.evaluate(
        """async ({theme, lang, track}) => {
          const D = window.SlideDeck, root = document.documentElement;
          if (theme) { root.classList.remove('theme-light', 'theme-dark'); root.classList.add('theme-' + theme); }
          if (lang && D.setLang) D.setLang(lang);
          if (D.setTrack) D.setTrack(track || 'all');
          document.querySelectorAll('.slide').forEach((s) => s.classList.add('visible'));
          document.querySelectorAll('img[loading="lazy"]').forEach((img) => { img.loading = 'eager'; });
          window.dispatchEvent(new Event('beforeprint'));
          await Promise.all(Array.from(document.images).map((img) => (img.complete ? 0
            : new Promise((res) => { img.onload = img.onerror = res; setTimeout(res, 8000); }))));
          if (document.fonts && document.fonts.ready) await document.fonts.ready;
          const frames = Array.from(document.querySelectorAll('iframe'));
          await Promise.all(frames.map((f) => new Promise((res) => {
            let d = null; try { d = f.contentDocument; } catch (e) { return res(); }
            if (d && d.readyState === 'complete' && d.URL !== 'about:blank') return res();
            f.addEventListener('load', () => res(), { once: true }); setTimeout(res, 8000);
          })));
          await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
        }""",
        {"theme": args.theme, "lang": args.lang, "track": args.track},
    )
    page.add_style_tag(content=END_STATE_CSS)
    return page.evaluate("() => window.SlideDeck.count()")


def settle(page, index: int):
    page.evaluate(
        """async (i) => {
          window.SlideDeck.goTo(i, true);
          const s = window.SlideDeck.slides()[i];
          if (s) s.scrollIntoView({ behavior: 'instant', block: 'start' });
          await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
          await new Promise((res) => setTimeout(res, 60));
        }""",
        index,
    )


def screenshot(page, index: int) -> bytes:
    box = page.evaluate(
        "(i) => { const r = window.SlideDeck.slides()[i].getBoundingClientRect(); return {x: r.left, y: r.top, width: r.width, height: r.height}; }",
        index,
    )
    return page.screenshot(clip=box, type="png", animations="disabled")


# --------------------------------------------------------------------------- pptx side
GENERIC = {"sans-serif": "Arial", "serif": "Times New Roman", "monospace": "Courier New",
           "system-ui": "Arial", "ui-sans-serif": "Arial", "ui-serif": "Times New Roman",
           "ui-monospace": "Courier New", "cursive": "Comic Sans MS", "fantasy": "Impact",
           "-apple-system": "Arial", "blinkmacsystemfont": "Arial", "emoji": "Segoe UI Emoji",
           "apple color emoji": "Segoe UI Emoji", "math": "Cambria Math"}
BULLETS = {"disc": "•", "circle": "◦", "square": "▪"}
NUMBERED = {"decimal": "arabicPeriod", "decimal-leading-zero": "arabicPeriod", "lower-alpha": "alphaLcPeriod",
            "lower-latin": "alphaLcPeriod", "upper-alpha": "alphaUcPeriod", "upper-latin": "alphaUcPeriod",
            "lower-roman": "romanLcPeriod", "upper-roman": "romanUcPeriod"}


class Builder:
    def __init__(self, args, px_w: int):
        from pptx import Presentation
        from pptx.util import Emu

        self.args = args
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Emu(SLIDE_W_EMU), Emu(SLIDE_H_EMU)
        self.layout = self.prs.slide_layouts[6]  # blank
        self.px_w = px_w
        self.fonts: dict[str, int] = {}
        self.n_text = self.n_tables = 0

    def emu(self, px: float) -> int:
        return int(round(px * self.scale))

    def pt(self, px: float) -> float:
        return px * self.scale / 12700

    def family(self, families: list[str]) -> str:
        name = None
        for f in families:
            if f and f.lower() not in GENERIC:
                name = f
                break
        if name is None:
            name = GENERIC.get((families[0] if families else "sans-serif").lower(), "Arial")
        self.fonts[name] = self.fonts.get(name, 0) + 1
        return self.args.fallback.get(name.lower(), name)

    def add_slide(self, png: bytes, data: dict | None):
        from pptx.util import Emu

        slide = self.prs.slides.add_slide(self.layout)
        slide.shapes.add_picture(io.BytesIO(png), 0, 0, Emu(SLIDE_W_EMU), Emu(SLIDE_H_EMU))
        if data:
            self.scale = SLIDE_W_EMU / data["w"]
            self.text_boxes(slide, data["blocks"])
            for t in data["tables"]:
                self.table(slide, t)
            if data["notes"]:
                slide.notes_slide.notes_text_frame.text = data["notes"]
        return slide

    # ---- runs
    def run_style(self, run, st):
        from pptx.dml.color import RGBColor
        from pptx.util import Pt

        f = run.font
        f.name = self.family(st["family"])
        f.size = Pt(round(self.pt(st["size"]) * 2) / 2)
        f.bold = st["weight"] >= 600
        f.italic = bool(st["italic"])
        if st["underline"]:
            f.underline = True
        f.color.rgb = RGBColor(*st["color"])
        rpr = run._r.get_or_add_rPr()
        if st["alpha"] < 0.999:
            srgb = rpr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
            alpha = srgb.makeelement(qn("a:alpha"), {"val": str(int(st["alpha"] * 100000))})
            srgb.append(alpha)
        if st.get("caps"):
            rpr.set("cap", st["caps"])  # text stays as written, PowerPoint shows it in capitals
        if abs(st["spacing"]) > 0.05:
            rpr.set("spc", str(int(round(self.pt(st["spacing"]) * 100))))
        # east asian and complex script slots follow the latin font
        for tag in ("a:ea", "a:cs"):
            el = rpr.makeelement(qn(tag), {"typeface": f.name})
            rpr.append(el)

    def fill_paragraph(self, para, block):
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Pt

        para.alignment = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(block["align"], PP_ALIGN.LEFT)
        para.line_spacing = Pt(round(self.pt(block["lineHeight"]), 1))
        for i, line in enumerate(block["lines"]):
            if i:
                para.add_line_break()
            merged = []  # one run per stretch of equal style, not one per word
            for tok in line:
                if merged and merged[-1]["st"] == tok["st"]:
                    merged[-1]["text"] += tok["text"]
                else:
                    merged.append({"text": tok["text"], "st": tok["st"]})
            for tok in merged:
                r = para.add_run()
                r.text = tok["text"]
                self.run_style(r, tok["st"])

    def bullet(self, para, block, indent_px):
        ppr = para._p.get_or_add_pPr()
        ind = self.emu(indent_px)
        ppr.set("marL", str(ind))
        ppr.set("indent", str(-ind))
        b = block["bullet"]
        first = block["lines"][0][0]["st"] if block["lines"] and block["lines"][0] else None
        if first:
            clr = ppr.makeelement(qn("a:buClr"), {})
            clr.append(clr.makeelement(qn("a:srgbClr"), {"val": "%02X%02X%02X" % tuple(first["color"])}))
            ppr.append(clr)
        if b["type"] in NUMBERED:
            ppr.append(ppr.makeelement(qn("a:buAutoNum"), {"type": NUMBERED[b["type"]], "startAt": str(b["start"])}))
        else:
            ppr.append(ppr.makeelement(qn("a:buChar"), {"char": BULLETS.get(b["type"], "•")}))

    def text_boxes(self, slide, blocks):
        # consecutive siblings of one kind stacked on one edge (list items, paragraphs of a
        # card, lines of a code block): one text box with a paragraph each
        groups = []
        for b in blocks:
            g = groups[-1] if groups else None
            if g and self.stacks(g[-1], b):
                g.append(b)
            else:
                groups.append([b])
        for g in groups:
            self.text_box(slide, g)

    @staticmethod
    def stacks(a, b) -> bool:
        if a["parent"] != b["parent"] or a["tag"] != b["tag"] or a["align"] != b["align"]:
            return False
        if bool(a["bullet"]) != bool(b["bullet"]) or b["box"]["t"] < a["box"]["b"] - 2:
            return False
        if b["box"]["t"] - a["box"]["b"] > 2.5 * max(a["lineHeight"], b["lineHeight"]):
            return False
        edge = {"center": lambda x: (x["l"] + x["r"]) / 2, "right": lambda x: x["r"]}.get(a["align"], lambda x: x["l"])
        return abs(edge(a["box"]) - edge(b["box"])) < (6 if a["align"] == "center" else 2.5)

    def text_box(self, slide, group):
        from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
        from pptx.util import Pt

        indent = max((b["fontSize"] * 1.25 if b["bullet"] else 0) for b in group)
        l = min(b["box"]["l"] for b in group) - indent
        r = max(b["box"]["r"] for b in group)
        t = group[0]["box"]["t"]
        btm = group[-1]["box"]["b"]
        w = r - l
        slack = max(6.0, w * 0.06)
        align = group[0]["align"]
        if align == "center":
            l -= slack / 2
        elif align == "right":
            l -= slack
        w += slack
        box = slide.shapes.add_textbox(self.emu(l), self.emu(t), self.emu(w), self.emu(btm - t))
        tf = box.text_frame
        tf.word_wrap = False
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.TOP
        prev = None
        for i, b in enumerate(group):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            self.fill_paragraph(para, b)
            if b["bullet"]:
                self.bullet(para, b, indent)
            if prev is not None:
                para.space_before = Pt(round(max(0.0, self.pt(b["box"]["t"] - prev["box"]["b"])), 1))
            prev = b
        self.n_text += 1

    # ---- tables
    def table(self, slide, t):
        from pptx.dml.color import RGBColor
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Emu

        nrows, ncols = len(t["rows"]), t["ncols"]
        if not nrows or not ncols:
            return
        b = t["box"]
        shape = slide.shapes.add_table(nrows, ncols, self.emu(b["l"]), self.emu(b["t"]), self.emu(b["w"]), self.emu(b["h"]))
        tbl = shape.table
        tbl.first_row = tbl.horz_banding = tbl.first_col = tbl.last_row = tbl.last_col = tbl.vert_banding = False
        # no table style: the cells carry their own fills and lines
        tbl_pr = shape._element.graphic.graphicData.tbl.tblPr
        for child in list(tbl_pr):
            if child.tag == qn("a:tableStyleId"):
                tbl_pr.remove(child)
        tbl_pr.append(tbl_pr.makeelement(qn("a:tableStyleId"), {}))
        tbl_pr[-1].text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # "No Style, No Grid"
        for i, w in enumerate(t["cols"]):
            tbl.columns[i].width = Emu(self.emu(w))
        for i, h in enumerate(t["rows"]):
            tbl.rows[i].height = Emu(self.emu(h))
        for c in t["cells"]:
            if c["rs"] > 1 or c["cs"] > 1:
                tbl.cell(c["r"], c["c"]).merge(tbl.cell(min(nrows, c["r"] + c["rs"]) - 1, min(ncols, c["c"] + c["cs"]) - 1))
        for row in range(nrows):
            for col in range(ncols):
                self.no_lines(tbl.cell(row, col))
        for c in t["cells"]:
            cell = tbl.cell(c["r"], c["c"])
            if c["bg"]:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(*c["bg"][:3])
                if c["bg"][3] < 0.999:
                    clr = cell._tc.tcPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
                    clr.append(clr.makeelement(qn("a:alpha"), {"val": str(int(c["bg"][3] * 100000))}))
            else:
                cell.fill.background()
            pl, pr, ptop, pb = c["pad"]
            cell.margin_left, cell.margin_right = Emu(self.emu(pl)), Emu(self.emu(pr))
            cell.margin_top, cell.margin_bottom = Emu(self.emu(ptop)), Emu(self.emu(pb))
            cell.vertical_anchor = {"top": MSO_ANCHOR.TOP, "bottom": MSO_ANCHOR.BOTTOM}.get(c["valign"], MSO_ANCHOR.MIDDLE)
            tf = cell.text_frame
            tf.word_wrap = True
            for i, line in enumerate(c["text"].split("\n") or [""]):
                para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                para.alignment = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(c["align"], PP_ALIGN.LEFT)
                run = para.add_run()
                run.text = line
                self.run_style(run, c["st"])
                if c["th"]:
                    run.font.bold = True
            if c["border"]:
                self.line(cell, "a:lnB", c["border"])
        self.n_tables += 1

    @staticmethod
    def no_lines(cell):
        tcpr = cell._tc.get_or_add_tcPr()
        for i, tag in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):  # schema order, first in tcPr
            ln = tcpr.makeelement(qn(tag), {"w": "0"})
            ln.append(ln.makeelement(qn("a:noFill"), {}))
            tcpr.insert(i, ln)

    def line(self, cell, tag, border):
        tcpr = cell._tc.get_or_add_tcPr()
        for old in tcpr.findall(qn(tag)):
            tcpr.remove(old)
        ln = tcpr.makeelement(qn(tag), {"w": str(max(1, self.emu(border["w"]))), "cmpd": "sng"})
        fill = ln.makeelement(qn("a:solidFill"), {})
        clr = fill.makeelement(qn("a:srgbClr"), {"val": "%02X%02X%02X" % tuple(border["c"][:3])})
        if border["c"][3] < 0.999:
            clr.append(clr.makeelement(qn("a:alpha"), {"val": str(int(border["c"][3] * 100000))}))
        fill.append(clr)
        ln.append(fill)
        # lnL, lnR, lnT, lnB keep their schema order ahead of the fill
        order = ["a:lnL", "a:lnR", "a:lnT", "a:lnB"]
        pos = sum(1 for child in tcpr if child.tag in {qn(o) for o in order[: order.index(tag)]})
        tcpr.insert(pos, ln)


def qn(tag: str) -> str:
    from pptx.oxml.ns import qn as _qn

    return _qn(tag)


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    src, out = Path(args.input).resolve(), Path(args.output).resolve()
    if not src.is_file():
        die("render-pptx: input not found: %s" % src)
    try:
        import pptx  # noqa: F401
        from playwright.sync_api import sync_playwright
    except ImportError:
        die(INSTALL)
    vw, vh = SIZES[args.size]
    scale = 2 if vw < 1920 else 1
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:  # the browser binary is not installed
            die("render-pptx: chromium not available (%s); run `playwright install chromium`"
                % str(exc).strip().splitlines()[0])
        try:
            ctx = browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=scale,
                                      color_scheme=args.theme or "light", reduced_motion="reduce")
            page = ctx.new_page()
            n = load_deck(page, src, args)
            builder = Builder(args, vw)
            if args.mode == "hybrid":
                page.add_style_tag(content=HIDE_CSS)
            for i in range(n):
                settle(page, i)
                data = page.evaluate(EXTRACT_JS, {"index": i, "hide": args.mode == "hybrid"}) if args.mode == "hybrid" else None
                if data is not None:
                    page.evaluate("() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)))")
                builder.add_slide(screenshot(page, i), data)
        except Exception as exc:
            print("render-pptx: render failed: %s" % exc, file=sys.stderr)
            return 1
        finally:
            browser.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    builder.prs.save(str(out))
    if builder.fonts:
        names = sorted(builder.fonts, key=lambda k: -builder.fonts[k])
        mapped = ["%s -> %s" % (f, args.fallback[f.lower()]) if f.lower() in args.fallback else f for f in names]
        print("render-pptx: fonts: %s (install them where the file is opened, or pass --font-fallback)"
              % ", ".join(mapped), file=sys.stderr)
    print("render-pptx: wrote %s (%d slides, %d text boxes, %d tables)"
          % (out, len(builder.prs.slides), builder.n_text, builder.n_tables))
    return 0


if __name__ == "__main__":
    sys.exit(main())
