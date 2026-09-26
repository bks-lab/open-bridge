"""Is the program that runs the program that is KEPT.

`in_sync` compares a unit against the artifact it was rendered from and the
stamp that records the rendering. Neither of those is the program the unit
CALLS. A wrapper that lives outside the repository and drifted from its twin
runs happily forever, and a change in the repository never reaches it, without
an error appearing anywhere. Measured on one machine on 2026-08-25: five such
pairs, and two watchdogs that existed only on that box, a hundred and thirty
lines ahead of the repository's copy, one disk failure from gone.

THIS MODULE DOES NOT DECIDE WHICH SIDE IS RIGHT. In no two of those five pairs
was it the same side: once the repository's version was the maintained one,
once the machine's, and once rolling out would have pointed a fallback path at
nothing. Deciding is a question for a person; NOTICING that two exist and have
come apart is a question for a machine, and that is the half that was missing.

Three answers, and the third is the dangerous one:

  ``in the repository``  the program's path ends in a path the repository
                         itself carries, so it IS that file and drift is
                         structurally impossible.
  ``a copy``             it sits elsewhere and the repository holds a file of
                         the same name. Then the digests decide.
  ``only on the machine``it sits elsewhere and the repository holds no such
                         file at all. This program exists on one disk.

A shared interpreter is not a program, it is the language the program is
written in. Counting `/bin/bash` would make almost every run a copy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping, Sequence

from engine import model
from engine.report import Finding

#: A path suffix has to be at least this many segments before it counts as
#: "the repository's own file". One segment is a bare basename, and a bare
#: basename matching somewhere in a repository is a coincidence, not an
#: identity.
MIN_SUFFIX_SEGMENTS = 2


def program_of(w) -> str:
    """The program this declaration runs, or empty where argv names none.

    The first absolute path that is not a shared interpreter. `command` is
    argv, so the interpreter comes first and the program after it, and on a
    declaration that names only an interpreter there is nothing to ask about.
    """
    execution = getattr(w, "execution", None)
    for part in (getattr(execution, "command", ()) or ()):
        text = str(part)
        if text.startswith("/") and text not in model.SHARED_INTERPRETERS:
            return text
    return ""


def in_repository(program: str, root: Path) -> str:
    """The repository-relative path this program IS, or empty.

    Matched on the SUFFIX rather than on a configured repository root: the
    root belongs to the machine, this function runs wherever `reconcile` was
    started, and a root read from configuration would be a second opinion
    about a fact the path already carries.
    """
    parts = [p for p in str(program or "").split("/") if p]
    for start in range(len(parts) - MIN_SUFFIX_SEGMENTS, -1, -1):
        rel = "/".join(parts[start:])
        if (Path(root) / rel).is_file():
            return rel
    return ""


def twin_of(program: str, root: Path) -> str:
    """A file of the same name inside the repository, or empty.

    First hit in sorted order, so two candidates give the same answer on every
    run rather than whichever the filesystem happened to hand over first. No
    hidden folder is a source: not the git directory, and not `.claude/worktrees/`
    or `.bridge/`, which hold working copies. On 2026-09-26 a leftover agent
    worktree sorted before `infra/`, its older copy became the twin, and a
    program identical to the kept source was reported as drifted.
    """
    name = Path(str(program or "")).name
    if not name:
        return ""
    for found in sorted(Path(root).rglob(name)):
        rel_parts = found.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts[:-1]) or not found.is_file():
            continue
        return str(found.relative_to(root))
    return ""


def digest_of(path: Path) -> str:
    """The same digest the host is asked for, computed here on a local file."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


#: What a reader is told about where a program sits. Phrases rather than codes,
#: because they are printed as they are: a page that says `copy_differs` has
#: moved the explaining back onto the reader.
WHERE_REPO = "in this repository"
WHERE_ONLY_HERE = "only on the machine, no copy in this repository"
WHERE_AGREE = "a copy of {rel}, and today they agree"
WHERE_APART = "a copy of {rel}, and they have come apart"
WHERE_UNASKED = "a copy of {rel}, and nothing here compared the two"
WHERE_NO_PROGRAM = ""


def describe(w, root, digests: Mapping[str, str]) -> tuple:
    """`(program, where)` for one declaration. The one derivation of both.

    `findings` is built on this rather than beside it: a page that says "in
    this repository" while a finding says the copy has drifted would be two
    answers to one question, and the second reader would believe whichever
    they saw first.
    """
    program = program_of(w)
    if not program:
        return "", WHERE_NO_PROGRAM
    if in_repository(program, root):
        return program, WHERE_REPO
    twin = twin_of(program, root)
    if not twin:
        return program, WHERE_ONLY_HERE
    theirs = (digests or {}).get(program, "")
    if not theirs:
        return program, WHERE_UNASKED.format(rel=twin)
    try:
        mine = digest_of(Path(root) / twin)
    except OSError:
        return program, WHERE_UNASKED.format(rel=twin)
    shape = WHERE_AGREE if mine == theirs else WHERE_APART
    return program, shape.format(rel=twin)


def findings(workloads: Sequence, root, digests: Mapping[str, str]) -> list[Finding]:
    """One verdict per declaration whose program is not the repository's own.

    A digest nobody read leaves NO finding: not asked is not absent, the same
    rule the marker and the off-list already carry. A run whose copy agrees
    with its twin today leaves none either, because a sentence per healthy run
    is how a section stops being read.
    """
    out: list[Finding] = []
    for w in workloads or ():
        if getattr(w, "is_retired", False):
            continue
        program, where = describe(w, root, digests)
        if not program:
            continue
        if where == WHERE_ONLY_HERE:
            out.append(Finding(
                workload_id=w.id, state=model.WorkloadState.source_drift,
                severity=model.Severity.medium,
                detail=(f"{w.id} runs {program}, which is outside this "
                        f"repository and has no file of that name inside it, "
                        f"so this program exists on one disk only"),
                hint=("keep it in the repository and roll it out from there, "
                      "or record here why one copy is enough"),
                source="declaration"))
        elif where.endswith("they have come apart"):
            out.append(Finding(
                workload_id=w.id, state=model.WorkloadState.source_drift,
                severity=model.Severity.medium,
                detail=(f"{w.id} runs {program}, and the copy on the machine "
                        f"no longer matches its file in this repository, so a "
                        f"change there does not reach this run and nothing "
                        f"reports it"),
                hint=("compare the two and decide which one is the maintained "
                      "side; this page does not decide that"),
                source="machine"))
    return out


def described(workloads: Sequence, root, digests: Mapping[str, str]) -> dict:
    """`{id: (program, where)}`, for a renderer that shows the healthy case too.

    The negative answer is worth printing: twenty-three rows saying "in this
    repository" are what make the twenty-fourth legible.
    """
    out = {}
    for w in workloads or ():
        program, where = describe(w, root, digests)
        if program:
            out[w.id] = (program, where)
    return out
