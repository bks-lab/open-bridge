"""The plaintext-pattern parity check, tested against the drift it is for.

Two layers, and the second is the one that matters. The first walks the real
repo and asserts that every copy of the pattern list agrees today. The second
builds small fake repos where one copy has drifted, in each of the ways these
copies have actually drifted, and asserts that the check says so and names the
file. A guard that has only ever run against a green tree has never been
measured.

The comparison under test is by MARKER, never by regular expression. Two
scanners can spell the same pattern differently and both be right: `ghp_` and
`gh[pousr]_` are one pattern, and a comparison that demanded the literal would
report a gap where there is none. What matters is that no copy is blind to a
shape the others know.

One thing worth saying about the fixtures. Every fake repo gets a COPY of the
real `skills/secrets/engine/patterns.py`, because `compare` imports it as
Python and reads `copies`, `aliases` and `note` off each pattern. A fake source
list would measure a fake.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_secret_patterns", REPO / "scripts" / "check-secret-patterns.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()
patterns = check.load_patterns(REPO)


def demanded(copy_name: str) -> list:
    """The patterns that copy is required to carry, from the source list."""
    return [pattern for pattern in patterns.ALL if copy_name in pattern.copies]


def markers_found(block: str, copy_name: str) -> list:
    """What `compare` would count as carried, given this block of text."""
    return [pattern.marker for pattern in demanded(copy_name)
            if any(spelling in block
                   for spelling in (pattern.marker, *pattern.aliases))]


# ---------------------------------------------------------------------------
# the live tree
# ---------------------------------------------------------------------------

def test_the_skill_is_where_the_list_comes_from():
    assert patterns.MARKERS, "the source list is empty, so every copy agrees with nothing"
    assert set(patterns.MARKERS) >= {"AKIA", "ghp_", "AIza", "github_pat_"}, (
        "the four shapes this check was written for are the ones that had "
        "drifted; they may not quietly leave the source")


def test_every_copy_in_this_repo_carries_what_the_source_asks_of_it():
    measured, problems = check.compare(REPO)
    assert problems == [], "\n".join(problems)
    assert set(measured) == {"source", "overlay", "promote"}


def test_the_command_line_reports_green_on_this_repo(capsys):
    assert check.main(["--repo", str(REPO)]) == 0
    assert "every copy carries the patterns" in capsys.readouterr().out


def test_the_json_form_carries_the_markers_and_the_problems(capsys):
    assert check.main(["--json", "--repo", str(REPO)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["problems"] == []
    assert payload["markers"]["overlay"], "the overlay column came back empty and green"


def test_render_names_every_copy_and_the_verdict():
    text = check.render(*check.compare(REPO))
    for name in ("source", "overlay", "promote"):
        assert name in text
    assert "every copy carries the patterns" in text


# ---------------------------------------------------------------------------
# the mutation anchors
# ---------------------------------------------------------------------------

def test_every_mutation_anchor_still_stands_in_the_file_it_names():
    # A needle whose anchor has drifted applies to nothing and proves nothing
    # from that day on, silently. This is the cheap check for that.
    for name, path, search, _replace, _scar in check.NEEDLES:
        text = (REPO / path).read_text(encoding="utf-8")
        assert search in text, f"{name}: {search!r} is not in {path} any more"


def test_every_mutation_anchor_stands_exactly_once_in_the_block_that_is_compared():
    # The count that makes a needle mean what its name says, and the reason it
    # is measured on the BLOCK rather than on the file: `AKIA` stands three
    # times in rules/promote-safety.md and only once in the table this check
    # reads. The other two are in a shell snippet further down, which nothing
    # compares (see the last case in this file).
    extractors = {check.OVERLAY: check.overlay_block, check.PROMOTE: check.promote_block}
    for name, path, search, _replace, _scar in check.NEEDLES:
        block = extractors[path]((REPO / path).read_text(encoding="utf-8"))
        assert block.count(search) == 1, (
            f"{name}: {search!r} stands {block.count(search)} times in the block "
            f"of {path} that is compared")


def test_every_needle_softens_a_copy_until_the_check_goes_red(tmp_path, capsys):
    # `--mutate` on a throwaway repo rather than on the working tree. The real
    # run rewrites a tracked file and puts it back in a `finally`; a suite that
    # did that would leave the repository half-softened whenever a case failed
    # in between.
    repo = _fake_repo(tmp_path)
    assert check.mutate(repo) == 0
    printed = capsys.readouterr().out
    assert f"{len(check.NEEDLES)} needles, {len(check.NEEDLES)} bit" in printed
    assert "GREEN" not in printed


def test_a_needle_whose_anchor_is_gone_is_reported_rather_than_counted(tmp_path, capsys):
    # The other direction: the anchor missing must not read as "the check
    # noticed". It is the silent failure this whole mechanism is exposed to.
    repo = _fake_repo(tmp_path, overlay=[marker for marker in _default("overlay")
                                         if marker != "AIza"])
    assert check.mutate(repo) == 1
    assert "anchor gone" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the fake repos
# ---------------------------------------------------------------------------

def _default(copy_name: str) -> list:
    return [pattern.marker for pattern in demanded(copy_name)]


def _overlay_file(markers) -> str:
    """`scripts/overlay.py` reduced to the list this check reads.

    The first entry is the private-key header on purpose: its character class
    holds a `]`, which is what the extractor once stopped at.
    """
    body = "".join('    re.compile(r"%s"),\n' % marker for marker in markers)
    return ("import re\n\n"
            "# A mention of AKIA up here is prose and must not count.\n"
            "RAW_SECRET_PATTERNS = [\n" + body + "]\n\n"
            "RAW_ASSIGN = re.compile(r\"(?i)password\\s*[:=]\")\n")


def _promote_file(markers) -> str:
    """`rules/promote-safety.md` reduced to the table this check reads."""
    rows = "".join("| a shape | `%s` |\n" % marker for marker in markers)
    return ("# Promote safety\n\n"
            "### Something else entirely\n\n"
            "Prose mentioning ghp_ and AIza, which must not count.\n\n"
            "### Hardcoded universal patterns (always active)\n\n"
            "| Category | Regex |\n|---|---|\n" + rows + "\n"
            "### User-configured blocklist\n\n"
            "More prose, mentioning AKIA, that is not the table.\n")


def _fake_repo(tmp_path: Path, *, overlay=None, promote=None) -> Path:
    """A repo with the real source list and two copies a case can doctor."""
    source = tmp_path / check.SOURCE
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / check.SOURCE, source)

    target = tmp_path / check.OVERLAY
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_overlay_file(_default("overlay") if overlay is None else overlay),
                      encoding="utf-8")

    target = tmp_path / check.PROMOTE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_promote_file(_default("promote") if promote is None else promote),
                      encoding="utf-8")
    return tmp_path


def test_the_fake_repo_is_green_before_a_case_breaks_it(tmp_path):
    # Every case below reads "and now it is red". None of them means anything
    # unless this one is green first.
    _, problems = check.compare(_fake_repo(tmp_path))
    assert problems == [], problems


def test_an_overlay_list_that_lost_a_marker_is_reported_with_its_file(tmp_path):
    repo = _fake_repo(tmp_path, overlay=[m for m in _default("overlay") if m != "AIza"])
    _, problems = check.compare(repo)
    assert any(check.OVERLAY in problem and "AIza" in problem for problem in problems), problems


def test_the_report_says_what_the_lost_pattern_was_for(tmp_path):
    # A gap that only says "missing" is a diff. The note is the sentence that
    # tells the reader whether this is the shape they just walked past.
    repo = _fake_repo(tmp_path, overlay=[m for m in _default("overlay") if m != "AIza"])
    _, problems = check.compare(repo)
    named = [problem for problem in problems if "AIza" in problem]
    assert named and "google-api-key" in named[0], named
    assert "known to the instance rule" in named[0], named


def test_a_promote_table_that_lost_a_marker_is_reported_with_its_file(tmp_path):
    repo = _fake_repo(tmp_path, promote=[m for m in _default("promote") if m != "AKIA"])
    _, problems = check.compare(repo)
    assert any(check.PROMOTE in problem and "AKIA" in problem for problem in problems), problems
    assert not any(check.OVERLAY in problem for problem in problems), problems


def test_the_two_copies_are_compared_separately(tmp_path):
    # One list losing a shape says nothing about the other, and a check that
    # reported both would send the reader to the wrong file.
    repo = _fake_repo(tmp_path, overlay=["AKIA"], promote=_default("promote"))
    _, problems = check.compare(repo)
    assert all(check.OVERLAY in problem for problem in problems), problems
    assert len(problems) == len(demanded("overlay")) - 1


def test_a_copy_that_is_missing_entirely_is_a_problem_and_not_a_pass(tmp_path):
    repo = _fake_repo(tmp_path)
    (repo / check.OVERLAY).unlink()
    measured, problems = check.compare(repo)
    assert any(check.OVERLAY in problem and "missing" in problem for problem in problems), problems
    assert measured["overlay"] == []


def test_a_block_that_cannot_be_found_is_a_problem_and_not_an_empty_comparison(tmp_path):
    # The silent failure this check is most exposed to: a rename or a reformat
    # leaves the extractor matching nothing, every pattern then counts as
    # absent, and the loudest possible output would be the right one. Saying
    # "nothing was compared" is what keeps a green run from meaning two things.
    repo = _fake_repo(tmp_path)
    (repo / check.OVERLAY).write_text("SECRET_PATTERNS = []\n", encoding="utf-8")
    _, problems = check.compare(repo)
    assert any("the pattern block was not found" in problem for problem in problems), problems


def test_a_pattern_that_declares_no_copies_is_demanded_nowhere(tmp_path):
    # An IBAN, a tax id and the key-and-value heuristic are deliberately not in
    # the other two lists: a promote scan is not where personal data is
    # decided, and the overlay scan runs no key-and-value heuristic over code
    # because there it is wrong more often than right.
    homeless = [pattern for pattern in patterns.ALL if not pattern.copies]
    assert homeless, "the case is about patterns that belong to no copy, and there are none"
    _, problems = check.compare(_fake_repo(tmp_path))
    for pattern in homeless:
        assert not any(pattern.name in problem for problem in problems), problems


def test_a_copy_may_carry_more_than_it_is_asked_for(tmp_path):
    # The comparison is one directional on purpose. A scanner that knows an
    # extra shape is not drift, it is a scanner doing its job.
    repo = _fake_repo(tmp_path, overlay=[*_default("overlay"), "IBAN", "Steuer"])
    _, problems = check.compare(repo)
    assert problems == [], problems


def test_an_alias_counts_as_the_marker(tmp_path):
    # `gh[pousr]_` in a regex IS `ghp_` plus its siblings. A comparison that
    # demanded the literal would report a gap in a copy that is strictly wider
    # than the one it is compared against.
    spellings = [m for m in _default("overlay") if m != "ghp_"] + ["gh[pousr]_"]
    repo = _fake_repo(tmp_path, overlay=spellings)
    _, problems = check.compare(repo)
    assert problems == [], problems


def test_an_alias_of_one_pattern_does_not_satisfy_another(tmp_path):
    # The other half. Aliases are per pattern, so a copy that spells one
    # pattern widely is still missing everything else.
    repo = _fake_repo(tmp_path, overlay=["gh[pousr]_"])
    _, problems = check.compare(repo)
    assert not any("github-token" in problem for problem in problems), problems
    assert any("aws-access-key" in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# the extractors, one block each
# ---------------------------------------------------------------------------

#: What the overlay extractor was before it was anchored: non greedy to the
#: first `]`. Kept here as a fixture rather than as a memory, because the case
#: below is only meaningful next to the thing it replaced.
NAIVE_OVERLAY = re.compile(r"RAW_SECRET_PATTERNS\s*=\s*\[(.*?)\]", re.DOTALL)


def test_the_overlay_extractor_reads_only_its_own_list():
    text = ("# AKIA and AIza in a comment up here\n"
            "RAW_SECRET_PATTERNS = [\n"
            '    re.compile(r"\\bASIA[0-9A-Z]{16}\\b"),\n'
            "]\n"
            "# and ghp_ in one down here\n")
    block = check.overlay_block(text)
    assert "ASIA" in block
    for elsewhere in ("AKIA", "AIza", "ghp_"):
        assert elsewhere not in block, f"{elsewhere} was counted from prose outside the list"


def test_the_overlay_extractor_does_not_stop_at_a_bracket_inside_a_character_class():
    # THE REGRESSION. The first entry of that list is the private-key header,
    # whose `[A-Z ]*PRIVATE KEY` holds a `]`. A non greedy match to the first
    # `]` stopped there, so the extractor returned one line, the comparison
    # counted one pattern where the file carries eleven, and the check reported
    # green on ten shapes it had never looked at.
    text = (REPO / check.OVERLAY).read_text(encoding="utf-8")
    anchored = markers_found(check.overlay_block(text), "overlay")
    naive = markers_found(NAIVE_OVERLAY.search(text).group(1), "overlay")

    assert len(anchored) == len(demanded("overlay"))
    assert len(naive) == 1, (
        "the fixture stopped reproducing the bug, so this case proves nothing")
    assert naive == ["BEGIN"], naive


def test_the_overlay_extractor_reads_every_line_of_a_multi_line_list(tmp_path):
    # The same property stated without the historical regex, so the case
    # survives the day somebody deletes the fixture above.
    repo = _fake_repo(tmp_path)
    block = check.overlay_block((repo / check.OVERLAY).read_text(encoding="utf-8"))
    assert len(block.splitlines()) == len(demanded("overlay"))


def test_the_promote_extractor_reads_only_its_section():
    text = _promote_file(["ASIA"])
    block = check.promote_block(text)
    assert "ASIA" in block
    for elsewhere in ("ghp_", "AIza", "AKIA"):
        assert elsewhere not in block, (
            f"{elsewhere} was counted from prose in another section of the same file")


def test_the_promote_extractor_stops_at_the_next_heading():
    block = check.promote_block(_promote_file(["ASIA"]))
    assert "User-configured blocklist" not in block


def test_the_promote_extractor_reads_to_the_end_when_its_section_is_last():
    text = ("### Hardcoded universal patterns (always active)\n\n"
            "| Category | Regex |\n|---|---|\n| a shape | `AKIA` |\n")
    assert "AKIA" in check.promote_block(text)


@pytest.mark.parametrize("missing", ["heading", "everything"])
def test_a_promote_file_without_the_section_compares_nothing_and_says_so(tmp_path, missing):
    repo = _fake_repo(tmp_path)
    text = "" if missing == "everything" else "# Promote safety\n\nNo table here.\n"
    (repo / check.PROMOTE).write_text(text, encoding="utf-8")
    _, problems = check.compare(repo)
    assert any("the pattern block was not found" in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# the placement rule says what the list means
# ---------------------------------------------------------------------------

def test_the_placement_rule_says_credential_identifiers_are_secrets():
    # An access key ID cannot sign a request alone, which is the argument for
    # pasting it into an account file. The rule answers that argument, and
    # this case holds the answer to the list it points at: the day the source
    # list drops the AWS shapes, or the rule stops naming the list, the
    # sentence "the scanner flags it" is no longer true.
    rule = (REPO / "rules" / "secret-placement.md").read_text(encoding="utf-8")
    heading = "## What counts as a secret"
    assert heading in rule, "the placement rule lost its section on identifiers"
    section = rule.split(heading, 1)[1].split("\n## ", 1)[0]
    for marker in ("AKIA", "ASIA"):
        assert marker in patterns.MARKERS, f"{marker} left the source list"
        assert f"`{marker}`" in section, f"the section no longer names {marker}"
    source = "skills/secrets/engine/patterns.py"
    assert source in section and (REPO / source).is_file()
    assert "access key ID" in section
    template = (REPO / "identity" / "accounts" / "_template.yaml").read_text(encoding="utf-8")
    assert "access key ID" in template, (
        "the account template is where the ID gets pasted; it has to say so there")


# ---------------------------------------------------------------------------
# the copy nothing compares
# ---------------------------------------------------------------------------

#: The shell scan `rules/promote-safety.md` hands a person to run before a
#: commit, as an alternation of the shapes it looks for.
SHELL_SCAN = re.compile(r"^UNIVERSAL='(.+)'$", re.MULTILINE)


def test_the_shell_scan_in_the_promote_rule_knows_what_its_own_table_knows():
    # This case was written red, and the red was the point.
    #
    # `rules/promote-safety.md` carries the pattern list TWICE: as the table
    # this check compares, and as a `$UNIVERSAL` alternation in the pre-commit
    # recipe further down, which is the form somebody actually runs. The table
    # was brought up to date on 2026-09-20; the recipe was not. Measured that
    # day it knows five shapes fewer than its own table: `ssh-rsa`,
    # `github_pat_`, `AIza`, `eyJ` and `Bearer `, four of them the very ones
    # the drift story is about. So a promote scanned with the documented
    # one-liner walks past a fine-grained GitHub token, a Google API key and a
    # pasted JWT while the table in the same file says all three are never
    # CORE appropriate. The rule carries the snippet twice, at both places a
    # reader is sent to it. Both were brought up to the table on the same day,
    # which is what this case now holds them to: the table and the one-liner in
    # the same file may not know different things again.
    text = (REPO / check.PROMOTE).read_text(encoding="utf-8")
    snippets = SHELL_SCAN.findall(text)
    assert snippets, "the promote rule stopped carrying a shell scan at all"
    for number, snippet in enumerate(snippets, 1):
        missing = [pattern.marker for pattern in demanded("promote")
                   if not any(spelling in snippet
                              for spelling in (pattern.marker, *pattern.aliases))]
        assert missing == [], (
            f"the shell scan of the promote rule (occurrence {number}) does not "
            f"know {missing}, and the table in the same file says it must")
