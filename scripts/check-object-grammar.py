#!/usr/bin/env python3
"""Hold the copies of the object reference grammar to one source, and keep
object references out of everything a session reads before its first answer.

THE GRAMMAR. `infra/object-stores/_schema.yaml` is the source: the `name`
pattern (the shape of a store name), the `backend` enum, and `$defs/reference`
(object://<store>/<key>). Two other places carry it as a literal rather than a
read, on purpose:

* `skills/object-store/objstore/refs.py` parses references, and the skill has
  to keep working when its directory is lifted out of the repo on its own.
* `infra/object-stores/_template.yaml` tells the person writing a declaration
  which backends exist.

The schema is also checked against itself: its reference pattern and its
address pattern have to use the same store shape as its name pattern.

Text is compared where text is the thing (the backend list, the store shape,
the scheme). The reference itself is compared by BEHAVIOUR: a fixed list of
sample references goes through the schema's pattern and through the resolver's
own `parse`, and every answer has to match. A first version compared constants
only, while the parser used a regular expression of its own that no constant
fed, so a changed parser passed; and the schema accepted `object://s/../x`,
which the parser refused, from the first commit on.

docs/object-store.md decided this from its first commit, because the secret
grammar did not: its six copies had drifted apart before anything compared
them, and `scripts/check-secret-grammar.py` was written afterwards.

THE PLACEMENT. The ADR's last content rule is a hard never: a store may hold
what a session opens later, never what a session needs to start. So no FILE on
the always-on surface may carry a concrete reference. "Always-on" is whatever
`scripts/measure-context.py` measures, the one definition every other guard
uses, minus its `cmd:` items: those are the output of a command run at session
start (the work log slice, the config slice), and a log row that MENTIONS where
a recording went is the entry tracking its reference, which the ADR asks for,
not content a session needs to start. A placeholder such as
object://<store>/<key> is grammar, not a reference.

    python3 scripts/check-object-grammar.py            # compare, report, exit non-zero on a finding
    python3 scripts/check-object-grammar.py --json     # the same as data
    python3 scripts/check-object-grammar.py --mutate   # prove both checks bite
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SCHEMA = "infra/object-stores/_schema.yaml"
ENGINE = "skills/object-store/objstore/refs.py"
TEMPLATE = "infra/object-stores/_template.yaml"

#: A concrete reference: a real store name and a key. `<store>` does not match.
CONCRETE = re.compile(r"object://[a-z][a-z0-9-]*/[^\s`'\")>\]]+")

#: Sample references both the schema and the resolver have to answer alike.
#: Chosen at the edges: dots that are and are not a segment, empty segments,
#: case, a leading digit, a backslash, whitespace, another scheme.
SAMPLES = (
    "object://recordings/a.m4a", "object://r/a/b/c", "object://a-b/x.y",
    "object://r/.hidden", "object://r/..x", "object://r/x..",
    "object://r/../x", "object://r/./x", "object://r//x", "object://r/",
    "object://R/x", "object://9r/x", "object://r/a\\b", "object://r/a b",
    "object://r/a/..", "object://r/a/.", "object://r", "object:/r/x", "s3://b/k",
)

_PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from objstore import refs
out = []
for sample in json.loads(sys.stdin.read()):
    try:
        refs.parse(sample)
        out.append(True)
    except Exception:
        out.append(False)
print(json.dumps(out))
"""


def read(path: str, repo: Path) -> str:
    full = repo / path
    return full.read_text(encoding="utf-8") if full.exists() else ""


def _bare(pattern: str) -> str:
    return pattern[1:-1] if pattern.startswith("^") and pattern.endswith("$") else pattern


def read_source(repo: Path = REPO) -> dict:
    """The grammar as the schema states it."""
    import yaml

    text = read(SCHEMA, repo)
    if not text:
        return {}
    schema = yaml.safe_load(text) or {}
    props = schema.get("properties") or {}
    return {
        "backends": set((props.get("backend") or {}).get("enum") or []),
        "store": _bare(str((props.get("name") or {}).get("pattern") or "")),
        "reference": str(((schema.get("$defs") or {}).get("reference") or {}).get("pattern") or ""),
        "addresses": str(((props.get("addresses") or {}).get("items") or {}).get("pattern") or ""),
    }


def read_engine(text: str) -> dict:
    backends = re.search(r"^BACKENDS\s*=\s*\(([^)]*)\)", text, re.M)
    store = re.search(r'^STORE_PATTERN\s*=\s*"([^"]*)"', text, re.M)
    scheme = re.search(r'^SCHEME\s*=\s*"([^"]*)"', text, re.M)
    return {
        "backends": set(re.findall(r'"([a-z0-9-]+)"', backends.group(1))) if backends else set(),
        "store": store.group(1) if store else "",
        "scheme": scheme.group(1) if scheme else "",
    }


def engine_answers(repo: Path):
    """What the resolver's own `parse` says to each sample, or None when it cannot load.

    In a child process, so that a fake repo's copy of the package is what gets
    imported and not whatever an earlier call left in sys.modules.
    """
    skill = repo / "skills" / "object-store"
    done = subprocess.run([sys.executable, "-c", _PROBE, str(skill)], input=json.dumps(SAMPLES),
                          capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        return None
    return json.loads(done.stdout)


def read_template(text: str) -> set:
    match = re.search(r"^backend:\s*\S+\s*#\s*([a-z0-9| -]+)$", text, re.M)
    if not match:
        return set()
    return {part.strip() for part in match.group(1).split("|") if part.strip()}


def compare(repo: Path = REPO) -> tuple[dict, list]:
    """The measured grammar per copy, and one line per disagreement."""
    problems: list = []
    source = read_source(repo)
    if not source:
        return {}, [f"{SCHEMA}: missing, and it is the source of the object grammar"]
    measured = {"schema": {"backends": sorted(source["backends"]), "store": source["store"]}}

    # the schema against itself
    if not source["reference"].startswith(f"^object://{source['store']}/"):
        problems.append(f"{SCHEMA}: $defs/reference is {source['reference']!r}, which does not "
                        f"start with the store shape of the name pattern")
    expected_addresses = f"^(\\*|{source['store']}\\*?)$"
    if source["addresses"] != expected_addresses:
        problems.append(f"{SCHEMA}: the addresses pattern is {source['addresses']!r}, the store "
                        f"shape makes it {expected_addresses!r}; an address could name a store no "
                        f"reference can")

    # the engine
    text = read(ENGINE, repo)
    if not text:
        problems.append(f"{ENGINE}: missing, and the resolver is supposed to carry the grammar")
    else:
        engine = read_engine(text)
        measured["engine"] = {"backends": sorted(engine["backends"]), "store": engine["store"],
                              "scheme": engine["scheme"]}
        extra, lost = engine["backends"] - source["backends"], source["backends"] - engine["backends"]
        if extra:
            problems.append(f"{ENGINE}: implements {', '.join(sorted(extra))}, which {SCHEMA} "
                            f"does not allow; a declaration using it is refused by the schema")
        if lost:
            problems.append(f"{ENGINE}: does not implement {', '.join(sorted(lost))}, which {SCHEMA} "
                            f"allows; a declaration using it validates and resolves to nothing")
        if engine["store"] != source["store"]:
            problems.append(f"{ENGINE}: the store pattern is {engine['store']!r}, the schema says "
                            f"{source['store']!r}; a reference parses here and not there")
        if engine["scheme"] != "object":
            problems.append(f"{ENGINE}: the scheme is {engine['scheme']!r}, the schema's reference "
                            f"starts with object://")
        answers = engine_answers(repo)
        if answers is None:
            problems.append(f"{ENGINE}: the resolver's parser could not be loaded, so its answers "
                            f"cannot be compared with the schema's")
        else:
            pattern = re.compile(source["reference"])
            for sample, engine_says in zip(SAMPLES, answers):
                schema_says = pattern.match(sample) is not None
                if schema_says != engine_says:
                    problems.append(
                        f"{ENGINE}: parses {sample!r} as {'valid' if engine_says else 'invalid'}, "
                        f"the schema's reference pattern says {'valid' if schema_says else 'invalid'}")

    # the template
    text = read(TEMPLATE, repo)
    if not text:
        problems.append(f"{TEMPLATE}: missing")
    else:
        advertised = read_template(text)
        measured["template"] = {"backends": sorted(advertised)}
        if advertised != source["backends"]:
            problems.append(f"{TEMPLATE}: names backends {' | '.join(sorted(advertised)) or 'none'}, "
                            f"the schema allows {' | '.join(sorted(source['backends']))}")
    return measured, problems


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------

def references_in(parts: dict) -> list:
    """One line per concrete object reference in an always-on part."""
    found = []
    for where, text in parts.items():
        for match in CONCRETE.finditer(text or ""):
            found.append(f"{where}: carries {match.group(0)}, and a session reads it before its "
                         f"first answer; a store may never hold what a session needs to start")
    return found


def _meter(repo: Path):
    spec = importlib.util.spec_from_file_location("measure_context", repo / "scripts" / "measure-context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def always_on_files(parts: dict) -> dict:
    """The always-on parts that are files, without the output of session-start commands."""
    return {where: text for where, text in parts.items() if not where.startswith("cmd:")}


def placements(repo: Path = REPO) -> list:
    # The meter's CODE comes from this checkout and its DATA from `repo`: a
    # fake repository in a test carries no scripts/ of its own.
    meter = _meter(REPO)
    return references_in(always_on_files(meter.always_on_parts(repo, meter.load_budget(repo))))


def render(measured: dict, problems: list, placed: list) -> str:
    lines = [f"{name:<9} {json.dumps(value, sort_keys=True)}" for name, value in measured.items()]
    lines.append("")
    findings = problems + placed
    if findings:
        lines.append(f"{len(findings)} finding(s):")
        lines.extend(f"  - {item}" for item in findings)
    else:
        lines.append(f"every copy carries the grammar of {SCHEMA}, and nothing always-on points at an object")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# --mutate: the proof over the proof
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Needle:
    name: str
    path: str
    search: str
    replace: str
    scar: str
    #: A finding the needle has to produce. ANY finding is not enough: a needle
    #: that trips some other rule proves nothing about the one it names.
    expect: str


NEEDLES = (
    Needle("the resolver implements a backend the schema does not allow", ENGINE,
           'BACKENDS = ("local", "s3")', 'BACKENDS = ("local", "s3", "ftp")',
           "A backend written down in one place and refused in the other is the keeper:// case.",
           expect="implements ftp"),
    Needle("the resolver loses a backend", ENGINE,
           'BACKENDS = ("local", "s3")', 'BACKENDS = ("local",)',
           "A declaration the schema accepts would resolve to nothing.",
           expect="does not implement s3"),
    Needle("the resolver's store shape drifts", ENGINE,
           'STORE_PATTERN = "[a-z][a-z0-9-]*"', 'STORE_PATTERN = "[a-z0-9-]+"',
           "A reference would parse in the resolver and fail the schema, or the other way round.",
           expect="the store pattern is"),
    Needle("the resolver's parser stops checking key segments", ENGINE,
           'SEGMENT = r"(?!\\.\\.?(?:/|$))[^/\\s\\\\]+"', 'SEGMENT = r"[^/\\s\\\\]+"',
           "A key with .. validates nowhere and resolves one level above the store's root.",
           expect="'object://r/../x' as valid"),
    Needle("the resolver's parser accepts another scheme", ENGINE,
           '_prefix = "^" + SCHEME + "://"', '_prefix = "^[a-z0-9]+://"',
           "A backend URI is read as a reference, which the constants alone never showed.",
           expect="'s3://b/k' as valid"),
    Needle("the template advertises a backend", TEMPLATE,
           "# local | s3\n", "# local | s3 | gcs\n",
           "A person copies the template and writes a backend nothing implements.",
           expect="gcs"),
    Needle("the schema's reference loses its key rule", SCHEMA,
           "pattern: '^object://[a-z][a-z0-9-]*/(?!", "pattern: '^object://[a-z][a-z0-9-]*/(?:",
           "The source would accept a key the resolver refuses, the state the first commit had.",
           expect="the schema's reference pattern says valid"),
    Needle("the schema's addresses accept anything", SCHEMA,
           'pattern: "^(\\\\*|[a-z][a-z0-9-]*\\\\*?)$"', 'pattern: "^(\\\\*|[a-z][a-z0-9-]*\\\\*?|.*)$"',
           "An address could name a store no reference can reach, and nobody would notice.",
           expect="the addresses pattern is"),
    # AGENTS.md, never a CLAUDE.md: writing one into the copy would make it the
    # entry and shadow AGENTS.md. The heading is kept verbatim on purpose.
    Needle("an always-on file points at an object", "AGENTS.md",
           "## Session Start Detection (automatic)\n",
           "## Session Start Detection (automatic)\nsee object://recordings/2026-09/kickoff.m4a\n",
           "Session start would depend on a store being reachable.",
           expect="AGENTS.md: carries object://recordings/"),
)


def _scratch_copy(repo: Path) -> Path:
    """The tracked files of `repo`, copied to a throwaway directory.

    The needles are applied THERE and never to the working tree, so a run that
    is killed half way leaves nothing softened behind. The secret grammar check
    edits the real files and restores them in a `finally`, which a SIGKILL skips.
    """
    scratch = Path(tempfile.mkdtemp(prefix="object-grammar-mutate-"))
    listed = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    names = [n for n in listed.stdout.decode("utf-8", "replace").split("\0") if n] \
        if listed.returncode == 0 else []
    if not names:
        shutil.copytree(repo, scratch, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".bridge"))
        return scratch
    for name in names:
        source = repo / name
        if source.is_file():
            target = scratch / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return scratch


def mutate(repo: Path = REPO) -> int:
    """Soften one copy at a time, in a scratch copy of the tree, and demand its finding."""
    failures = 0
    scratch = _scratch_copy(repo)
    try:
        failures = _run_needles(scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("")
    print(f"{len(NEEDLES)} needles, {len(NEEDLES) - failures} bit")
    return 1 if failures else 0


def _run_needles(repo: Path) -> int:
    failures = 0
    for needle in NEEDLES:
        target = repo / needle.path
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        if original.count(needle.search) != 1:
            print(f"GREEN (anchor gone)  {needle.name}: {needle.search!r} appears "
                  f"{original.count(needle.search)} times in {needle.path}, so this needle has "
                  f"been proving nothing")
            failures += 1
            continue
        target.write_text(original.replace(needle.search, needle.replace, 1), encoding="utf-8")
        try:
            findings = compare(repo)[1] + placements(repo)
        finally:
            target.write_text(original, encoding="utf-8")
        if any(needle.expect in finding for finding in findings):
            print(f"red   {needle.name}")
        elif findings:
            print(f"GREEN {needle.name}: other findings, not the one this needle names "
                  f"({needle.expect!r}). {needle.scar}")
            failures += 1
        else:
            print(f"GREEN {needle.name}: the check did not notice. {needle.scar}")
            failures += 1
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine readable output")
    parser.add_argument("--mutate", action="store_true",
                        help="soften each copy in turn and demand that this check goes red")
    parser.add_argument("--repo", default=str(REPO), help="repository root (default: this one)")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()

    if args.mutate:
        return mutate(repo)

    measured, problems = compare(repo)
    placed = placements(repo)
    if args.json:
        print(json.dumps({"grammar": measured, "problems": problems, "placements": placed}, indent=2))
    else:
        print(render(measured, problems, placed))
    return 1 if problems or placed else 0


if __name__ == "__main__":
    sys.exit(main())
