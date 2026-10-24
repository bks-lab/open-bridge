#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hold the CORE/USER figure on docs/explore.html to the actual tree.

The figure draws one dot per tracked file, the CORE half against the shipped
example workspace, split by top level folder. Those numbers are true on the commit that wrote
them and quietly false on the next merge, which is worse than shipping no number
at all. This recomputes every one of them from `git ls-files` and fails when the
page has drifted.

It checks the totals, the per folder counts inside both JS arrays, and the two
numbers spelled out in the visible captions.

It holds two more claims on the pages to the same tree:

  * the containment ring on docs/index.html, which draws the shipped demo
    workspace examples/agency/ as files per folder and one dot per line, and
    spells both totals out in its caption;
  * every quoted artifact. A block marked `data-verbatim="<path>"` must consist
    of lines that file actually carries, in order, and a page that tells the
    reader something is copied "character-for-character" or "verbatim" has to
    carry such a block. index.html quoted a README row for months after the
    README dropped it, which is the drift this closes.

    python3 scripts/check-figure-counts.py            # report drift, exit 1
    python3 scripts/check-figure-counts.py --write     # rewrite the page to match

A strict census on a moving tree goes red on the next commit that adds a file,
including the commit that added this script. That is the point, but a gate is
only worth its friction if clearing it is one command, so --write exists.
"""
from __future__ import annotations

import collections
import importlib.util
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs/explore.html"
RING_PAGE = REPO / "docs/index.html"
USER_PREFIX = "examples/agency/"

# The example instance keeps three sub-agent definitions under .claude/agents/.
# The figure counts them under the root rather than giving them a folder of
# their own: sub-agents are the one Claude Code specific piece in the system,
# and a .claude/ label on the USER half would read as "this only works with
# Claude" on a page whose whole claim is that it does not.
USER_FOLD = {".claude/": "./"}


# The promote router (scripts/categorize-commits.py) is the one place that knows
# a file's tier. Reuse it rather than growing a second answer here that drifts
# from it. Loaded by path because the filename carries a hyphen.
_ROUTER_SPEC = importlib.util.spec_from_file_location(
    "categorize_commits", REPO / "scripts" / "categorize-commits.py"
)
if not (_ROUTER_SPEC and _ROUTER_SPEC.loader):
    sys.exit("check-figure-counts: cannot load scripts/categorize-commits.py")
_router = importlib.util.module_from_spec(_ROUTER_SPEC)
_ROUTER_SPEC.loader.exec_module(_router)

# Files that SHIP but must never be PROMOTED, which is why the router calls them
# `user` and why `classify_file() == "core"` alone is the wrong census.
#
# The router answers "may this travel upward", the figure asks "does a fresh
# clone get it". Both are right and they disagree on exactly two families:
#
#   * `.gitignore` / `.bridge-origin` are per-tier INVERTED — they exist on both
#     sides and copying either way is a bug (promoting ours would disarm the
#     push guard downstream), yet a clone plainly gets them.
#   * `work/templates/` and the `work/_learning/` scaffolding are CORE content
#     living inside a folder whose TIER is USER. A clone gets the templates; an
#     instance's filled-in copies must never travel.
#
# Inside `_learning/`, the three directories below are where an instance's own
# content accumulates. Their `.gitkeep` ships (it is what creates the directory),
# everything else in them is that operator's.
SHIPPED_NOT_PROMOTABLE = frozenset({".gitignore", ".bridge-origin"})
SHIPPED_SCAFFOLD = ("work/templates/",)

# `work/_learning/` mixes both in one tree: the scaffolding ships, the captured
# findings are the operator's. Split them by the repo's own naming convention
# rather than by a list that rots the day upstream adds a file — `_`-prefixed is
# reserved, README.md documents, `.gitkeep` is what creates the directory. The
# one irregular is `audit-trail.md`, which ships as an empty ledger and fills up
# per instance.
LEARNING_ROOT = "work/_learning/"
LEARNING_SHIPPED = frozenset({"README.md", ".gitkeep", "audit-trail.md"})


def is_core_file(path: str) -> bool:
    """True when a fresh clone of the default branch gets this file.

    The census used to be `not path.startswith("examples/")`, which is true on
    the default branch and false on every `user/*` branch — where an instance
    tracks its own work/ content. `validate.yml` runs on `user/**` by design, so
    that census could never pass on the branches it was pointed at, and `--write`
    would have answered by baking one operator's task list into a page that
    ships to open-bridge.
    """
    if path.startswith("examples/"):
        return False
    if path in SHIPPED_NOT_PROMOTABLE:
        return True
    if path.startswith(SHIPPED_SCAFFOLD):
        return True
    if path.startswith(LEARNING_ROOT):
        name = path.rsplit("/", 1)[-1]
        return name in LEARNING_SHIPPED or name.startswith("_")
    return _router.classify_file(path) == "core"


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    if not out:
        sys.exit("check-figure-counts: git ls-files returned nothing")
    return out


def family(path: str) -> str:
    head, _, rest = path.partition("/")
    return "./" if not rest else head + "/"


def counted(files: list[str]) -> collections.Counter:
    return collections.Counter(family(f) for f in files)


def parse(block: str, key: str) -> dict[str, int]:
    """Pull {n:"<folder>", ... <key>:<n> ...} pairs out of one JS array."""
    found: dict[str, int] = {}
    for entry in re.finditer(r"\{[^{}]*\}", block):
        text = entry.group(0)
        name = re.search(r'n\s*:\s*"([^"]+)"', text)
        num = re.search(rf"\b{key}\s*:\s*(\d+)", text)
        if name and num:
            found[name.group(1)] = int(num.group(1))
    return found


def section(src: str, var: str) -> str:
    start = src.index("var " + var + " = [")
    return src[start:src.index("\n  ];", start)]


def rewrite(src: str, real_core: dict, real_user: dict, core_total: int, user_total: int) -> str:
    """Put the recomputed numbers back into the page, in place."""
    def fix_array(block: str, key: str, real: dict) -> str:
        def one(m: re.Match) -> str:
            text = m.group(0)
            name = re.search(r'n\s*:\s*"([^"]+)"', text)
            if not name or name.group(1) not in real:
                return text
            want = real[name.group(1)]
            return re.sub(rf"(\b{key}\s*:\s*)\d+", rf"\g<1>{want}", text, count=1)
        return re.sub(r"\{[^{}]*\}", one, block)

    def fix_prose(block: str, num_key: str, prose_keys: tuple) -> str:
        def one(m: re.Match) -> str:
            text = m.group(0)
            num = re.search(rf"\b{num_key}\s*:\s*(\d+)", text)
            if not num:
                return text
            for pk in prose_keys:
                text = re.sub(rf'({pk}\s*:\s*")\d+ ', rf"\g<1>{num.group(1)} ", text, count=1)
            return text
        return re.sub(r"\{[^{}]*\}", one, block)

    for var, key, real in (("CORE_ONLY", "c", real_core),
                           ("PAIRS", "core", real_core),
                           ("PAIRS", "user", real_user)):
        block = section(src, var)
        src = src.replace(block, fix_array(block, key, real), 1)

    # the sentence follows the field it describes
    for var, num_key, prose_keys in (("CORE_ONLY", "c", ("d_en", "d_de")),
                                     ("PAIRS", "core", ("c_en", "c_de")),
                                     ("PAIRS", "user", ("u_en", "u_de"))):
        block = section(src, var)
        src = src.replace(block, fix_prose(block, num_key, prose_keys), 1)

    # the numbers a reader sees: captions, headers, screen reader text
    src = re.sub(r"\b\d+ files ship\. \d+ are yours\.",
                 f"{core_total} files ship. {user_total} are yours.", src)
    src = re.sub(r"\b\d+ Dateien kommen mit, \d+ sind deine\.",
                 f"{core_total} Dateien kommen mit, {user_total} sind deine.", src)
    src = re.sub(r'"\d+ Dateien, alle mitgeliefert" : "\d+ files, all shipped"',
                 f'"{core_total} Dateien, alle mitgeliefert" : "{core_total} files, all shipped"', src)
    src = re.sub(r'"\d+ Dateien, alle deine" : "\d+ files, all yours"',
                 f'"{user_total} Dateien, alle deine" : "{user_total} files, all yours"', src)
    src = re.sub(r"\b\d+ tracked files, one dot each", f"{core_total} tracked files, one dot each", src)
    src = re.sub(r"\b\d+ versionierte Dateien, je Datei ein Punkt",
                 f"{core_total} versionierte Dateien, je Datei ein Punkt", src)
    for fam, n in real_core.items():
        name = fam.rstrip("/")
        if not name or name.startswith("."):
            continue
        src = re.sub(rf"\b({re.escape(name)} (?:at|bei) )\d+\b", rf"\g<1>{n}", src)
    return src


# ---------------------------------------------------------------------------
# The containment ring on docs/index.html
# ---------------------------------------------------------------------------

def _read_tracked(path: str) -> bytes:
    return (REPO / path).read_bytes()


def ring_census(files: list[str], read=_read_tracked) -> dict[str, dict]:
    """examples/agency/ per top level folder: lines (as `wc -l` counts them)
    and files per second level folder, "" for files directly in the folder."""
    census: dict[str, dict] = {}
    for path in files:
        if not path.startswith(USER_PREFIX):
            continue
        rel = path[len(USER_PREFIX):]
        top, _, rest = rel.partition("/")
        if rest:
            label = top + "/"
            sub, _, deeper = rest.partition("/")
            kid = sub + "/" if deeper else ""
        else:
            label, kid = "./", ""
        entry = census.setdefault(label, {"lines": 0, "kids": {}})
        entry["lines"] += read(path).count(b"\n")
        entry["kids"][kid] = entry["kids"].get(kid, 0) + 1
    return census


_RING_ENTRY = re.compile(
    r"\{\s*key:'[^']*',\s*label:'(?P<label>[^']*)',\s*l:(?P<l>\d+),\s*kids:\[(?P<kids>[^\]]*)\]\s*\}"
)
_RING_KID = re.compile(r"\{n:'(?P<n>[^']*)',\s*f:(?P<f>\d+)\}")

# Every place the page spells out a ring total. Each must match at least once:
# a sentence reworded out of reach of its pattern would otherwise go unchecked.
# Group `f` is the file total, group `l` the line total.
RING_PROSE = (
    r"(?P<f>\d+) files in six folders",
    r"each of their (?P<l>\d+) lines",
    r"(?P<f>\d+) Dateien in sechs Ordnern",
    r"ihrer (?P<l>\d+) Zeilen",
    r"examples/agency</b>: (?P<f>\d+) files, (?P<l>\d+) lines",
    r"examples/agency</b>: (?P<f>\d+) Dateien, (?P<l>\d+) Zeilen",
    r"counted on disk\. (?P<f>\d+) files",
    r"-not -path '\./\.git/\*' \| wc -l\s+-> (?P<f>\d+)",
    r"\{\} \+ \| wc -l\s+-> (?P<l>\d+)",
    r"one dot per LINE of content, (?P<l>\d+) of them",
    r"rather than (?P<l>\d+) separate arcs",
    r"instead of (?P<l>\d+) arcs",
)


def _ring_section(src: str) -> str:
    start = src.index("var TREE = [")
    return src[start:src.index("\n  ];", start)]


def ring_problems(src: str, census: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    drawn: dict[str, tuple[int, dict]] = {}
    for m in _RING_ENTRY.finditer(_ring_section(src)):
        kids = {k.group("n"): int(k.group("f")) for k in _RING_KID.finditer(m.group("kids"))}
        drawn[m.group("label")] = (int(m.group("l")), kids)
    for label, (lines, kids) in sorted(drawn.items()):
        real = census.get(label, {"lines": 0, "kids": {}})
        if real["lines"] != lines:
            problems.append(f"index.html ring {label}: draws {lines} lines, tree has {real['lines']}")
        for kid in sorted(set(kids) | set(real["kids"])):
            if kids.get(kid) != real["kids"].get(kid):
                problems.append(
                    f"index.html ring {label}{kid}: draws {kids.get(kid, 0)} files, "
                    f"tree has {real['kids'].get(kid, 0)}"
                )
    for label in sorted(set(census) - set(drawn)):
        problems.append(f"index.html ring {label}: in the tree, not drawn")
    want = {"f": sum(sum(v["kids"].values()) for v in census.values()),
            "l": sum(v["lines"] for v in census.values())}
    for pattern in RING_PROSE:
        hits = list(re.finditer(pattern, src))
        if not hits:
            problems.append(f"index.html ring caption not found: {pattern!r}")
        for hit in hits:
            for key, value in hit.groupdict().items():
                if value is not None and int(value) != want[key]:
                    what = "files" if key == "f" else "lines"
                    problems.append(
                        f"index.html ring caption says {value} {what}, tree has {want[key]}: "
                        f"{hit.group(0)!r}"
                    )
    return problems


def rewrite_ring(src: str, census: dict[str, dict]) -> str:
    block = _ring_section(src)

    def one(m: re.Match) -> str:
        real = census.get(m.group("label"))
        if not real:
            return m.group(0)
        text = re.sub(r"(\bl:)\d+", rf"\g<1>{real['lines']}", m.group(0), count=1)

        def kid(k: re.Match) -> str:
            n = real["kids"].get(k.group("n"))
            return k.group(0) if n is None else re.sub(r"(f:)\d+", rf"\g<1>{n}", k.group(0))
        return _RING_KID.sub(kid, text)

    src = src.replace(block, _RING_ENTRY.sub(one, block), 1)
    want = {"f": sum(sum(v["kids"].values()) for v in census.values()),
            "l": sum(v["lines"] for v in census.values())}
    for pattern in RING_PROSE:
        def fix(m: re.Match) -> str:
            text, base = m.group(0), m.start()
            for key in sorted(m.groupdict(), key=lambda k: -m.start(k)):
                if m.group(key) is None:
                    continue
                a, b = m.start(key) - base, m.end(key) - base
                text = text[:a] + str(want[key]) + text[b:]
            return text
        src = re.sub(pattern, fix, src)
    return src


# ---------------------------------------------------------------------------
# Quoted artifacts
# ---------------------------------------------------------------------------

VERBATIM_PAGES = ("docs/index.html", "docs/concepts.html")
# What a reader is told. Comments are stripped first, so a note to the next
# author ("verbatim from the project brief") is not a claim on the page.
# One pattern per language: a bilingual page says the same thing twice, once
# for each reader, and that is still one quoted block.
_CLAIMS = (re.compile(r"character-for-character|verbatim from", re.IGNORECASE),
           re.compile(r"Zeichengenau|wortgetreu", re.IGNORECASE))
# A row that carries no `ln` span has no text the check could compare. It is
# kept as this marker so it is reported rather than skipped.
NO_TEXT = None


class _Quotes(HTMLParser):
    """Collect every data-verbatim block and the text of each of its rows.

    Rows are found as elements, not as lines, so a row split over two lines or
    closed with a space before `</div>` is still compared. A regex over lines
    skipped those shapes, and a block of invented rows in them came back green.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, list]] = []
        self._stack: list[str] = []   # role of each open div/span: block, row, ln, other
        self._text: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag not in ("div", "span"):
            return
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        role = "other"
        if tag == "div" and "data-verbatim" in a and "block" not in self._stack:
            self.blocks.append((a["data-verbatim"], []))
            role = "block"
        elif tag == "div" and "row" in classes and self._stack[-1:] == ["block"]:
            self.blocks[-1][1].append(NO_TEXT)
            role = "row"
        elif tag == "span" and "ln" in classes and "row" in self._stack and "ln" not in self._stack:
            self._text = []
            role = "ln"
        self._stack.append(role)

    def handle_endtag(self, tag):
        if tag not in ("div", "span") or not self._stack:
            return
        role = self._stack.pop()
        if role == "ln" and self._text is not None:
            self.blocks[-1][1][-1] = "".join(self._text)
            self._text = None

    def handle_data(self, data):
        if self._text is not None:
            self._text.append(data)


def verbatim_blocks(src: str) -> list[tuple[str, list]]:
    """Each data-verbatim block as (source path, row texts); a row without text is NO_TEXT.

    The rows must appear in the source in the order shown. They need not be
    adjacent: a block may quote a heading and a row further down, so its label
    should say how the lines were picked (a grep, not a cat).
    """
    parser = _Quotes()
    parser.feed(src)
    parser.close()
    return parser.blocks


def verbatim_problems(pages=None) -> list[str]:
    problems: list[str] = []
    for page in pages or [REPO / p for p in VERBATIM_PAGES]:
        page = Path(page)
        src = page.read_text(encoding="utf-8")
        blocks = verbatim_blocks(src)
        visible = re.sub(r"<!--.*?-->|/\*.*?\*/", "", src, flags=re.DOTALL)
        claims = max(len(c.findall(visible)) for c in _CLAIMS)
        if claims > len(blocks):
            problems.append(
                f"{page.name}: {claims} verbatim claim(s), {len(blocks)} block(s) naming "
                f"their source with data-verbatim"
            )
        for path, rows in blocks:
            source = REPO / path
            if not source.is_file():
                problems.append(f"{page.name}: data-verbatim names {path}, not in the tree")
                continue
            lines = source.read_text(encoding="utf-8").splitlines()
            if not rows:
                problems.append(f"{page.name}: data-verbatim block for {path} has no rows")
            at = 0
            for row in rows:
                if row is NO_TEXT:
                    problems.append(f"{page.name}: a row quoting {path} carries no ln span to compare")
                    continue
                try:
                    at = lines.index(row, at) + 1
                except ValueError:
                    problems.append(f"{page.name}: quotes {path}, which has no line {row!r} (in this order)")
    return problems


def is_instance() -> bool:
    """A configured Bridge (it carries its own bridge-config.yaml), not open-bridge itself."""
    return (REPO / "bridge-config.yaml").is_file()


def main() -> int:
    write = "--write" in sys.argv
    files = tracked()
    core_files = [f for f in files if is_core_file(f)]
    user_files = [f[len(USER_PREFIX):] for f in files if f.startswith(USER_PREFIX)]

    core_real = counted(core_files)
    user_real = collections.Counter()
    for fam, n in counted(user_files).items():
        user_real[USER_FOLD.get(fam, fam)] += n

    src = PAGE.read_text(encoding="utf-8")
    pairs = section(src, "PAIRS")
    core_only = section(src, "CORE_ONLY")

    drawn_core = parse(core_only, "c")
    drawn_core.update(parse(pairs, "core"))
    drawn_user = parse(pairs, "user")

    problems: list[str] = []

    for label, drawn, real in (("CORE", drawn_core, core_real),
                               ("USER", drawn_user, user_real)):
        for fam, n in sorted(drawn.items()):
            if real.get(fam, 0) != n:
                problems.append(
                    f"{label} {fam}: figure says {n}, tree has {real.get(fam, 0)}"
                )
        for fam, n in sorted(real.items()):
            if fam not in drawn:
                problems.append(f"{label} {fam}: {n} files in the tree, not drawn")

    core_total, user_total = len(core_files), len(user_files)
    if sum(drawn_core.values()) != core_total:
        problems.append(
            f"CORE total: figure sums to {sum(drawn_core.values())}, tree has {core_total}"
        )
    if sum(drawn_user.values()) != user_total:
        problems.append(
            f"USER total: figure sums to {sum(drawn_user.values())}, tree has {user_total}"
        )

    # The prose beside a count quotes the same number, and --write used to fix
    # the field while leaving the sentence saying something else. A figure whose
    # chip says 112 next to a sentence saying 111 is worse than either alone.
    for var, pairs in (("CORE_ONLY", (("c", ("d_en", "d_de")),)),
                       ("PAIRS", (("core", ("c_en", "c_de")), ("user", ("u_en", "u_de"))))):
        for entry in re.finditer(r"\{[^{}]*\}", section(src, var)):
            text = entry.group(0)
            name = re.search(r'n\s*:\s*"([^"]+)"', text)
            if not name:
                continue
            for num_key, prose_keys in pairs:
                num = re.search(rf"\b{num_key}\s*:\s*(\d+)", text)
                if not num:
                    continue
                for pk in prose_keys:
                    said = re.search(rf'{pk}\s*:\s*"(\d+) ', text)
                    if said and said.group(1) != num.group(1):
                        problems.append(
                            f"{name.group(1)} {pk}: the sentence says {said.group(1)}, "
                            f"the count says {num.group(1)}"
                        )

    # every example path the figure names has to be a file that exists. A
    # renamed skill would otherwise leave a dead path on a public page, and the
    # page is making a point about claims being checkable.
    tracked_set = set(files)
    for m in re.finditer(r'\b(?:ex|cex|uex)\s*:\s*\[([^\]]*)\]', src):
        for raw in re.findall(r'"([^"]+)"', m.group(1)):
            path = raw if raw in tracked_set else USER_PREFIX + raw
            if path not in tracked_set:
                problems.append(f"example path not in the tree: {raw}")

    # The screen reader paragraph names folders with their counts in prose:
    # "with skills at 345 files and scripts at 113 the largest by far". It is a
    # third renderer of the same numbers and it drifted twice through this gap
    # while everything else stayed green, because a sighted reader never sees it.
    for fam, n in core_real.items():
        name = fam.rstrip("/")
        if not name or name.startswith("."):
            continue
        for m in re.finditer(rf"\b{re.escape(name)} (?:at|bei) (\d+)\b", src):
            if int(m.group(1)) != n:
                problems.append(
                    f"screen reader text says {name} has {m.group(1)}, the tree says {n}"
                )

    # the two numbers a reader actually sees, in both languages
    for phrase in (f"{core_total} files ship. {user_total} are yours.",
                   f"{core_total} Dateien kommen mit, {user_total} sind deine."):
        if phrase not in src:
            problems.append(f"caption missing or stale: {phrase!r}")

    explore_problems = problems
    ring_src = RING_PAGE.read_text(encoding="utf-8")
    ring = ring_census(files)
    ring_drift = ring_problems(ring_src, ring)
    quoted = verbatim_problems()
    problems = explore_problems + ring_drift + quoted

    # A configured instance that carries core files of its own (docs, scripts
    # it added) differs from what open-bridge ships BY DESIGN, and the page
    # describes open-bridge. Failing there made the check red in every
    # established instance, and --write would have baked one instance's tree
    # into a CORE page that ships upstream. Report it, never rewrite it.
    if problems and is_instance():
        if write:
            print("check-figure-counts: refusing --write in a configured instance; the page "
                  "describes what open-bridge ships, rewriting it here would make a CORE "
                  "file diverge from upstream.", file=sys.stderr)
            return 2
        print(f"docs/explore.html and docs/index.html describe open-bridge; this instance "
              f"differs in {len(problems)} number(s), expected where it carries core files "
              f"of its own:")
        for p in problems[:5]:
            print(f"  {p}")
        return 0

    if (explore_problems or ring_drift) and write:
        if explore_problems:
            PAGE.write_text(
                rewrite(src, dict(core_real), dict(user_real), core_total, user_total),
                encoding="utf-8",
            )
            print(f"docs/explore.html rewritten: {len(explore_problems)} number(s) brought back to the tree.")
        if ring_drift:
            RING_PAGE.write_text(rewrite_ring(ring_src, ring), encoding="utf-8")
            print(f"docs/index.html rewritten: {len(ring_drift)} ring number(s) brought back to the tree.")
        print("Re-run without --write to confirm, and read the diff before committing:")
        for p in explore_problems + ring_drift:
            print(f"  {p}")
        if quoted:
            # a quote is text, not a count; no rewrite can know what was meant
            print("\nQuoted blocks that --write cannot fix, edit them by hand:", file=sys.stderr)
            for p in quoted:
                print(f"  {p}", file=sys.stderr)
            return 1
        return 0

    if problems:
        print("The docs pages have drifted from the tree:\n", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(
            "\nRun `python3 scripts/check-figure-counts.py --write` to bring the counts "
            "back to the tree, then read the diff. A quoted block (data-verbatim) is "
            "fixed by hand.",
            file=sys.stderr,
        )
        return 1

    print(
        f"docs/explore.html matches the tree: CORE {core_total} in "
        f"{len(drawn_core)} folders, USER {user_total} in {len(drawn_user)}, "
        f"{len(re.findall(chr(34), src))//2 and sum(len(re.findall(chr(34)+'([^'+chr(34)+']+)'+chr(34), m.group(1))) for m in re.finditer(r'\b(?:ex|cex|uex)\s*:\s*\[([^\]]*)\]', src))} example paths all present."
    )
    n_ring = sum(sum(v["kids"].values()) for v in ring.values())
    l_ring = sum(v["lines"] for v in ring.values())
    print(f"docs/index.html ring matches examples/agency: {n_ring} files, {l_ring} lines; "
          f"quoted blocks match their sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
