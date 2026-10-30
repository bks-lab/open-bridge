"""The object grammar check, tested against the drift it is supposed to catch.

Two layers, as for the secret grammar. The first walks the real repo and asserts
that every copy agrees today and that nothing a session reads before its first
answer points at an object. The second builds small fake repos where one copy
has drifted and asserts that the check says so and names the file. A guard that
only ever runs against a green tree has never been measured.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

COPIED = (
    "infra/object-stores/_schema.yaml",
    "infra/object-stores/_template.yaml",
    "skills/object-store/objstore/__init__.py",
    "skills/object-store/objstore/errors.py",
    "skills/object-store/objstore/refs.py",
)


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_object_grammar", REPO / "scripts" / "check-object-grammar.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


grammar = _load()


def fake_repo(tmp_path: Path) -> Path:
    for rel in COPIED:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, target)
    return tmp_path


def edit(repo: Path, rel: str, old: str, new: str) -> None:
    path = repo / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"anchor {old!r} is not unique in {rel}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def problems_in(repo: Path) -> list:
    return grammar.compare(repo)[1]


# ---------------------------------------------------------------------------
# the live tree
# ---------------------------------------------------------------------------

def test_the_schema_is_where_the_grammar_comes_from():
    source = grammar.read_source(REPO)
    assert source["backends"] == {"local", "s3"}
    assert source["store"] == "[a-z][a-z0-9-]*"


def test_every_copy_agrees_today():
    assert problems_in(REPO) == []


def test_nothing_a_session_reads_first_points_at_an_object():
    assert grammar.placements(REPO) == []


# ---------------------------------------------------------------------------
# drift, one copy at a time
# ---------------------------------------------------------------------------

def test_a_fake_repo_starts_green(tmp_path):
    assert problems_in(fake_repo(tmp_path)) == []


def test_an_engine_that_implements_a_backend_the_schema_does_not_name(tmp_path):
    repo = fake_repo(tmp_path)
    edit(repo, "skills/object-store/objstore/refs.py",
         'BACKENDS = ("local", "s3")', 'BACKENDS = ("local", "s3", "ftp")')
    found = problems_in(repo)
    assert any("refs.py" in p and "ftp" in p for p in found), found


def test_an_engine_that_lost_a_backend(tmp_path):
    repo = fake_repo(tmp_path)
    edit(repo, "skills/object-store/objstore/refs.py",
         'BACKENDS = ("local", "s3")', 'BACKENDS = ("local",)')
    found = problems_in(repo)
    assert any("refs.py" in p and "s3" in p for p in found), found


def test_a_template_that_advertises_a_backend_nobody_implements(tmp_path):
    repo = fake_repo(tmp_path)
    edit(repo, "infra/object-stores/_template.yaml", "# local | s3\n", "# local | s3 | gcs\n")
    found = problems_in(repo)
    assert any("_template.yaml" in p and "gcs" in p for p in found), found


def test_a_store_pattern_that_drifted_in_the_engine(tmp_path):
    repo = fake_repo(tmp_path)
    edit(repo, "skills/object-store/objstore/refs.py",
         'STORE_PATTERN = "[a-z][a-z0-9-]*"', 'STORE_PATTERN = "[a-z0-9-]+"')
    found = problems_in(repo)
    assert any("refs.py" in p and "store" in p for p in found), found


def test_a_reference_pattern_that_disagrees_with_the_name_pattern(tmp_path):
    repo = fake_repo(tmp_path)
    edit(repo, "infra/object-stores/_schema.yaml",
         "pattern: '^object://[a-z][a-z0-9-]*/", "pattern: '^object://[a-z0-9-]+/")
    found = problems_in(repo)
    assert any("_schema.yaml" in p and "reference" in p for p in found), found


def test_a_parser_that_drifted_is_caught_by_what_it_answers(tmp_path):
    """The first version compared constants only. The parser used a regular
    expression of its own, and a change to it passed."""
    repo = fake_repo(tmp_path)
    edit(repo, "skills/object-store/objstore/refs.py",
         '_prefix = "^" + SCHEME + "://"', '_prefix = "^[a-z0-9]+://"')
    found = problems_in(repo)
    assert any("'s3://b/k' as valid" in p for p in found), found


def test_a_schema_that_accepts_a_key_the_resolver_refuses(tmp_path):
    """The state of the first commit: the schema said \\S+, the parser refused `..`."""
    repo = fake_repo(tmp_path)
    edit(repo, "infra/object-stores/_schema.yaml",
         "pattern: '^object://[a-z][a-z0-9-]*/(?!", "pattern: '^object://[a-z][a-z0-9-]*/(?:")
    found = problems_in(repo)
    assert any("'object://r/../x'" in p and "schema's reference pattern says valid" in p for p in found), found


def test_an_address_pattern_that_accepts_anything(tmp_path):
    repo = fake_repo(tmp_path)
    edit(repo, "infra/object-stores/_schema.yaml",
         'pattern: "^(\\\\*|[a-z][a-z0-9-]*\\\\*?)$"', 'pattern: "^(\\\\*|[a-z][a-z0-9-]*\\\\*?|.*)$"')
    found = problems_in(repo)
    assert any("addresses pattern" in p for p in found), found


def test_an_engine_with_another_scheme(tmp_path):
    repo = fake_repo(tmp_path)
    edit(repo, "skills/object-store/objstore/refs.py", 'SCHEME = "object"', 'SCHEME = "obj"')
    found = problems_in(repo)
    assert any("refs.py" in p and "scheme" in p for p in found), found


def test_a_missing_copy_is_a_finding(tmp_path):
    repo = fake_repo(tmp_path)
    (repo / "skills/object-store/objstore/refs.py").unlink()
    found = problems_in(repo)
    assert any("refs.py" in p and "missing" in p for p in found), found


# ---------------------------------------------------------------------------
# placement: what a session reads before its first answer
# ---------------------------------------------------------------------------

def test_a_concrete_reference_in_an_always_on_file_is_found():
    found = grammar.references_in({"AGENTS.md": "see object://recordings/2026-09/a.m4a for it",
                                   "GEMINI.md": "nothing here"})
    assert len(found) == 1 and "AGENTS.md" in found[0] and "object://recordings/" in found[0]


def test_a_command_output_is_not_a_placement():
    """A work log row that says where a recording went is the entry tracking its
    reference, which the ADR asks for, not content a session needs to start."""
    parts = {"cmd:python3 scripts/worklog.py --recent 3": "put object://recordings/2026-09/a.m4a",
             "AGENTS.md": "nothing here"}
    assert grammar.references_in(grammar.always_on_files(parts)) == []


def test_a_placeholder_is_not_a_reference():
    assert grammar.references_in({"listing:skills": "resolves object://<store>/<key> to a path",
                                  "AGENTS.md": 'trigger "object://" and object:// alone'}) == []


def test_the_always_on_needle_targets_agents_md():
    """A needle that writes a CLAUDE.md would flip the entry file of the copy."""
    needle = next(n for n in grammar.NEEDLES if n.name == "an always-on file points at an object")
    assert needle.path == "AGENTS.md"
    assert not any(n.path == "CLAUDE.md" for n in grammar.NEEDLES)
