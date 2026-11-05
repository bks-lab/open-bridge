#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A table of contents for a declared map source, and one block on demand.

Shared by `scripts/context-index.py` (the CLI a session calls) and
`scripts/measure-context.py` (which measures the card rather than the file
once one is declared). The contract is specified by
`scripts/tests/test_context_index.py`.

TWO DELIBERATE CHOICES, both cost something and both are the point.

SLICES ARE RAW TEXT. This module parses YAML only far enough to know where a
block begins and ends; it never re-serializes. A round trip through a YAML
loader is lossy in exactly the direction that matters here: comments. In the
registries this feature exists for, the comments are where the reasoning
lives — which branch is the running one, which board is closed, why a path is
not the obvious one. A reader that answers `--get` with clean re-serialized
YAML answers the letter of the question and drops the half that stops a wrong
action.

THE CARD NAMES EVERY TOP-LEVEL KEY. Kept whole, expanded into an index, or
merely named — but never absent. An index that silently omits a key is the
same failure as a budget that silently omits a file, one layer down: the thing
does not look missing, it looks like it was never there.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a documented dependency
    yaml = None

DEFAULT_LABEL = ("description", "display_name", "name")
DEFAULT_LABEL_CHARS = 120
CLI = "python3 scripts/context-index.py"
ALSO_PRESENT = "Also present, fetch by name: "

REGISTRY_BASE = "ecosystem.yaml"
# Byte-identical to scripts/overlay.py FRAGMENT_NAME_RE (held by a test): every
# fragment the overlay may write is one Phase 1 indexes, and nothing else is.
REGISTRY_FRAGMENT = re.compile(r"^ecosystem\.[a-z][a-z0-9-]*\.yaml$")
REGISTRY_EXCLUDE = frozenset({"ecosystem.example.yaml"})


def registry_files(repo_root) -> list[str]:
    """Every registry Phase 1 indexes: the base first, then each fragment by name.

    One predicate for the CLI (`--registries`) and the meter alike. The glob
    lives here rather than in the Phase 1 command line because zsh aborts on an
    unmatched glob and the CLI takes one path per call.
    """
    root = Path(repo_root)
    found = [REGISTRY_BASE] if (root / REGISTRY_BASE).is_file() else []
    found += sorted(
        path.name
        for path in root.glob("ecosystem.*.yaml")
        if path.is_file()
        and REGISTRY_FRAGMENT.match(path.name)
        and path.name not in REGISTRY_EXCLUDE
    )
    return found

# A top-level key: column zero, not a comment, not a document marker, and NOT
# a list item. `- name: public` at column zero is legal YAML and was read as a
# key called `- name` until a sweep over 120 real files said otherwise. The
# damage was not the invented key but what it did to its neighbour: the real
# key's block ended at the first list item, so it sliced to its header line
# alone — eleven bytes on a live bridge-config.yaml — and the round-trip guard
# called that clean, because one line is still something.
# A quoted key may CONTAIN a colon, and this repo's own context-budget.yaml has
# three of them ("cmd:python3 scripts/worklog.py --recent 3"). An unquoted name
# still stops at the first colon, which is what YAML does too.
KEY_NAME = r'("[^"]*"|\'[^\']*\'|[^\s#][^:]*)'
TOP_KEY = re.compile(r"^(?!-\s)" + KEY_NAME + r":(?:\s|$)")
CHILD_KEY = re.compile(r"^(?!-\s)" + KEY_NAME + r":(?:\s|$)")


# ------------------------------------------------------------- structure --


def _is_blank(line: str) -> bool:
    return not line.strip()


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _inline_value(line: str, indent: int = 0) -> str:
    """What stands after `key:` on the same line, quoting respected.

    Splitting at the first colon is the mistake this file has now made three
    times. On `"cmd:python3 scripts/worklog.py --recent 3":` it hands back
    `python3 …":` and the key reads as a scalar with a value, which is how one
    child stopped its whole parent from being indexed.
    """
    match = CHILD_KEY.match(line[indent:])
    if not match:
        return ""
    return line[indent + match.end() :].strip()


def _unquote(name: str) -> str:
    """The name YAML reports, not the spelling the file needed.

    A key with a dot, a slash or a colon has to be quoted in YAML, and carrying
    the quotes into the index advertises a name no YAML reader will ever hand
    back. `--get items."a.b"` worked and `--get items.a.b` did not, which is
    backwards: the second is the form a caller actually has.
    """
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        return name[1:-1]
    return name


def _child_key(line: str, indent: int):
    """The child name on `line` at exactly `indent`, or None."""
    if len(line) <= indent or line[:indent].strip() or _is_comment(line):
        return None
    if line[indent : indent + 1].isspace():
        return None
    match = CHILD_KEY.match(line[indent:])
    return _unquote(match.group(1)) if match else None


def _trim(lines: list[str], start: int, end: int) -> int:
    """Drop the tail that belongs to whatever comes NEXT, not to this block.

    Order matters. Comment lines are dropped FIRST, and only while they run
    unbroken to the next key: those introduce the next key, and a block that
    keeps them files its neighbour's reasoning under its own name. A comment
    followed by a blank line is separated from the next key, so it stays with
    this block. Then the blank lines go.
    """
    while end > start + 1 and _is_comment(lines[end - 1]):
        end -= 1
    while end > start + 1 and _is_blank(lines[end - 1]):
        end -= 1
    return end


def parse_source(text: str) -> dict:
    """Top-level blocks in file order, with line spans and child spans.

    Returns `{name: {"kind", "start", "end", "children": {name: (start, end)}}}`
    where spans are half-open line indices into `text.split("\\n")`.
    """
    lines = text.split("\n")
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        match = TOP_KEY.match(line)
        if match:
            starts.append((i, _unquote(match.group(1))))

    blocks: dict[str, dict] = {}
    for pos, (start, name) in enumerate(starts):
        end = _trim(lines, start, starts[pos + 1][0] if pos + 1 < len(starts) else len(lines))

        inline = _inline_value(lines[start])
        body = [
            line
            for line in lines[start + 1 : end]
            if not _is_blank(line) and not _is_comment(line)
        ]
        if inline and not inline.startswith("#"):
            kind = "scalar"
        elif body and body[0].lstrip().startswith("- "):
            kind = "list"
        elif body:
            kind = "map"
        else:
            kind = "scalar"

        children: dict[str, tuple[int, int]] = {}
        if kind == "map":
            indent = len(body[0]) - len(body[0].lstrip())
            marks: list[tuple[int, str]] = []
            for i in range(start + 1, end):
                child = _child_key(lines[i], indent)
                if child:
                    marks.append((i, child))
            for idx, (cstart, cname) in enumerate(marks):
                cend = _trim(
                    lines, cstart, marks[idx + 1][0] if idx + 1 < len(marks) else end
                )
                children[cname] = (cstart, cend)

        blocks[name] = {
            "kind": kind,
            "start": start,
            "end": end,
            "children": children,
        }
    return blocks


def _with_leading_comments(lines: list[str], start: int) -> int:
    """Walk back over comment lines that TOUCH `start` (no blank between).

    Contiguity is the whole rule. A comment separated by a blank line belongs
    to the section, not to the entry below it, and dragging it along would
    attach one entry's reasoning to its neighbour.
    """
    i = start
    while i > 0 and _is_comment(lines[i - 1]) and not _is_blank(lines[i - 1]):
        i -= 1
    return i


# An editor directive, not prose. It tells a language server where the schema
# is and says nothing about what the file holds, so it is noise in a card.
DIRECTIVE = re.compile(r"^#\s*yaml-language-server\s*:")


def file_header(text: str) -> str:
    """The leading comment block: what this FILE is, above the first key.

    A card is a table of contents, and one that omits what the book is is
    incomplete. Measured on a live instance, slicing three registries dropped 24
    comment lines, every one of them from this block and none attached to a key.
    Among them `scope: bks — routet zu bks-bridge, NIE open-bridge` and
    `PERSONAL-tier … NEVER promoted to public`. Promote routing is structural, so
    nothing was unsafe; but a session that only ever sees the card had no way to
    learn that the file it holds is PII that must never be published, and that is
    the one sentence a header exists to say. 2 018 bytes for three files there,
    and it is bounded by the item's own `max_bytes` like every other line.

    The split from the FIRST KEY's own comments costs nothing: contiguity already
    decides that, in `_with_leading_comments`. The header is what sits above what
    that returns, so the two partition the region and nothing is carried twice.

    Empty when there is no key to be the header OF: a file of pure comments would
    otherwise arrive whole, which is the opposite of a card.
    """
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if TOP_KEY.match(line)), None)
    if first is None:
        return ""
    kept = [
        line
        for line in lines[: _with_leading_comments(lines, first)]
        if _is_comment(line) and not DIRECTIVE.match(line.strip())
    ]
    return "\n".join(kept).strip()


def slice_block(text: str, dotted: str) -> str:
    """The raw text of `dotted` (`section` or `section.entry`), comments kept."""
    lines = text.split("\n")
    blocks = parse_source(text)
    head, _, tail = dotted.partition(".")
    if head not in blocks:
        return ""
    block = blocks[head]
    if not tail:
        start, end = block["start"], block["end"]
    else:
        if tail not in block["children"]:
            return ""
        start, end = block["children"][tail]
    start = _with_leading_comments(lines, start)
    return "\n".join(lines[start:end]).rstrip() + "\n"


# ------------------------------------------------------------ the card --


def resolve_card(text: str, card) -> dict:
    """The effective card: the declaration, or one detected from the shape.

    FAIL-OPEN. An instance that never declares anything still gets a usable
    index, and therefore never has to choose between adopting this feature and
    keeping its registry readable.
    """
    resolved = dict(card or {})
    auto_keep, auto_sections = _detect(text)

    # ABSENT is not EMPTY, and each field defaults on its own. `sections: []`
    # is a decision and stays empty; an absent `sections:` means "you work it
    # out". Both matter: a bare `card: {kind: index}` that resolved to two
    # empty lists would render every key under "also present" — a list of
    # names, which is the thing this feature exists to beat — while still
    # passing its cap and every guard. And declaring only `keep:` would
    # silently switch indexing off.
    if resolved.get("keep") is None:
        resolved["keep"] = [k for k in auto_keep if k not in (resolved.get("sections") or [])]
    if resolved.get("sections") is None:
        resolved["sections"] = [s for s in auto_sections if s not in resolved["keep"]]

    resolved.setdefault("kind", "index")
    resolved.setdefault("label", DEFAULT_LABEL)
    resolved.setdefault("label_chars", DEFAULT_LABEL_CHARS)
    return resolved


def _detect(text: str) -> tuple[list[str], list[str]]:
    """(keep, sections) read off the file's own shape."""
    lines = text.split("\n")
    keep, sections = [], []
    for name, block in parse_source(text).items():
        children = block["children"]
        # ALL children, not any. A map whose children are mixed is a block of
        # settings, and settings are what a session needs in front of it —
        # `work.enabled` decides whether Phase 1 runs at all. When the shape is
        # ambiguous, detection carries more, never less.
        if (
            block["kind"] == "map"
            and children
            and all(_looks_nested(lines, span) for span in children.values())
        ):
            sections.append(name)
        elif block["kind"] in ("scalar", "map"):
            keep.append(name)
    return keep, sections


def _looks_nested(lines: list[str], span: tuple[int, int]) -> bool:
    """True when the child at `span` is a block rather than a scalar.

    Reads the span, never a rendered slice: a slice carries the entry's
    leading comment as its first line, and reading a comment as the key line
    answers this question at random.
    """
    start, end = span
    key = lines[start]
    indent = len(key) - len(key.lstrip())
    inline = _inline_value(key, indent)
    if inline and not inline.startswith("#"):
        return False
    return any(
        not _is_blank(line) and not _is_comment(line)
        for line in lines[start + 1 : end]
    )


def addressable(text: str, card=None) -> list[str]:
    """Every path `--get` accepts, in file order."""
    resolved = resolve_card(text, card)
    blocks = parse_source(text)
    paths: list[str] = []
    for name, block in blocks.items():
        paths.append(name)
        if name in resolved["sections"]:
            paths.extend(f"{name}.{child}" for child in block["children"])
    return paths


def _label_for(text: str, section: str, child: str, field, chars: int) -> str:
    """The one line for an entry, from the first declared field that has one.

    `label` may name several fields, tried in order. Entry families disagree
    about what their one line is called — repos say `description`, customers
    say `display_name` — and an index whose lines are empty is just a list of
    names.
    """
    fields = [field] if isinstance(field, str) else list(field or [])
    block = slice_block(text, f"{section}.{child}")
    value = None
    if yaml is not None:
        try:
            parsed = yaml.safe_load(block) or {}
            entry = parsed.get(child) if isinstance(parsed, dict) else None
            if isinstance(entry, dict):
                for name in fields:
                    if isinstance(entry.get(name), str) and entry[name].strip():
                        value = entry[name]
                        break
        except yaml.YAMLError:
            value = None
    if not isinstance(value, str) or not value.strip():
        return ""
    flat = " ".join(value.split())
    return flat if len(flat) <= chars else flat[: chars - 1].rstrip() + "…"


def uncarried_comment_bytes(text: str, card=None) -> int:
    """Comment bytes inside indexed sections, i.e. not resident in the card.

    They remain reachable through `--get`; they stop being in front of the
    reader by default. That distinction is the real cost of this feature, and
    a migration that does not see the number will discover it the hard way:
    a guardrail written as a YAML comment stops guarding the day the file
    stops being read whole.
    """
    resolved = resolve_card(text, card)
    lines = text.split("\n")
    blocks = parse_source(text)
    total = 0
    for name in resolved["sections"]:
        block = blocks.get(name)
        if not block:
            continue
        for line in lines[block["start"] : block["end"]]:
            if _is_comment(line):
                total += len(line.encode("utf-8")) + 1
    return total


def render_card(text: str, card, rel_path: str) -> str:
    """The always-on surface for `rel_path`. Deterministic by construction."""
    resolved = resolve_card(text, card)
    blocks = parse_source(text)
    kept = [n for n in blocks if n in resolved["keep"]]
    sections = [n for n in blocks if n in resolved["sections"]]
    rest = [n for n in blocks if n not in kept and n not in sections]

    out = [f"# {rel_path} — index", ""]

    header = file_header(text)
    if header:
        out.append(header)
        out.append("")

    if kept:
        out.append("Kept whole:")
        out.append("")
        for name in kept:
            out.append(slice_block(text, name).rstrip())
            out.append("")

    entries = sum(len(blocks[n]["children"]) for n in sections)
    out.append(
        f"{len(sections)} section(s), {entries} entr{'y' if entries == 1 else 'ies'}. "
        f"Read one with `{CLI} {rel_path} --get <path>`."
    )
    out.append("")

    for name in sections:
        out.append(f"## {name}")
        for child in blocks[name]["children"]:
            label = _label_for(
                text, name, child, resolved["label"], int(resolved["label_chars"])
            )
            out.append(f"- **{child}**" + (f" — {label}" if label else " — (no label)"))
        out.append("")

    if rest:
        described = []
        for name in rest:
            block = blocks[name]
            if block["kind"] == "list":
                count = sum(
                    1
                    for line in text.split("\n")[block["start"] + 1 : block["end"]]
                    if line.lstrip().startswith("- ")
                )
                described.append(f"{name} (list of {count})")
            else:
                described.append(name)
        out.append(ALSO_PRESENT + ", ".join(described) + ".")
        out.append("")

    lost = uncarried_comment_bytes(text, resolved)
    if lost:
        out.append(
            f"{lost} bytes of comment sit inside the indexed sections and are not "
            f"resident here; `--get` still returns them with their entry."
        )
        out.append("")

    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- guards --


def check_round_trip(text: str, card=None, extra_paths=None) -> list[str]:
    """Every advertised path has to slice to something.

    A pointer reads as a promise that the content is one call away, and the
    caller stops looking anywhere else. A dead one is worse than no index.
    """
    paths = list(addressable(text, card)) + list(extra_paths or [])
    return [
        f"{path}: advertised in the index and slices to nothing"
        for path in paths
        if not slice_block(text, path).strip()
    ]


def check_declaration(text: str, card=None) -> list[str]:
    """Names in `keep:` / `sections:` that the source does not have.

    The declaration is the failure surface this feature adds, and a typo in it
    is absorbed in silence: the real key falls through to "also present", its
    content stops being resident, and the card still renders and still passes
    its cap. Auto-detection cannot make this mistake, so an undeclared source
    has nothing to check.
    """
    if not card:
        return []
    blocks = parse_source(text)
    present = set(blocks)
    findings = []
    for name in card.get("sections") or []:
        kind = (blocks.get(name) or {}).get("kind")
        if kind and kind != "map":
            findings.append(
                f"sections: '{name}' is a {kind}, not a map. A section is "
                f"rendered from its CHILDREN, and a non-map has none: the card "
                f"gets a bare heading, the entries leave the count, and they do "
                f"not reach 'also present' either. Undeclared it would fall "
                f"through to a working pointer, so declaring it is strictly "
                f"worse than leaving it out."
            )
    for field in ("keep", "sections"):
        for name in card.get(field) or []:
            if name not in present:
                findings.append(
                    f"{field}: '{name}' is declared and not in the source"
                )
    both = set(card.get("keep") or []) & set(card.get("sections") or [])
    for name in sorted(both):
        findings.append(
            f"keep/sections: '{name}' is declared in both, which is two answers "
            f"to one question"
        )
    return findings


def check_structure(text: str, blocks=None) -> list[str]:
    """The scanner's answer against YAML's, which already knows it.

    This module reads the file as lines so it can keep comments, and a line
    scanner can be wrong in ways a round trip cannot see: the failure that
    prompted this guard invented a key AND truncated its neighbour to a header
    line, and `check_round_trip` called it clean, because one line is still
    something.

    The oracle is `yaml.compose`, not `yaml.safe_load`, and that is the whole
    difference between a guard and a nuisance. `safe_load` hands back RESOLVED
    values: `on:` becomes the boolean True, so every GitHub workflow looked
    like the scanner had invented a key it had read perfectly well. Compose
    keeps the source spelling and, more usefully, says whether a value was
    written in flow style — so `required: [a, b]` is one line legitimately and
    a block mapping squeezed onto one line is not. Written without that
    distinction, this guard's first outing produced 54 findings across 255 real
    files and not one of them was real.
    """
    if yaml is None:  # pragma: no cover
        return []
    try:
        node = yaml.compose(text)
    except yaml.YAMLError as exc:
        return [f"source is not valid YAML: {exc}"]
    if not isinstance(node, yaml.MappingNode):
        return []

    truth: dict[str, object] = {}
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode):
            truth[key_node.value] = value_node

    blocks = parse_source(text) if blocks is None else blocks
    findings = []
    for name in truth:
        if name not in blocks:
            findings.append(f"{name}: in the source and invisible to the scanner")
    for name in blocks:
        if name not in truth:
            findings.append(f"{name}: invented by the scanner, YAML has no such key")

    for name, value in truth.items():
        block = blocks.get(name)
        if not block or not isinstance(value, (yaml.MappingNode, yaml.SequenceNode)):
            continue
        if not value.value or value.flow_style:
            continue
        if block["end"] - block["start"] < 2:
            findings.append(
                f"{name}: sliced to its header line alone, and its block value "
                f"has content"
            )
        if block["kind"] == "scalar":
            findings.append(
                f"{name}: read as a scalar, and YAML says it is a block "
                f"{'mapping' if isinstance(value, yaml.MappingNode) else 'sequence'}"
            )
        # One level down as well. Checking only the top level is how a live
        # file kept advertising `"ecosystem.bks.yaml"`, quotes and all, with
        # every guard green: the defect was never at the top.
        if not isinstance(value, yaml.MappingNode) or not block["children"]:
            continue
        want = {
            k.value
            for k, _ in value.value
            if isinstance(k, yaml.ScalarNode)
        }
        for child in want - set(block["children"]):
            findings.append(f"{name}.{child}: in the source and invisible to the scanner")
        for child in set(block["children"]) - want:
            findings.append(f"{name}.{child}: invented by the scanner")
    return findings


def check_coverage(text: str, rendered: str = "") -> list[str]:
    """Every top-level key has to be findable in the card, in some form.

    Matched as a section heading, a kept block's own key line, or a name in the
    "also present" line — never as a substring. `org` occurs inside
    `example-org`, so a substring test finds keys that are not there, and a
    guard that cannot fail is not a guard.
    """
    present: set[str] = set()
    for line in rendered.split("\n"):
        if line.startswith("## "):
            present.add(line[3:].strip())
        elif line.startswith(ALSO_PRESENT):
            names = line[len(ALSO_PRESENT):].rstrip(".")
            present.update(part.strip().split(" ")[0] for part in names.split(","))
        elif line[:1] not in (" ", "\t", "#", "-", "") and ":" in line:
            present.add(line.split(":", 1)[0].strip())
    return [
        f"{name}: present in the source and absent from the card"
        for name in parse_source(text)
        if name not in present
    ]


# ----------------------------------------------------------- declaration --


def card_for(repo_root, rel_path: str):
    """The `card:` block declared for `rel_path`, or None.

    One declaration file, read by both halves: the meter measures the card the
    session will really get, and the session gets the card the meter measured.
    Two sources of truth here would mean a green gate over a different card.
    """
    if yaml is None:  # pragma: no cover
        return None
    return (_merged_items(repo_root).get(rel_path) or {}).get("card")


def declared_cards(repo_root) -> dict:
    """Every `path -> card` the budget declares, overlay applied."""
    return {
        rel: item["card"]
        for rel, item in _merged_items(repo_root).items()
        if (item or {}).get("card")
    }


def _merged_items(repo_root) -> dict:
    """CORE items with the per-instance overlay laid over them, WHOLESALE.

    The same rule `measure-context.py` uses, and it has to be the same rule: an
    overlay entry replaces a CORE entry entirely, so an instance that redeclares
    an item without a `card:` has removed the card. Merging per key here while
    the meter replaces per item would mean the gate measures one card and the
    session gets another.
    """
    if yaml is None:  # pragma: no cover
        return {}
    root = Path(repo_root)
    items: dict = {}
    for name in ("context-budget.yaml", "context-budget.user.yaml"):
        path = root / name
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for rel, item in (data.get("items") or {}).items():
            items[rel] = item or {}
    return items
