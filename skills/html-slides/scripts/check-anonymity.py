#!/usr/bin/env python3
"""Audit a deck for names, identifiers and leftover placeholders before it is sent.

Scans what a reader sees: text, attribute values (alt, title, aria-label) and
comments. Before the scan, data: URIs and the bodies of <style> and <script>
are blanked (newlines kept, so line numbers stay true): embedded font data is
base64 and matches almost any short term somewhere, and a stylesheet or the
engine script is no text anybody reads. HTML entities are decoded, so
`caf&eacute;` matches `café`.

Terms come from wordlists, one per line (`#` lines and blanks ignored):
  plain term     case-insensitive, matched as a whole word: `todo` hits "TODO:",
                 not "mastodon"; a term with punctuation (example.com) the same
  re:<pattern>   a regular expression, case-insensitive

Lists, all additive:
  scripts/wordlist-default.txt   generic leak and placeholder markers (CORE);
                                 --no-default-wordlist drops it
  --wordlist FILE                repeatable; an instance's own list
  bridge-config.yaml             html_slides.anonymity_wordlist: a path or a list
                                 of paths relative to that file, found walking up
                                 from the deck (or named with --config); the older
                                 key html_slides.wordlist is read too. --no-config
                                 skips it.

Exit codes:
  0  no hits (or --warn-only)
  1  hits found
  2  usage error: input or wordlist missing, or no term to check

Usage:
  check-anonymity.py deck.html [--wordlist FILE ...] [--config bridge-config.yaml]
                     [--no-config] [--no-default-wordlist] [--warn-only] [--quiet]
"""
from __future__ import annotations

import argparse
import html as html_mod
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # the config lookup is optional; plain wordlists still work
    yaml = None

DEFAULT_WORDLIST = Path(__file__).resolve().parent / "wordlist-default.txt"
CONFIG_NAME = "bridge-config.yaml"
CONFIG_KEYS = ("anonymity_wordlist", "wordlist")  # current key first, older one second

# Text nobody reads, blanked before the scan.
BLANK_PATTERNS = (
    re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.I | re.S),
    re.compile(r"(<script\b[^>]*>)(.*?)(</script\s*>)", re.I | re.S),
)
DATA_URI_RE = re.compile(r"data:[\w.+-]+/[\w.+-]+(?:;[\w.+-]+=[^;,\s\"')]*)*(?:;base64)?,[^\s\"')<>]*", re.I)


class UsageError(Exception):
    pass


def spaces(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def readable(raw: str) -> str:
    """The deck with unread text blanked and entities decoded, line for line."""
    for pat in BLANK_PATTERNS:
        raw = pat.sub(lambda m: m.group(1) + spaces(m.group(2)) + m.group(3), raw)
    raw = DATA_URI_RE.sub(lambda m: spaces(m.group(0)), raw)
    # per line, and an encoded newline stays a space, so line numbers stay true
    return "\n".join(re.sub(r"[\r\n]", " ", html_mod.unescape(line)) for line in raw.split("\n"))


def load_terms(path: Path) -> list[tuple[str, re.Pattern]]:
    """(label, compiled pattern) per entry of one wordlist."""
    if not path.is_file():
        raise UsageError("wordlist not found: %s" % path)
    terms = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("re:"):
            try:
                terms.append((line, re.compile(line[3:], re.I)))
            except re.error as exc:
                print("WARN: invalid regex %r in %s: %s" % (line, path.name, exc), file=sys.stderr)
        else:
            terms.append((line.lower(), re.compile(r"(?<!\w)" + re.escape(line) + r"(?!\w)", re.I)))
    return terms


def find_config(start: Path) -> Path | None:
    for folder in [start, *start.parents]:
        cand = folder / CONFIG_NAME
        if cand.is_file():
            return cand
    return None


def config_wordlists(config: Path) -> list[Path]:
    """The instance lists a bridge-config.yaml names under html_slides."""
    if yaml is None:
        print("WARN: PyYAML missing, %s not read" % config, file=sys.stderr)
        return []
    try:
        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print("WARN: %s not readable: %s" % (config, exc), file=sys.stderr)
        return []
    block = data.get("html_slides") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    for key in CONFIG_KEYS:
        value = block.get(key)
        if value:
            items = value if isinstance(value, list) else [value]
            return [(config.parent / Path(str(v)).expanduser()).resolve() for v in items]
    return []


def scan(text: str, terms: list[tuple[str, re.Pattern]]) -> list[tuple[int, str, str]]:
    hits = []
    for line_no, line in enumerate(text.split("\n"), start=1):
        for label, pat in terms:
            for m in pat.finditer(line):
                hits.append((line_no, label if not label.startswith("re:") else "%s -> %s" % (label, m.group(0)),
                             line.strip()))
    return hits


def render_report(hits, src: Path, lists: list[Path], quiet: bool) -> None:
    if not hits:
        if not quiet:
            print("OK %s: no wordlist hits (%s)." % (src.name, ", ".join(p.name for p in lists)))
        return
    by_term: dict[str, list[tuple[int, str]]] = {}
    for line_no, term, ctx in hits:
        by_term.setdefault(term, []).append((line_no, ctx))
    print("HITS %s: %d potential hit%s across %d term%s (%s):"
          % (src.name, len(hits), "" if len(hits) == 1 else "s", len(by_term),
             "" if len(by_term) == 1 else "s", ", ".join(p.name for p in lists)))
    print()
    for term in sorted(by_term):
        occ = by_term[term]
        print("  * %s  (%d hit%s)" % (term, len(occ), "" if len(occ) == 1 else "s"))
        for line_no, ctx in occ[:5]:
            print("      L%d: %s" % (line_no, ctx if len(ctx) <= 110 else ctx[:107] + "..."))
        if len(occ) > 5:
            print("      ... and %d more" % (len(occ) - 5))
        print()
    print("Some hits may be intentional (an explicitly disclosed name, for example).")
    print("Review each one before sending; keep the wordlist entry as a reminder.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit a deck against wordlists before sending it")
    ap.add_argument("input", type=Path, help="HTML file to audit")
    ap.add_argument("--wordlist", "--extra-wordlist", dest="wordlists", type=Path, action="append",
                    default=[], metavar="FILE", help="an additional wordlist (repeatable)")
    ap.add_argument("--no-default-wordlist", action="store_true",
                    help="drop the generic scripts/wordlist-default.txt")
    ap.add_argument("--config", type=Path, help="bridge-config.yaml to read html_slides.anonymity_wordlist "
                                                "from (default: the nearest one above the deck)")
    ap.add_argument("--no-config", action="store_true", help="do not read bridge-config.yaml")
    ap.add_argument("--warn-only", action="store_true", help="report hits but exit 0")
    ap.add_argument("--exit-on-hits", action="store_true", help=argparse.SUPPRESS)  # the default now
    ap.add_argument("--quiet", action="store_true", help="print nothing on a clean run")
    args = ap.parse_args()

    try:
        if not args.input.is_file():
            raise UsageError("input not found: %s" % args.input)
        lists = [] if args.no_default_wordlist else [DEFAULT_WORDLIST]
        lists += args.wordlists
        if not args.no_config:
            config = args.config or find_config(args.input.resolve().parent)
            if args.config and not args.config.is_file():
                raise UsageError("--config: %s not found" % args.config)
            if config:
                lists += config_wordlists(config)
        terms = [t for path in lists for t in load_terms(path)]
        if not terms:
            raise UsageError("no term to check (the wordlists are empty)")
    except UsageError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2

    text = readable(args.input.read_text(encoding="utf-8", errors="replace"))
    hits = scan(text, terms)
    render_report(hits, args.input, lists, args.quiet)
    return 1 if hits and not args.warn_only else 0


if __name__ == "__main__":
    raise SystemExit(main())
