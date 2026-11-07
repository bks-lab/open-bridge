#!/usr/bin/env python3
"""knowledge-pack.py: build, check, mark and embed a knowledge pack (knowledge-pack@1).

A knowledge pack is the small JSON a page or deck carries so that a term in the text
opens its knowledge in a panel beside it (html-canvas block `knowledge`,
`references/knowledge.md`). This script is the build side; the panel is the block
script in `assets/sections.js`.

    knowledge-pack.py build --terms terms.yaml --corpus docs/ [--corpus more/] --out pack.json
    knowledge-pack.py check pack.json
    knowledge-pack.py mark page.html --pack pack.json [--write] [--headings]
    knowledge-pack.py embed page.html --pack pack.json

`build` is the Markdown adapter: the term list says which terms exist (label, aliases,
type, summary, named relations); passages are the paragraphs of the corpus that
mention a term, neighbours the named relations first, then the terms that share a
paragraph with it (counted, most frequent first). Another source (a knowledge graph,
a search service) is a different adapter that writes the same JSON; `check` holds
every pack to the contract, whatever wrote it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

SCHEMA = "knowledge-pack@1"
MAX_TERMS = 60
MAX_SUMMARY = 400
MAX_PASSAGE = 280
MAX_PASSAGES = 4
MAX_NEIGHBOURS = 6
MAX_BYTES = 120_000

REGION_START = "<!-- knowledge-pack:start -->"
REGION_END = "<!-- knowledge-pack:end -->"
REGION = re.compile(re.escape(REGION_START) + r".*?" + re.escape(REGION_END), re.S)


class PackError(Exception):
    pass


# --- reading ------------------------------------------------------------------------------

def load_terms(path: Path) -> list[dict]:
    text = path.read_text("utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise PackError("reading %s needs PyYAML (uv run --with pyyaml ...)" % path) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    terms = data.get("terms") if isinstance(data, dict) else data
    if not isinstance(terms, list) or not terms:
        raise PackError("%s: no terms" % path)
    return terms


def strip_md(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(\*\*|__|\*|_)(\S.*?\S|\S)\1", r"\2", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def paragraphs(path: Path):
    """(title, heading, text, kind) for every paragraph, list item and table row of a Markdown
    file; kind is "p" (prose, list item, quote) or "row" (a table row)."""
    title, heading, buf, out = path.stem, "", [], []
    kind = ["p"]

    def flush():
        if buf:
            t = strip_md(" ".join(buf))
            if t:
                out.append((heading, t, kind[0]))
            buf.clear()
        kind[0] = "p"

    in_code = False
    for raw in path.read_text("utf-8").splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            if len(m.group(1)) == 1 and title == path.stem:
                title = strip_md(m.group(2))
            heading = strip_md(m.group(2))
            continue
        if not line.strip() or re.match(r"^\s*(\|?\s*:?-{3,}.*|---+)\s*$", line):
            flush()
            continue
        item = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if item or line.lstrip().startswith("|"):
            flush()
            if not item:
                kind[0] = "row"
            buf.append(item.group(1) if item else line.strip().strip("|").replace("|", " · "))
            flush()
            continue
        buf.append(re.sub(r"^\s*(?:>\s?)+", "", line).strip())
    flush()
    if heading == "" and not out:
        return []
    return [(title, h, t, k) for h, t, k in out]


def corpus_files(dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        files += sorted(d.rglob("*.md")) if d.is_dir() else [d]
    return files


def is_acronym(name: str) -> bool:
    """A name without a lower-case letter (IT, NIS2, ISO/IEC 27001) matches only as written;
    any other name matches in any case, so "Latency" finds "latency" mid-sentence."""
    return any(ch.isalpha() for ch in name) and not any(ch.islower() for ch in name)


def matcher(term: dict):
    names = sorted({term["label"], *(term.get("aliases") or [])}, key=len, reverse=True)
    # longest first, so an alias that extends the label wins at the same position
    alts = [re.escape(n) if is_acronym(n) else "(?i:%s)" % re.escape(n) for n in names]
    # a term may head a compound (term-based), never sit inside a word
    return re.compile(r"(?<![\w-])(?:%s)(?!\w)" % "|".join(alts))


def clip(text: str, m: re.Match, limit: int = MAX_PASSAGE) -> str:
    """A window of at most `limit` characters around the match, cut at sentence or word ends."""
    if len(text) <= limit:
        return text
    sentences = list(re.finditer(r"[^.!?]+[.!?]*\s*", text))
    for s in sentences:
        if s.start() <= m.start() < s.end() and len(s.group().strip()) <= limit:
            out, i = s.group().strip(), sentences.index(s)
            if i + 1 < len(sentences) and len(out) + len(sentences[i + 1].group()) <= limit:
                out += " " + sentences[i + 1].group().strip()
            return out
    start = max(0, m.start() - limit // 3)
    piece = text[start:start + limit - 2]
    piece = piece.rsplit(" ", 1)[0] if " " in piece else piece
    return ("…" if start else "") + piece.strip() + "…"


# --- build --------------------------------------------------------------------------------

def build(args) -> dict:
    terms = load_terms(args.terms)
    base = args.terms.parent
    ids = [t["id"] for t in terms]
    by_id = {t["id"]: t for t in terms}
    pats = {t["id"]: matcher(t) for t in terms}
    paras = []  # (path, title, heading, text, ids found)
    for f in corpus_files(args.corpus):
        for title, heading, text, kind in paragraphs(f):
            found = [i for i in ids if pats[i].search(text)]
            if found:
                paras.append((f, title, heading, text, found, kind))
    cooc: dict[str, Counter] = {i: Counter() for i in ids}
    for *_, found, _kind in paras:
        for a in found:
            for b in found:
                if a != b:
                    cooc[a][b] += 1

    roots = [base] + [c if c.is_dir() else c.parent for c in args.corpus]

    def preferred(t: dict, p) -> tuple:
        """The section the term list names for the summary first, then that file,
        then prose before table rows, then longer paragraphs (they explain more)."""
        src = str(t.get("summary_source", "")).split("#", 1)
        same_file = bool(src[0]) and any((r / src[0]).resolve() == p[0].resolve() for r in roots)
        same_head = len(src) > 1 and src[1] == p[2]
        rank = 0 if same_file and same_head else 1 if same_file else 2
        return (rank, p[5] == "row", len(p[3]) < 60)

    out_terms = []
    for t in terms:
        key = t["id"]
        hits = [p for p in paras if key in p[4]]
        hits.sort(key=lambda p: preferred(t, p))
        passages, seen = [], set()
        for f, title, heading, text, _, _kind in hits:
            snippet = clip(text, pats[key].search(text))
            if snippet in seen:
                continue
            seen.add(snippet)
            src = {"title": title, "locator": "" if heading == title else heading}
            if args.link_base:
                src["href"] = args.link_base.rstrip("/") + "/" + rel_path(f, args.corpus)
            passages.append({"text": snippet, "source": src})
            if len(passages) >= args.max_passages:
                break
        neighbours, taken = [], set()
        for r in t.get("related", []) or []:
            rid = r["id"] if isinstance(r, dict) else r
            if rid in taken or rid == key:
                continue
            label = by_id[rid]["label"] if rid in by_id else rid
            neighbours.append({"id": rid, "rel": (r.get("rel", "") if isinstance(r, dict) else ""), "label": label})
            taken.add(rid)
        for rid, _ in cooc[key].most_common():
            if len(neighbours) >= args.max_neighbours:
                break
            if rid not in taken:
                neighbours.append({"id": rid, "rel": "", "label": by_id[rid]["label"]})
                taken.add(rid)
        sources = []
        for p in passages:
            s = {"title": p["source"]["title"]}
            if "href" in p["source"]:
                s["href"] = p["source"]["href"].split("#")[0]
            if s not in sources:
                sources.append(s)
        out_terms.append({
            "id": key, "label": t["label"], "aliases": [x for x in (t.get("aliases") or []) if x != t["label"]],
            "type": t.get("type", ""), "summary": str(t.get("summary", "")).strip(),
            "neighbours": neighbours[: args.max_neighbours], "passages": passages, "sources": sources,
        })
    return {
        "schema": SCHEMA, "id": args.id or args.terms.stem, "title": args.title or args.terms.stem,
        "lang": args.lang,
        "source": {"kind": "markdown", "ref": args.source_ref or ", ".join(str(c) for c in args.corpus),
                   "revision": args.revision or "", "generated": dt.date.today().isoformat()},
        "terms": out_terms,
    }


def rel_path(f: Path, roots: list[Path]) -> str:
    for r in roots:
        try:
            return f.resolve().relative_to(r.resolve()).as_posix()
        except ValueError:
            continue
    return f.name


# --- check --------------------------------------------------------------------------------

def check(pack: dict, raw_bytes: int) -> list[str]:
    errs = []
    if pack.get("schema") != SCHEMA:
        errs.append("schema: expected %s" % SCHEMA)
    for k in ("id", "title", "terms"):
        if k not in pack:
            errs.append("%s: missing" % k)
    terms = pack.get("terms") or []
    if len(terms) > MAX_TERMS:
        errs.append("terms: %d, at most %d" % (len(terms), MAX_TERMS))
    seen = set()
    for i, t in enumerate(terms):
        where = "terms[%d] %s" % (i, t.get("id", "?"))
        for k in ("id", "label", "summary"):
            if not t.get(k):
                errs.append("%s: %s missing" % (where, k))
        if t.get("id") in seen:
            errs.append("%s: duplicate id" % where)
        seen.add(t.get("id"))
        if t.get("id") and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", t["id"]):
            errs.append("%s: id must be a lowercase slug" % where)
        if len(t.get("summary", "")) > MAX_SUMMARY:
            errs.append("%s: summary %d characters, at most %d" % (where, len(t["summary"]), MAX_SUMMARY))
        if len(t.get("passages", [])) > MAX_PASSAGES:
            errs.append("%s: %d passages, at most %d" % (where, len(t["passages"]), MAX_PASSAGES))
        for p in t.get("passages", []):
            if len(p.get("text", "")) > MAX_PASSAGE + 2:
                errs.append("%s: a passage of %d characters, at most %d" % (where, len(p["text"]), MAX_PASSAGE))
            if not (p.get("source") or {}).get("title"):
                errs.append("%s: a passage without source title" % where)
        if len(t.get("neighbours", [])) > MAX_NEIGHBOURS:
            errs.append("%s: %d neighbours, at most %d" % (where, len(t["neighbours"]), MAX_NEIGHBOURS))
        for n in t.get("neighbours", []):
            if not n.get("id") or not n.get("label"):
                errs.append("%s: a neighbour needs id and label" % where)
    if raw_bytes > MAX_BYTES:
        errs.append("size: %d bytes, at most %d (fewer terms or shorter passages)" % (raw_bytes, MAX_BYTES))
    return errs


# --- mark ---------------------------------------------------------------------------------

SKIP_TAGS = {"script", "style", "code", "pre", "kbd", "samp", "button", "a", "h1", "h2", "title",
             "textarea", "select", "option", "svg", "aside", "figcaption", "label"}
TOKEN = re.compile(r"(<!--.*?-->|<[^>]+>)", re.S)
SCOPE = re.compile(r'<section\b[^>]*class="[^"]*\bslide\b', re.I)


def mark(html: str, terms: list[dict], headings: bool) -> tuple[str, list[tuple[int, str]]]:
    skip = SKIP_TAGS - ({"h1", "h2"} if headings else set())
    pats = [(t["id"], matcher(t)) for t in terms]
    parts = TOKEN.split(html)
    stack: list[str] = []
    scope, done, report = 0, set(), []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            m = re.match(r"<\s*(/)?\s*([a-zA-Z0-9]+)", part)
            if part.startswith("<!--") or not m:
                continue
            name = m.group(2).lower()
            if m.group(1):
                if name in stack:
                    while stack and stack.pop() != name:
                        pass
            elif not part.rstrip().endswith("/>") and name not in ("br", "img", "hr", "input", "meta", "link", "source", "wbr"):
                if name == "section" and SCOPE.match(part):
                    scope += 1
                    done = set()
                stack.append(name)
                known = re.search(r'data-know="([^"]+)"', part)
                if known:
                    done.add(known.group(1))  # marked by hand or by an earlier run
                    stack.append("__known")
            continue
        if not part.strip() or any(s in skip or s == "__known" for s in stack):
            continue
        hits = []
        for key, pat in pats:
            if key in done:
                continue
            m = pat.search(part)
            if m:
                hits.append((m.start(), m.end(), key))
        hits.sort()
        out, pos = [], 0
        for start, end, key in hits:
            if start < pos:
                continue
            out.append(part[pos:start])
            out.append('<button type="button" class="kp-term" data-know="%s">%s</button>' % (key, part[start:end]))
            pos = end
            done.add(key)
            report.append((scope, key))
        if out:
            out.append(part[pos:])
            parts[i] = "".join(out)
    # a closing tag that was never opened leaves "__known" markers: harmless, they only skip text
    return "".join(parts), report


# --- embed --------------------------------------------------------------------------------

def embed(html: str, pack: dict) -> str:
    data = json.dumps(pack, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    block = '%s\n<script type="application/json" id="knowledge-pack">%s</script>\n%s' % (REGION_START, data, REGION_END)
    if REGION.search(html):
        return REGION.sub(lambda _: block, html, count=1)
    idx = html.lower().rfind("</body>")
    if idx < 0:
        return html.rstrip("\n") + "\n" + block + "\n"
    return html[:idx] + block + "\n" + html[idx:]


# --- cli ----------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="pack from a term list and a Markdown corpus")
    b.add_argument("--terms", type=Path, required=True)
    b.add_argument("--corpus", type=Path, action="append", required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--id")
    b.add_argument("--title")
    b.add_argument("--lang", default="de")
    b.add_argument("--revision")
    b.add_argument("--source-ref")
    b.add_argument("--link-base", help="URL prefix for passage links (path relative to the corpus folder)")
    b.add_argument("--max-passages", type=int, default=3)
    b.add_argument("--max-neighbours", type=int, default=MAX_NEIGHBOURS)
    c = sub.add_parser("check", help="hold a pack to the contract")
    c.add_argument("pack", type=Path)
    m = sub.add_parser("mark", help="wrap the first mention of each term per slide (or page) as a term button")
    m.add_argument("file", type=Path)
    m.add_argument("--pack", type=Path, required=True)
    m.add_argument("--write", action="store_true", help="rewrite the file; without it only report")
    m.add_argument("--headings", action="store_true", help="mark in h1 and h2 too")
    e = sub.add_parser("embed", help="put the pack into a page or deck (one marked region)")
    e.add_argument("file", type=Path)
    e.add_argument("--pack", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            a.max_passages = min(a.max_passages, MAX_PASSAGES)
            a.max_neighbours = min(a.max_neighbours, MAX_NEIGHBOURS)
            pack = build(a)
            text = json.dumps(pack, ensure_ascii=False, indent=1)
            errs = check(pack, len(json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
            a.out.write_text(text + "\n", encoding="utf-8")
            empty = [t["id"] for t in pack["terms"] if not t["passages"]]
            print("%s: %d terms, %d passages%s" % (a.out, len(pack["terms"]),
                  sum(len(t["passages"]) for t in pack["terms"]),
                  ("; no passage for: " + ", ".join(empty)) if empty else ""))
            for err in errs:
                print("error: " + err)
            return 1 if errs else 0
        if a.cmd == "check":
            raw = a.pack.read_text("utf-8")
            pack = json.loads(raw)
            errs = check(pack, len(json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
            for err in errs:
                print("error: " + err)
            if not errs:
                print("%s: ok, %d terms" % (a.pack, len(pack["terms"])))
            return 1 if errs else 0
        pack = json.loads(a.pack.read_text("utf-8"))
        html = a.file.read_text("utf-8")
        if a.cmd == "mark":
            new, report = mark(html, pack["terms"], a.headings)
            for scope, key in report:
                print("%s: %s" % (("slide %d" % scope) if scope else "page", key))
            if not report:
                print("nothing to mark")
            if a.write and new != html:
                a.file.write_text(new, encoding="utf-8")
            return 0
        if a.cmd == "embed":
            errs = check(pack, len(json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
            if errs:
                for err in errs:
                    print("error: " + err)
                return 1
            a.file.write_text(embed(html, pack), encoding="utf-8")
            print("%s: pack %s embedded (%d terms)" % (a.file, pack.get("id"), len(pack["terms"])))
            return 0
    except (PackError, OSError, json.JSONDecodeError, KeyError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
