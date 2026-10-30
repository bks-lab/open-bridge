#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/data-model.py.

CONTRACT, this file is the authoritative spec for that surface.

    Every config family the tree has is described EXACTLY ONCE: in
    docs/data-model.yaml when CORE ships it, in work/data-model.yaml when only
    the instance has it. A row names a family that exists. The table in
    docs/data-model.md, the ring in docs/index.html and the whole of
    docs/families.md are generated from the yaml and are drift the moment they
    differ from it. Every CORE wrapper family carries a `route:`, the line
    docs/families.md shows every session. AGENTS.md is a kernel: it imports
    docs/families.md, declares its `## ` sections in the yaml's `kernel:` block,
    carries no family table and stays under Codex's 32 KiB read.

WHY. The layout was documented in four places and drawn in two, and the
drawing on the landing page went on saying "the agent reads every ring at
session start" for weeks after the context index made that untrue. Nothing
failed, because nothing compared the picture with anything.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "data-model.py"


def _load():
    spec = importlib.util.spec_from_file_location("data_model", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dm = _load()

ROW = {"object": "one thing", "island": "user", "lives": "user-branch",
       "references": [], "writer": "a person", "read": "named",
       "route": "when x comes up"}
HEAD = """stores:
  user-branch: {short: "user branch"}
reads:
  named: {short: "by name"}
  start: {short: "at start"}
families:
"""


def _row(path: str, drop: tuple = (), **over) -> str:
    fields = dict(ROW, path=path, **over)
    for key in drop:
        fields.pop(key, None)
    lines = [f"  - path: {fields.pop('path')}"]
    for key, value in fields.items():
        lines.append(f"    {key}: {value!r}" if not isinstance(value, list)
                     else f"    {key}: {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def _tree(tmp: Path, families: list[str], core_rows: list[str], local_rows: list[str] | None = None) -> Path:
    for fam in families:
        (tmp / fam).mkdir(parents=True, exist_ok=True)
        if fam.split("/")[0] in ("identity", "infra", "workflow"):
            (tmp / fam / "_template.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (tmp / "docs").mkdir(exist_ok=True)
    # docs/ holds the model, so the tree always has that top-level family.
    rows = "".join(core_rows) + _row("docs/", drop=("route",))
    (tmp / "docs" / "data-model.yaml").write_text(HEAD + rows, encoding="utf-8")
    if local_rows is not None:
        (tmp / "work").mkdir(exist_ok=True)
        (tmp / "work" / "data-model.yaml").write_text("families:\n" + "".join(local_rows), encoding="utf-8")
    return tmp


def _problems(root: Path) -> list[str]:
    return dm.check_rows(dm.load_model(root), dm.tree_families(root))


def test_every_family_described_once_is_clean(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "work"],
                 [_row("identity/personas/"), _row("work/")])
    assert _problems(root) == []


def test_a_family_without_a_row_is_named(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "infra/remotes", "work"],
                 [_row("identity/personas/"), _row("work/")])
    found = _problems(root)
    assert any("infra/remotes/" in p and "no row" in p for p in found), found


def test_a_second_row_for_one_family_is_named(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "work"],
                 [_row("identity/personas/"), _row("identity/personas"), _row("work/")])
    assert any("described twice" in p for p in _problems(root))


def test_a_row_for_a_folder_the_tree_lacks_is_named(tmp_path):
    root = _tree(tmp_path, ["work"], [_row("work/"), _row("identity/gone/")])
    assert any("identity/gone/" in p and "no such family" in p for p in _problems(root))


def test_an_unknown_read_value_and_store_are_named(tmp_path):
    root = _tree(tmp_path, ["work"], [_row("work/", read="sometimes", lives="nowhere")])
    found = " ".join(_problems(root))
    assert "sometimes" in found and "nowhere" in found


def test_an_instance_family_is_described_in_work_and_never_reaches_the_doc(tmp_path):
    """The case that would turn every fork red if the model were CORE only."""
    root = _tree(tmp_path, ["workflow/meetings", "work"], [_row("work/")],
                 local_rows=[_row("workflow/meetings/")])
    model = dm.load_model(root)
    assert dm.check_rows(model, dm.tree_families(root)) == []
    assert "workflow/meetings" not in dm.render_table(model), \
        "an instance's own row leaked into the CORE table"


def test_the_instance_file_cannot_hide_a_core_row_twice(tmp_path):
    root = _tree(tmp_path, ["work"], [_row("work/")], local_rows=[_row("work/")])
    assert any("described twice" in p for p in _problems(root))


def test_the_repository_itself_is_in_sync():
    done = subprocess.run([sys.executable, str(CLI)], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_every_needle_bites():
    done = subprocess.run([sys.executable, str(CLI), "--mutate"], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_an_instance_file_in_the_core_repo_is_a_finding(tmp_path):
    """A CORE family described only in work/ would pass once-each and vanish from
    both renderings. A checkout without bridge-config.yaml is the CORE repo."""
    root = _tree(tmp_path, ["identity/personas", "work"], [_row("work/")],
                 local_rows=[_row("identity/personas/")])
    assert any("without bridge-config.yaml" in p for p in dm.check_instance_file(root))
    (root / "bridge-config.yaml").write_text("identity: {}\n", encoding="utf-8")
    assert dm.check_instance_file(root) == [], "an instance may describe its own families"


# ------------------------------------------------------------- route rule --


def test_a_core_wrapper_row_without_route_is_a_finding(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "work"],
                 [_row("identity/personas/", drop=("route",)), _row("work/")])
    found = _problems(root)
    assert any("identity/personas/" in p and "route" in p for p in found), found


def test_a_top_level_row_without_route_is_not(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "work"],
                 [_row("identity/personas/"), _row("work/", drop=("route",))])
    assert _problems(root) == []


def test_an_instance_row_without_route_is_not(tmp_path):
    """work/data-model.yaml never renders into a CORE file, so no fork goes red on merge."""
    root = _tree(tmp_path, ["workflow/meetings", "work"], [_row("work/")],
                 local_rows=[_row("workflow/meetings/", drop=("route",))])
    assert _problems(root) == []


# ------------------------------------------------------------ skill, guide --


def _links(root: Path) -> list[str]:
    return dm.check_links(root, dm.load_model(root))


def test_a_guide_that_does_not_exist_is_a_finding(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "work"],
                 [_row("identity/personas/", guide=["docs/personas.md", "docs/nope.md"]), _row("work/")])
    (root / "docs" / "personas.md").write_text("# p\n", encoding="utf-8")
    found = _links(root)
    assert len(found) == 1 and "docs/nope.md" in found[0], found


def test_a_skill_without_skill_md_is_a_finding(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "infra/remotes", "work"],
                 [_row("identity/personas/", skill="ghost"), _row("infra/remotes/", skill="remote"),
                  _row("work/")])
    (root / "skills" / "remote").mkdir(parents=True)
    (root / "skills" / "remote" / "SKILL.md").write_text("---\nname: remote\n---\n", encoding="utf-8")
    found = _links(root)
    assert len(found) == 1 and "ghost" in found[0] and "skills/ghost/SKILL.md" in found[0], found


def test_in_a_fork_a_missing_guide_only_warns(tmp_path):
    root = _tree(tmp_path, ["identity/personas", "work"],
                 [_row("identity/personas/", guide=["docs/nope.md"]), _row("work/")])
    assert any("docs/nope.md" in p for p in dm.gated(root, dm.load_model(root))[0])
    (root / "bridge-config.yaml").write_text("identity: {}\n", encoding="utf-8")
    problems, warnings = dm.gated(root, dm.load_model(root))
    assert problems == [] and any("docs/nope.md" in w for w in warnings)


# --------------------------------------------------------------- families --


def _families_tree(tmp_path: Path) -> Path:
    return _tree(tmp_path, ["identity/personas", "infra/remotes", "workflow/meetings", "skills", "work"],
                 [_row("infra/remotes/", skill="remote", guide=["docs/remotes.md", "docs/always-on-machine.md"]),
                  _row("identity/personas/", route="an identity the user HOLDS | a test pipe"),
                  _row("skills/", drop=("route",)), _row("work/", drop=("route",))],
                 local_rows=[_row("workflow/meetings/")])


def test_render_families_one_row_per_core_wrapper_family_and_none_for_instance_rows(tmp_path):
    text = dm.render_families(dm.load_model(_families_tree(tmp_path)))
    rows = [ln for ln in text.splitlines() if ln.startswith("| `")]
    assert [r.split("`")[1] for r in rows] == ["identity/personas/", "infra/remotes/"], rows
    assert "workflow/meetings" not in text, "an instance's own row leaked into the CORE index"
    assert "\\|" in rows[0], "a pipe in a route must not split the cell"
    assert "/remote" in rows[1] and "`docs/remotes.md` · `docs/always-on-machine.md`" in rows[1]
    lifecycle = [ln for ln in text.splitlines() if ln.startswith("Own lifecycle: ")]
    assert lifecycle == ["Own lifecycle: `skills/` `work/` `docs/`"], lifecycle
    assert "identity/agent/INSTANCE.md" in text
    assert not text.endswith("\n")


def test_render_families_uses_backticked_paths_and_no_markdown_links(tmp_path):
    text = dm.render_families(dm.load_model(_families_tree(tmp_path)))
    assert "](" not in text
    assert text.splitlines()[0].startswith("<!-- generated by scripts/data-model.py")


def test_render_families_never_looks_at_the_tree(tmp_path):
    """A fork must never be asked to --write a CORE file, so nothing local may change it."""
    root = _families_tree(tmp_path)
    before = dm.render_families(dm.load_model(root))
    (root / "mods").mkdir()
    (root / "docs" / "extra.md").write_text("x\n", encoding="utf-8")
    assert dm.render_families(dm.load_model(root)) == before


def _family_findings(root: Path) -> list[str]:
    return [p for p in dm.check_rendered(root, dm.load_model(root)) if dm.FAMILIES in p]


def test_a_missing_families_md_is_drift(tmp_path):
    root = _families_tree(tmp_path)
    assert any("missing" in p for p in _family_findings(root))


def test_a_hand_edit_to_families_md_is_drift(tmp_path):
    root = _families_tree(tmp_path)
    good = dm.render_families(dm.load_model(root)) + "\n"
    (root / dm.FAMILIES).write_text(good, encoding="utf-8")
    assert _family_findings(root) == []
    (root / dm.FAMILIES).write_text(good.replace("Read it when", "Open it when"), encoding="utf-8")
    assert any("differs" in p for p in _family_findings(root))


FULL_HEAD = HEAD.replace("families:\n", """always_on:
  - {label: "AGENTS.md", what: "the manual"}
ring:
  centre: {en: c, de: c}
  legend_start: {en: s, de: s}
  legend_named: {en: n, de: n}
  walked: {en: w, de: w}
  outside: {en: o, de: o}
  aria: "a ring"
  foot: {en: f, de: f}
kernel:
  sections: ["Loaded with this file", "Rules"]
  max_table_rows: 4
  max_bytes: 2000
families:
""")

GOOD_AGENTS = """# Manual

## Loaded with this file

@identity/agent/IDENTITY.md
@docs/families.md

## Rules

| a | b |
|---|---|
| c | d |
"""


def _full_tree(tmp_path: Path) -> Path:
    root = _families_tree(tmp_path)
    core = (root / "docs" / "data-model.yaml").read_text(encoding="utf-8")
    (root / "docs" / "data-model.yaml").write_text(core.replace(HEAD, FULL_HEAD, 1), encoding="utf-8")
    (root / "docs" / "remotes.md").write_text("# r\n", encoding="utf-8")
    (root / "docs" / "always-on-machine.md").write_text("# a\n", encoding="utf-8")
    (root / "skills" / "remote").mkdir(parents=True)
    (root / "skills" / "remote" / "SKILL.md").write_text("---\nname: remote\n---\n", encoding="utf-8")
    (root / "docs" / "data-model.md").write_text(f"# m\n\n{dm.TABLE_START}\n{dm.TABLE_END}\n", encoding="utf-8")
    (root / "docs" / "index.html").write_text(f"<p>\n{dm.RING_START}\n{dm.RING_END}\n</p>\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(GOOD_AGENTS, encoding="utf-8")
    (root / "work" / "data-model.yaml").unlink()     # a core checkout has no instance file
    shutil.rmtree(root / "workflow" / "meetings")    # ... and so no family only it describes
    return root


def test_write_creates_families_md_and_a_second_write_changes_nothing(tmp_path):
    root = _full_tree(tmp_path)
    assert not (root / dm.FAMILIES).exists()
    assert dm.FAMILIES in dm.write(root)
    assert (root / dm.FAMILIES).read_text(encoding="utf-8") == dm.render_families(dm.load_model(root)) + "\n"
    assert dm.write(root) == []
    assert dm.check(root) == []


def test_the_cli_writes_and_then_checks_a_fixture_clean(tmp_path):
    root = _full_tree(tmp_path)
    wrote = subprocess.run([sys.executable, str(CLI), "--root", str(root), "--write"],
                           capture_output=True, text=True)
    assert wrote.returncode == 0, wrote.stderr
    done = subprocess.run([sys.executable, str(CLI), "--root", str(root)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "docs/families.md" in done.stdout and "kernel" in done.stdout


def test_the_cli_in_a_fork_warns_on_the_kernel_and_passes(tmp_path):
    root = _full_tree(tmp_path)
    dm.write(root)
    (root / "bridge-config.yaml").write_text("identity: {}\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(GOOD_AGENTS + "\n## My own section\n", encoding="utf-8")
    done = subprocess.run([sys.executable, str(CLI), "--root", str(root)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "My own section" in done.stderr and "migrate-entry-file.py --file AGENTS.md" in done.stderr


# ----------------------------------------------------------------- kernel --


KERNEL = {"kernel": {"sections": ["Loaded with this file", "Rules"], "max_table_rows": 4, "max_bytes": 2000}}


def _kernel(tmp_path: Path, text: str, model: dict = KERNEL) -> list[str]:
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")
    return dm.check_kernel(tmp_path, model)


def test_a_kernel_agents_md_is_clean(tmp_path):
    assert _kernel(tmp_path, GOOD_AGENTS) == []


def test_no_agents_md_is_quiet(tmp_path):
    assert dm.check_kernel(tmp_path, KERNEL) == []


def test_agents_md_without_the_families_import_is_a_finding(tmp_path):
    found = _kernel(tmp_path, GOOD_AGENTS.replace("@docs/families.md\n", ""))
    assert any("@docs/families.md" in p for p in found), found
    indented = _kernel(tmp_path, GOOD_AGENTS.replace("@docs/families.md", "  @docs/families.md"))
    assert any("@docs/families.md" in p for p in indented), "the import must start at column 0"


def test_agents_md_with_a_family_table_row_is_a_finding(tmp_path):
    for path in ("identity/personas/", "infra/remotes/", "workflow/projects/"):
        found = _kernel(tmp_path, GOOD_AGENTS.replace("| c | d |", f"| `{path}` | d |"))
        assert any(path in p and "docs/families.md" in p for p in found), found


def test_the_families_import_inside_a_fence_is_a_finding(tmp_path):
    """Inside a code fence the line is an example, not an import: no session loads it."""
    fenced = GOOD_AGENTS.replace("@docs/families.md\n", "```\n@docs/families.md\n```\n")
    found = _kernel(tmp_path, fenced)
    assert any("@docs/families.md" in p for p in found), found


def test_a_family_row_without_backticks_or_space_is_a_finding(tmp_path):
    for row in ("| identity/personas/ | x |", "|`infra/remotes/`| y |", "|workflow/projects/|z|"):
        found = _kernel(tmp_path, GOOD_AGENTS.replace("| c | d |", row))
        assert any("docs/families.md" in p and "family table row" in p for p in found), (row, found)


def test_fences_follow_the_meter_rules(tmp_path):
    """An indented fence opens one, and a ~~~ inside ``` does not close it."""
    indented = GOOD_AGENTS + "\n  ```md\n## Example\n  ```\n"
    assert _kernel(tmp_path, indented) == []
    nested = GOOD_AGENTS + "\n```md\n~~~\n## Example\n~~~\n```\n"
    assert _kernel(tmp_path, nested) == []


def test_an_undeclared_section_is_a_finding(tmp_path):
    found = _kernel(tmp_path, GOOD_AGENTS + "\n## Personas\n\ntext\n")
    assert any("Personas" in p and "kernel" in p for p in found), found


def test_a_heading_inside_a_code_fence_is_not_a_section(tmp_path):
    assert _kernel(tmp_path, GOOD_AGENTS + "\n```md\n## Example\n| x |\n| y |\n```\n") == []


def test_too_many_table_rows_is_a_finding(tmp_path):
    assert _kernel(tmp_path, GOOD_AGENTS + "| e | f |\n") == [], "at the cap is fine"
    found = _kernel(tmp_path, GOOD_AGENTS + "| e | f |\n| g | h |\n")
    assert any("table" in p and "5" in p for p in found), found


def test_agents_md_over_the_byte_ceiling_is_a_finding(tmp_path):
    found = _kernel(tmp_path, GOOD_AGENTS + "x" * 2000 + "\n")
    assert any("bytes" in p and "2000" in p for p in found), found


def test_a_model_without_a_kernel_block_is_a_finding(tmp_path):
    assert any("kernel" in p for p in _kernel(tmp_path, GOOD_AGENTS, {}))


def test_in_a_fork_the_kernel_guard_only_warns(tmp_path):
    root = _full_tree(tmp_path)
    (root / "AGENTS.md").write_text(GOOD_AGENTS.replace("@docs/families.md\n", ""), encoding="utf-8")
    assert dm.gated(root, dm.load_model(root))[0], "a core checkout fails"
    (root / "bridge-config.yaml").write_text("identity: {}\n", encoding="utf-8")
    problems, warnings = dm.gated(root, dm.load_model(root))
    assert problems == [] and any("migrate-entry-file.py --file AGENTS.md" in w for w in warnings)


def test_the_live_model_routes_every_core_wrapper_family():
    model = dm.load_model(REPO_ROOT)
    rows = [r for r in model["families"] if r["origin"] == dm.CORE_MODEL
            and r["path"].split("/")[0] in dm.WRAPPER_GROUPS]
    assert rows and all(r.get("route") for r in rows)
    assert model["kernel"]["max_bytes"] == 32768
