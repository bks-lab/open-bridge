#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/check-edges.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. The card layer says WHAT exists. The reachability contract
says a session can still find it. Neither says anything about the third thing
a Bridge is made of: the references BETWEEN entries. A customer names its
mandant, a mandant names a persona, an account names the task that provisioned
it, a workload names the machine it runs on. Those are declared, in ordinary
fields, and nothing has ever checked that they resolve.

Measured on a live instance before this existed: 126 repo-internal references
across 44 config files, 45 of them pointing at nothing. A third of the graph.

    THE INTERESTING HALF is not that they rot. It is HOW.

    Four of the dead ones, sampled: every single target still existed. The
    task had simply moved KIND — `work/tasks/<slug>` to `work/streams/<slug>`
    or to `work/done/YYYY-MM/<slug>` — which is the documented lifecycle,
    performed with `mv`, and nothing pulls the references along. The nodes are
    alive and the edges point at where they used to be.

    So a plain "does the path exist" check would report 45 broken links and
    tell you nothing about what to do. This one distinguishes:

        ok        resolves
        moved     the target lives, in another bucket — the fix is mechanical
        external  the first segment is not a directory of this repo at all,
                  so it belongs to a neighbour repo and is not ours to check
        dead      nothing anywhere

    TEMPLATES ARE NOT EDGES. `ecosystem.example.yaml` describes the tree a
    future instance will have; `_template.yaml` describes a file nobody has
    written yet. Checking their paths reports three findings in open-bridge
    and all three are correct-as-written.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


edges = _load("check_edges", "scripts/check-edges.py")


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


# ------------------------------------------------------------ extraction --


def test_a_repo_relative_path_in_a_value_is_an_edge(tmp_path):
    _tree(tmp_path, {
        "identity/mandants/a.yaml": "persona_ref: identity/personas/p.yaml\n",
        "identity/personas/p.yaml": "name: p\n",
    })
    found = edges.iter_edges(tmp_path)

    assert ("identity/mandants/a.yaml", "persona_ref",
            "identity/personas/p.yaml") in found


def test_an_edge_is_found_at_any_depth(tmp_path):
    _tree(tmp_path, {
        "workflow/projects/a.yaml": (
            "bridge_refs:\n  mandant: identity/mandants/m.yaml\n"
        ),
        "identity/mandants/m.yaml": "x: 1\n",
    })
    keys = [k for _, k, _ in edges.iter_edges(tmp_path)]

    assert "bridge_refs.mandant" in keys


def test_an_edge_inside_a_list_is_found(tmp_path):
    _tree(tmp_path, {
        "infra/channels/c.yaml": (
            "related:\n  - infra/remotes/r.yaml\n  - infra/remotes/s.yaml\n"
        ),
        "infra/remotes/r.yaml": "x: 1\n",
        "infra/remotes/s.yaml": "x: 1\n",
    })
    assert len(edges.iter_edges(tmp_path)) == 2


def test_ordinary_prose_is_not_an_edge(tmp_path):
    _tree(tmp_path, {
        "identity/mandants/a.yaml": (
            'note: "see the mandant docs"\n'
            'display_name: "Some Customer GmbH"\n'
            'url: "https://example.org/a.yaml"\n'
        ),
    })
    assert edges.iter_edges(tmp_path) == []


def test_a_template_is_not_scanned(tmp_path):
    """A template describes a file nobody has written yet."""
    _tree(tmp_path, {
        "identity/mandants/_template.yaml": "persona_ref: identity/personas/x.yaml\n",
    })
    assert edges.iter_edges(tmp_path) == []


def test_an_example_file_is_not_scanned(tmp_path):
    _tree(tmp_path, {"ecosystem.example.yaml": "files:\n  current: work/log.md\n"})
    assert edges.iter_edges(tmp_path) == []


def test_a_lock_file_is_not_scanned(tmp_path):
    """Generated state, with a src/dest for every materialized file."""
    _tree(tmp_path, {"overlays.lock.yaml": "o:\n  - src: a/b.yaml\n    dest: c/d.yaml\n"})
    assert edges.iter_edges(tmp_path) == []


# -------------------------------------------------------- classification --


def test_a_resolving_edge_is_ok(tmp_path):
    _tree(tmp_path, {"identity/personas/p.yaml": "x: 1\n"})
    assert edges.classify(tmp_path, "identity/personas/p.yaml") == ("ok", None)


def test_a_path_into_a_directory_this_repo_lacks_is_external(tmp_path):
    """A neighbour repo. Not ours to check, and not a finding.

    `wiki/your-org/standards/...` on a live instance points into a sibling
    checkout. Reporting it as broken would be reporting on someone else's tree,
    and after the third false alarm nobody reads the output.
    """
    _tree(tmp_path, {"identity/personas/p.yaml": "x: 1\n"})
    assert edges.classify(tmp_path, "wiki/standards/x.md")[0] == "external"


def test_a_missing_target_under_an_existing_family_is_dead(tmp_path):
    _tree(tmp_path, {"identity/personas/p.yaml": "x: 1\n"})
    assert edges.classify(tmp_path, "identity/personas/gone.yaml")[0] == "dead"


def test_a_task_that_moved_to_done_is_moved_not_dead(tmp_path):
    """THE case this exists for. The node lives; the edge is stale."""
    _tree(tmp_path, {"work/done/2026-05/migration/STATUS.md": "x\n"})
    state, target = edges.classify(tmp_path, "work/tasks/migration/STATUS.md")

    assert state == "moved"
    assert target == "work/done/2026-05/migration/STATUS.md"


def test_a_task_that_became_a_stream_is_moved(tmp_path):
    _tree(tmp_path, {"work/streams/example-stream/STATUS.md": "x\n"})
    state, target = edges.classify(tmp_path, "work/tasks/example-stream/STATUS.md")

    assert state == "moved"
    assert target == "work/streams/example-stream/STATUS.md"


def test_a_deep_file_inside_a_moved_task_is_found(tmp_path):
    _tree(tmp_path, {"work/done/2026-07/x/deliverables/note.md": "x\n"})
    state, target = edges.classify(
        tmp_path, "work/tasks/x/deliverables/note.md"
    )

    assert state == "moved"
    assert target == "work/done/2026-07/x/deliverables/note.md"


def test_a_task_that_exists_nowhere_is_dead_not_moved(tmp_path):
    _tree(tmp_path, {"work/tasks/other/STATUS.md": "x\n"})
    assert edges.classify(tmp_path, "work/tasks/ghost/STATUS.md")[0] == "dead"


# ---------------------------------------------------------------- checks --


def test_check_reports_dead_and_moved_and_stays_quiet_on_ok(tmp_path):
    _tree(tmp_path, {
        "identity/mandants/a.yaml": (
            "persona_ref: identity/personas/p.yaml\n"
            "task_ref: work/tasks/moved/STATUS.md\n"
            "gone_ref: identity/personas/nope.yaml\n"
            "away_ref: wiki/x/y.md\n"
        ),
        "identity/personas/p.yaml": "x: 1\n",
        "work/streams/moved/STATUS.md": "x\n",
    })
    findings = edges.check(tmp_path)

    assert any("nope.yaml" in f and "dead" in f for f in findings)
    assert any("work/streams/moved/STATUS.md" in f for f in findings)
    assert not any("personas/p.yaml" in f for f in findings)
    assert not any("wiki/" in f for f in findings)


def test_stats_counts_by_class(tmp_path):
    _tree(tmp_path, {
        "identity/mandants/a.yaml": (
            "a: identity/personas/p.yaml\n"
            "b: identity/personas/nope.yaml\n"
            "c: wiki/x.md\n"
        ),
        "identity/personas/p.yaml": "x: 1\n",
    })
    stats = edges.stats(tmp_path)

    assert stats["ok"] == 1 and stats["dead"] == 1 and stats["external"] == 1


# ----------------------------------------------------------- neighbours --


def test_neighbours_lists_edges_out_of_a_node(tmp_path):
    _tree(tmp_path, {
        "identity/mandants/a.yaml": "persona_ref: identity/personas/p.yaml\n",
        "identity/personas/p.yaml": "x: 1\n",
    })
    out, _ = edges.neighbours(tmp_path, "identity/mandants/a.yaml")

    assert ("persona_ref", "identity/personas/p.yaml", "ok") in out


def test_neighbours_lists_edges_into_a_node(tmp_path):
    """The half a grep does not give you cheaply: who points HERE."""
    _tree(tmp_path, {
        "identity/mandants/a.yaml": "persona_ref: identity/personas/p.yaml\n",
        "workflow/projects/x.yaml": "owner: identity/personas/p.yaml\n",
        "identity/personas/p.yaml": "x: 1\n",
    })
    _, incoming = edges.neighbours(tmp_path, "identity/personas/p.yaml")
    sources = sorted(src for src, _ in incoming)

    assert sources == ["identity/mandants/a.yaml", "workflow/projects/x.yaml"]


# ----------------------------------------------------------------- --fix --


def test_fix_rewrites_a_moved_reference_and_keeps_the_comments(tmp_path):
    """Text substitution, not a YAML round trip.

    Re-serializing would drop every comment in the file, which is a far larger
    change than the one being made and would hide it in the diff.
    """
    _tree(tmp_path, {
        "identity/mandants/a.yaml": (
            "# why this mandant matters\n"
            "task_ref: work/tasks/moved/STATUS.md   # the launch plan\n"
        ),
        "work/done/2026-05/moved/STATUS.md": "x\n",
    })
    changed, _ = edges.fix_moved(tmp_path)
    text = (tmp_path / "identity/mandants/a.yaml").read_text(encoding="utf-8")

    assert changed == 1
    assert "work/done/2026-05/moved/STATUS.md" in text
    assert "# why this mandant matters" in text
    assert "# the launch plan" in text


def test_fix_leaves_dead_references_alone(tmp_path):
    """A dead edge is a decision, not a typo. Only `moved` is mechanical."""
    _tree(tmp_path, {"identity/mandants/a.yaml": "x: identity/personas/nope.yaml\n"})
    assert edges.fix_moved(tmp_path)[0] == 0


def test_fix_is_idempotent(tmp_path):
    _tree(tmp_path, {
        "identity/mandants/a.yaml": "task_ref: work/tasks/moved/STATUS.md\n",
        "work/streams/moved/STATUS.md": "x\n",
    })
    assert edges.fix_moved(tmp_path)[0] == 1
    assert edges.fix_moved(tmp_path)[0] == 0


# --------------------------------------------------------------- the CLI --


def test_main_runs_on_this_repo_and_agrees_with_itself():
    """A SMOKE test on real content, not a cleanliness gate.

    It used to assert the exit code was 0, which is a GATE and not a contract:
    it says this particular tree has no dead reference. In open-bridge that is
    trivially true, because CORE ships no instance YAML and therefore declares
    zero edges. In a downstream instance it is false the moment somebody
    references a document they have not written yet — and then the whole CORE
    contract suite goes red for a content decision that has nothing to do with
    whether this code works. Measured on one: one legitimate finding, 913 other
    tests passing, suite red.

    The gate exists and belongs where it already is: `validate.yml` runs
    `python3 scripts/check-edges.py` as its own step, so a real finding still
    fails CI, and it fails it with a name that says what broke.

    What survives here is what a contract test can honestly assert about a live
    tree: the CLI runs, and its exit code AGREES with its findings. That still
    catches the crash class this file was written after (a parser that walked
    real YAML and reported 54 findings, none of them real), and it stays green
    while an instance decides what to do about a reference.
    """
    findings = edges.check(edges.HERE.parent)
    assert edges.main([]) == (1 if findings else 0)
    assert all(isinstance(f, str) and f for f in findings)


def test_main_returns_one_on_a_finding(tmp_path):
    _tree(tmp_path, {"identity/mandants/a.yaml": "x: identity/personas/nope.yaml\n",
                     "identity/personas/p.yaml": "y: 1\n"})
    assert edges.main(["--repo-root", str(tmp_path)]) == 1


def test_main_stats_succeeds(tmp_path, capsys):
    _tree(tmp_path, {"identity/personas/p.yaml": "x: 1\n"})
    assert edges.main(["--repo-root", str(tmp_path), "--stats"]) == 0
    assert "edge" in capsys.readouterr().out


def test_main_neighbours_prints_both_directions(tmp_path, capsys):
    _tree(tmp_path, {
        "identity/mandants/a.yaml": "persona_ref: identity/personas/p.yaml\n",
        "identity/personas/p.yaml": "x: 1\n",
    })
    assert edges.main([
        "--repo-root", str(tmp_path), "--neighbours", "identity/personas/p.yaml"
    ]) == 0
    out = capsys.readouterr().out

    assert "identity/mandants/a.yaml" in out


# ---------------------------------------------------- declared exceptions --
#
# A checker over free-form YAML cannot know that `bin/generate_voice.py` is a
# runtime path inside a deployed pipeline, or that everything under a
# `family_repo:` key lives in a different checkout. On a live instance those
# two shapes were 7 of 18 "dead" findings — and a check whose output is mostly
# unactionable is a check people stop reading.
#
# So the instance says so, once, WITH A REASON. The reason is the point: it
# turns eighteen unknowns into eighteen known things.


def test_an_exception_silences_a_matching_finding(tmp_path):
    _tree(tmp_path, {
        "infra/channels/c.yaml": "pipeline:\n  steps:\n    - script: bin/x.py\n",
        # `bin/` has to EXIST, or the path classifies as external and there is
        # nothing for the exception to excuse.
        "bin/other.py": "x = 1\n",
        "edges.yaml": (
            "exceptions:\n"
            "  - path: infra/channels/c.yaml\n"
            "    keys: [pipeline.steps]\n"
            "    reason: runtime paths inside the deployed pipeline\n"
        ),
    })
    assert edges.check(tmp_path) == []


def test_an_exception_does_not_silence_a_different_key(tmp_path):
    _tree(tmp_path, {
        "infra/channels/c.yaml": (
            "pipeline:\n  steps:\n    - script: bin/x.py\n"
            "other_ref: infra/remotes/gone.yaml\n"
        ),
        "infra/remotes/r.yaml": "x: 1\n",
        "edges.yaml": (
            "exceptions:\n"
            "  - path: infra/channels/c.yaml\n"
            "    keys: [pipeline.steps]\n"
            "    reason: runtime paths\n"
        ),
    })
    findings = edges.check(tmp_path)

    assert any("gone.yaml" in f for f in findings)
    assert not any("bin/x.py" in f for f in findings)


def test_an_exception_does_not_silence_a_different_file(tmp_path):
    _tree(tmp_path, {
        "infra/channels/c.yaml": "a: infra/remotes/gone.yaml\n",
        "infra/channels/d.yaml": "a: infra/remotes/gone.yaml\n",
        "infra/remotes/r.yaml": "x: 1\n",
        "edges.yaml": (
            "exceptions:\n"
            "  - path: infra/channels/c.yaml\n"
            "    keys: [a]\n"
            "    reason: whatever\n"
        ),
    })
    findings = edges.check(tmp_path)

    assert len(findings) == 1
    assert "infra/channels/d.yaml" in findings[0]


def test_an_exception_without_a_reason_is_itself_a_finding(tmp_path):
    """An undocumented exception is indistinguishable from forgetting.

    The whole value of declaring one is the sentence next to it; without that
    the list becomes a place where findings go to be forgotten quietly.
    """
    _tree(tmp_path, {
        "infra/channels/c.yaml": "a: infra/remotes/gone.yaml\n",
        "infra/remotes/r.yaml": "x: 1\n",
        "edges.yaml": "exceptions:\n  - path: infra/channels/c.yaml\n    keys: [a]\n",
    })
    findings = edges.check(tmp_path)

    assert any("reason" in f for f in findings), findings


def test_an_exception_for_something_that_resolves_is_a_finding(tmp_path):
    """An exception that no longer excuses anything is stale, and stale
    exceptions are how a list of them turns into a list of lies."""
    _tree(tmp_path, {
        "infra/channels/c.yaml": "a: infra/remotes/r.yaml\n",
        "infra/remotes/r.yaml": "x: 1\n",
        "edges.yaml": (
            "exceptions:\n"
            "  - path: infra/channels/c.yaml\n"
            "    keys: [a]\n"
            "    reason: no longer needed\n"
        ),
    })
    assert any("excuses nothing" in f for f in edges.check(tmp_path))


def test_no_exception_file_is_fine(tmp_path):
    _tree(tmp_path, {"identity/personas/p.yaml": "x: 1\n"})
    assert edges.check(tmp_path) == []


def test_stats_counts_declared_exceptions_separately(tmp_path):
    _tree(tmp_path, {
        "infra/channels/c.yaml": "a: bin/x.py\n",
        "bin/other.py": "x = 1\n",
        "edges.yaml": (
            "exceptions:\n"
            "  - path: infra/channels/c.yaml\n"
            "    keys: [a]\n"
            "    reason: runtime path\n"
        ),
    })
    assert edges.stats(tmp_path)["declared"] == 1


# ------------------------------------------- the external escape hatch --
#
# `classify` took `target.split("/")[0]` and asked whether that is a directory
# of this repo. Both interesting cases came out exactly backwards:
#
#   channels/telegram.yaml            a real pre-reorg path, the file now lives
#                                     at infra/channels/ -> "external", excused,
#                                     and the gate reported "all resolve"
#   /opt/other-repo/thing.yaml        a genuine neighbour checkout -> the first
#                                     segment is "" (leading slash), root/"" IS
#                                     a directory, so it fell through to "dead"
#
# The example deliberately avoids a `/Users/<name>/` shape: that is what a real
# neighbour checkout looks like on macOS, and it is also exactly what the leak
# scanner refuses — correctly, since it cannot tell a placeholder name from a
# real one. It caught this fixture on the first push.
#
# The cluster-wrapper reorg moved channels/, backups/, remotes/ under infra/ and
# calendars/, contexts/, projects/ under workflow/ — so this hid exactly the rot
# the guard was built to find, in exactly the tree that had just been reorganised.


def test_an_absolute_path_is_external(tmp_path):
    assert edges.classify(tmp_path, "/opt/other-repo/thing.yaml")[0] == "external"


def test_a_home_relative_path_is_external(tmp_path):
    assert edges.classify(tmp_path, "~/other/thing.yaml")[0] == "external"


def test_a_pre_reorg_path_is_moved_not_external(tmp_path):
    (tmp_path / "infra" / "channels").mkdir(parents=True)
    (tmp_path / "infra" / "channels" / "telegram.yaml").write_text("id: t\n", encoding="utf-8")
    state, live = edges.classify(tmp_path, "channels/telegram.yaml")
    assert state == "moved"
    assert live == "infra/channels/telegram.yaml"


def test_a_neighbour_checkout_stays_external(tmp_path):
    # First segment is not a repo directory AND nothing in the tree ends with
    # the target: someone else's layout, not ours to judge.
    assert edges.classify(tmp_path, "some-other-repo/config/thing.yaml")[0] == "external"


def test_a_resolving_path_is_still_ok(tmp_path):
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "x.yaml").write_text("a: 1\n", encoding="utf-8")
    assert edges.classify(tmp_path, "infra/x.yaml")[0] == "ok"


def test_a_missing_file_under_a_real_directory_is_still_dead(tmp_path):
    (tmp_path / "infra").mkdir()
    assert edges.classify(tmp_path, "infra/nowhere.yaml")[0] == "dead"


def test_the_tail_match_needs_the_whole_tail_not_just_the_basename(tmp_path):
    # `README.md` exists all over a Bridge. Matching on basename alone would
    # call every stale reference "moved" and point it somewhere arbitrary.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("x\n", encoding="utf-8")
    assert edges.classify(tmp_path, "somewhere-else/README.md")[0] == "external"


def test_a_hit_inside_a_cloned_workspace_is_not_a_move(tmp_path):
    # `.bridge/workspaces/<name>/` holds CLONES of other repositories. A path
    # that resolves there resolves in somebody else's tree, which is the one
    # thing this module refuses to judge. Caught on a live instance: three
    # references to `incidents/index.md` in a customer context are paths inside
    # that customer's wiki, and the tail match found the checked-out copy and
    # called them moved.
    clone = tmp_path / ".bridge" / "workspaces" / "cust" / "cust-wiki" / "incidents"
    clone.mkdir(parents=True)
    (clone / "index.md").write_text("x\n", encoding="utf-8")
    assert edges.classify(tmp_path, "incidents/index.md")[0] == "external"


# ------------------------------------------ --fix must honour exceptions --
#
# `check()` and `stats()` both call `load_exceptions()`. `fix_moved()` did not.
# So a path an instance had explicitly declared NOT to be repo-relative, with a
# written reason, was rewritten as if it were.
#
# It happened. `infra/channels/voice-news.yaml :: pipeline.steps` carried the
# reason "runtime paths of the deployed pipeline on homeserver, relative to the
# SERVICE's working directory". The tail match found the sources under
# work/done/… and `--fix` rewrote `bin/generate_voice.py` into a repo path the
# service cannot resolve. A working config, broken by its own guard.
#
# Skipped LOUDLY, never silently: a fix run that declines to touch something has
# to say so, or the next reader assumes it had nothing to decline.


def _excepted_tree(tmp_path):
    (tmp_path / "infra" / "channels").mkdir(parents=True)
    (tmp_path / "infra" / "channels" / "ch.yaml").write_text(
        "id: ch\npipeline:\n  steps:\n    - script: bin/run.py\n", encoding="utf-8"
    )
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "bin").mkdir()
    (tmp_path / "work" / "bin" / "run.py").write_text("x\n", encoding="utf-8")
    return tmp_path


def test_fix_leaves_an_excepted_edge_alone(tmp_path):
    _excepted_tree(tmp_path)
    (tmp_path / "edges.yaml").write_text(
        "exceptions:\n"
        "  - path: infra/channels/ch.yaml\n"
        "    keys: [pipeline.steps]\n"
        "    reason: runtime paths, relative to the service working directory\n",
        encoding="utf-8",
    )
    edges.fix_moved(tmp_path)
    assert "script: bin/run.py" in (tmp_path / "infra" / "channels" / "ch.yaml").read_text()


def test_fix_still_rewrites_an_unexcepted_edge(tmp_path):
    _excepted_tree(tmp_path)
    edges.fix_moved(tmp_path)
    assert "work/bin/run.py" in (tmp_path / "infra" / "channels" / "ch.yaml").read_text()


def test_fix_reports_what_it_declined_to_touch(tmp_path):
    _excepted_tree(tmp_path)
    (tmp_path / "edges.yaml").write_text(
        "exceptions:\n"
        "  - path: infra/channels/ch.yaml\n"
        "    keys: [pipeline.steps]\n"
        "    reason: runtime paths\n",
        encoding="utf-8",
    )
    changed, skipped = edges.fix_moved(tmp_path)
    assert changed == 0
    assert skipped and "pipeline.steps" in skipped[0]


# ---------------------------------------- --fix must rewrite ONE occurrence --
#
# The exception gate added earlier sits on the LOOP ITERATION. The write was
# still a whole-file `text.replace(target, live)`, so an unexcused key naming the
# same string rewrote the excepted lines too — while the tool printed "left
# alone" about a value it had just changed. Worse than silent: the log actively
# misleads whoever checks it.
#
# The same replace corrupts correct paths. `live` always ends with
# `"/" + target`, so any longer path that already resolves and happens to end in
# `target` gets the replacement spliced into its middle:
#   work/done/svc/bin/run.py  ->  work/done/svc/work/done/svc/bin/run.py
#
# The rewrite is therefore scoped to the LINE of the scalar node at that key
# path, found with `yaml.compose` — the same loader that keeps source spelling
# elsewhere in this repo.


def _multi(tmp_path):
    (tmp_path / "infra" / "channels").mkdir(parents=True)
    (tmp_path / "work" / "svc" / "bin").mkdir(parents=True)
    (tmp_path / "work" / "svc" / "bin" / "run.py").write_text("x\n", encoding="utf-8")
    (tmp_path / "infra" / "channels" / "d.yaml").write_text(
        "pipeline:\n"
        "  steps:\n"
        "    - script: bin/run.py\n"
        "docs:\n"
        "  helper: bin/run.py\n",
        encoding="utf-8",
    )
    (tmp_path / "edges.yaml").write_text(
        "exceptions:\n"
        "  - path: infra/channels/d.yaml\n"
        "    keys: [pipeline.steps]\n"
        "    reason: runtime paths, relative to the service working directory\n",
        encoding="utf-8",
    )
    return tmp_path / "infra" / "channels" / "d.yaml"


def test_an_unexcused_key_does_not_drag_the_excepted_line_with_it(tmp_path):
    target = _multi(tmp_path)
    changed, skipped = edges.fix_moved(tmp_path)
    body = target.read_text(encoding="utf-8")
    assert "    - script: bin/run.py" in body, "the excepted line was rewritten anyway"
    assert "  helper: work/svc/bin/run.py" in body, "the unexcused line was not fixed"
    assert changed == 1 and skipped


def test_a_longer_resolving_path_is_not_spliced(tmp_path):
    # Under infra/<family>/, because SCAN_GLOBS is `infra/*/*.yaml`. At
    # infra/d.yaml the file is never scanned and every assertion below passes
    # for the wrong reason — which is how the first draft of this test read.
    (tmp_path / "infra" / "channels").mkdir(parents=True)
    (tmp_path / "work" / "svc" / "bin").mkdir(parents=True)
    (tmp_path / "work" / "svc" / "bin" / "run.py").write_text("x\n", encoding="utf-8")
    f = tmp_path / "infra" / "channels" / "d.yaml"
    f.write_text("good: work/svc/bin/run.py\nbad: bin/run.py\n", encoding="utf-8")
    assert edges.iter_edges(tmp_path), "fixture is not being scanned at all"
    edges.fix_moved(tmp_path)
    body = f.read_text(encoding="utf-8")
    assert "good: work/svc/bin/run.py" in body, "a correct path was corrupted"
    assert "bad: work/svc/bin/run.py" in body


def test_the_count_matches_the_lines_actually_changed(tmp_path):
    target = _multi(tmp_path)
    before = target.read_text(encoding="utf-8").splitlines()
    changed, _ = edges.fix_moved(tmp_path)
    after = target.read_text(encoding="utf-8").splitlines()
    assert changed == sum(1 for a, b in zip(before, after) if a != b)


def test_fix_stays_idempotent_with_an_exception_present(tmp_path):
    _multi(tmp_path)
    edges.fix_moved(tmp_path)
    changed, _ = edges.fix_moved(tmp_path)
    assert changed == 0


# ------------------------------------------------------- markdown links --
#
# The YAML fields are a third of the graph at most. The rest is prose: a
# STATUS.md linking a deliverable, a memory file linking the task it came
# from. Closing one stream moved it from `work/streams/` to
# `work/done/YYYY-MM/` and left about 14 such links dead, fixed by hand. The
# links are RELATIVE to the file they sit in, so a move breaks them twice: the
# links pointing INTO the moved folder, and the moved files' own links pointing
# OUT, because their depth changed.

MONTH = "2026-10"


def _moved_stream(tmp_path):
    return _tree(tmp_path, {
        f"work/done/{MONTH}/river/STATUS.md": (
            "# River\n\nSee [the task](../../tasks/alpha/STATUS.md).\n"
        ),
        f"work/done/{MONTH}/river/notes.md": "notes\n",
        "work/tasks/alpha/STATUS.md": (
            "# Alpha\n\nFrom [river](../../streams/river/STATUS.md#history).\n"
        ),
        "work/memory/fact.md": "Source: [notes](../streams/river/notes.md)\n",
    })


def test_a_relative_markdown_link_in_work_is_an_edge(tmp_path):
    _tree(tmp_path, {
        "work/tasks/alpha/STATUS.md": "[b](../beta/STATUS.md)\n",
        "work/tasks/beta/STATUS.md": "# Beta\n",
    })
    found = edges.iter_md_links(tmp_path)

    assert [(f, t) for f, _, t in found] == [
        ("work/tasks/alpha/STATUS.md", "work/tasks/beta/STATUS.md")]
    assert edges.check(tmp_path) == []


def test_links_into_a_moved_stream_are_reported_as_moved(tmp_path):
    _moved_stream(tmp_path)
    findings = edges.check(tmp_path)

    joined = "\n".join(findings)
    assert "work/tasks/alpha/STATUS.md" in joined
    assert "work/memory/fact.md" in joined
    assert all("moved" in f for f in findings)


def test_the_moved_files_own_outward_link_is_reported_too(tmp_path):
    _moved_stream(tmp_path)
    joined = "\n".join(edges.check(tmp_path))

    assert f"work/done/{MONTH}/river/STATUS.md" in joined


def test_fix_rewrites_every_moved_link_relative_to_its_own_file(tmp_path):
    _moved_stream(tmp_path)
    edges.fix_moved(tmp_path)

    alpha = (tmp_path / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")
    fact = (tmp_path / "work/memory/fact.md").read_text(encoding="utf-8")
    river = (tmp_path / f"work/done/{MONTH}/river/STATUS.md").read_text(encoding="utf-8")
    assert f"(../../done/{MONTH}/river/STATUS.md#history)" in alpha
    assert f"(../done/{MONTH}/river/notes.md)" in fact
    assert "(../../../tasks/alpha/STATUS.md)" in river
    assert edges.check(tmp_path) == []


def test_urls_anchors_mail_and_code_are_not_links_to_check(tmp_path):
    _tree(tmp_path, {
        "work/tasks/alpha/STATUS.md": (
            "[web](https://example.org/x.md) [top](#status) "
            "[mail](mailto:a@example.org) [abs](/etc/hosts)\n"
            "```\n[in code](../nowhere/STATUS.md)\n```\n"
            "`[inline](../nowhere/x.md)`\n"
        ),
    })
    assert edges.iter_md_links(tmp_path) == []


def test_a_dead_markdown_link_is_reported_and_left_alone_by_fix(tmp_path):
    _tree(tmp_path, {"work/tasks/alpha/STATUS.md": "[gone](../ghost/STATUS.md)\n"})
    findings = edges.check(tmp_path)

    assert len(findings) == 1 and "dead" in findings[0]
    edges.fix_moved(tmp_path)
    assert "(../ghost/STATUS.md)" in (
        tmp_path / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")


def test_templates_are_not_checked(tmp_path):
    _tree(tmp_path, {"work/templates/STATUS.md": "[x](../tasks/<slug>/STATUS.md)\n"})
    assert edges.iter_md_links(tmp_path) == []


def test_links_to_a_path_name_lists_the_files_that_still_point_there(tmp_path):
    _moved_stream(tmp_path)
    stale = edges.links_into(tmp_path, "work/streams/river")

    assert stale == ["work/memory/fact.md", "work/tasks/alpha/STATUS.md"]


def test_a_dead_link_in_closed_or_archived_work_is_history_not_a_finding(tmp_path):
    # A closed task often holds a snapshot of docs it worked on, with the
    # snapshot's own relative links. Measured on one instance: 238 of 369 dead
    # prose links sat in such copies. Reporting them buries the ones that matter.
    _tree(tmp_path, {
        f"work/done/{MONTH}/old/copy/README.md": "[gone](docs/never.md)\n",
        "work/archive/weeks/w1.md": "[gone](../nowhere.md)\n",
    })
    assert edges.check(tmp_path) == []


def test_a_moved_link_in_closed_work_is_still_reported(tmp_path):
    _moved_stream(tmp_path)
    joined = "\n".join(edges.check(tmp_path))

    assert f"work/done/{MONTH}/river/STATUS.md" in joined


# The first live run of the prose check, on one instance, flagged three
# "dead" links that were no links at all: a style rule saying "write every
# reference as [Text](URL)" twice, and a format example inside a code span
# that opened on the line above. Deleting them as dead would have damaged
# the rule text.

def test_a_bare_word_target_is_a_placeholder_not_a_link(tmp_path):
    _tree(tmp_path, {
        "work/memory/style.md": (
            "Write every reference as [Text](URL), never a bare id.\n"
            "links: markdown   # as [label](path)\n"
        ),
    })
    assert edges.iter_md_links(tmp_path) == []


def test_a_target_with_a_slash_is_still_a_link_without_an_extension(tmp_path):
    _tree(tmp_path, {"work/tasks/alpha/STATUS.md": "[dir](../beta)\n"})
    assert [t for _, _, t in edges.iter_md_links(tmp_path)] == ["work/tasks/beta"]


def test_a_code_span_that_opens_on_the_line_above_hides_its_example(tmp_path):
    _tree(tmp_path, {
        "work/tasks/alpha/STATUS.md": (
            "1. Write the `Gold\n"
            "   Summary` (every claim with `[ref +mm:ss](transcript.md#c-NNN)`)\n"
        ),
    })
    assert edges.iter_md_links(tmp_path) == []


def test_a_blank_line_ends_an_unclosed_code_span(tmp_path):
    _tree(tmp_path, {
        "work/tasks/alpha/STATUS.md": "a stray `tick\n\n[gone](../ghost/STATUS.md)\n",
    })
    assert [t for _, _, t in edges.iter_md_links(tmp_path)] == [
        "work/tasks/ghost/STATUS.md"]


def test_a_double_backtick_span_may_hold_a_single_backtick(tmp_path):
    _tree(tmp_path, {
        "work/tasks/alpha/STATUS.md": "`` a ` b [x](../ghost/STATUS.md) ``\n",
    })
    assert edges.iter_md_links(tmp_path) == []


def test_an_unmatched_backtick_is_literal_and_hides_nothing(tmp_path):
    _tree(tmp_path, {
        "work/tasks/alpha/STATUS.md": "a stray `tick\nthen [gone](../ghost/STATUS.md)\n",
    })
    assert [t for _, _, t in edges.iter_md_links(tmp_path)] == [
        "work/tasks/ghost/STATUS.md"]


# ------------------------------------------------------- design references --
# `design_ref:` and a theme's `branding.design:` name a design by id, not by
# path, so the path pattern above never sees them. They are edges all the same:
# an id that names no file under identity/designs/ makes scripts/designs.py
# refuse to resolve, and that should be red here before a generator meets it.


def test_a_design_ref_is_an_edge_to_the_design_file(tmp_path):
    _tree(tmp_path, {
        "workflow/contexts/client.yaml": "id: client\ndesign_ref: brand\n",
        "identity/personas/p.yaml": "id: p\ndesign_ref: brand\n",
        "themes/house.yaml": "meta: {name: house}\nbranding:\n  design: brand\n",
        "identity/designs/brand.md": "---\nname: brand\n---\n",
    })
    found = edges.all_edges(tmp_path)
    assert ("workflow/contexts/client.yaml", "design_ref", "identity/designs/brand.md") in found
    assert ("identity/personas/p.yaml", "design_ref", "identity/designs/brand.md") in found
    assert ("themes/house.yaml", "branding.design", "identity/designs/brand.md") in found
    assert edges.check(tmp_path) == []


def test_a_design_ref_to_a_missing_id_is_dead(tmp_path):
    _tree(tmp_path, {
        "workflow/contexts/client.yaml": "id: client\ndesign_ref: nobody\n",
        "themes/house.yaml": "meta: {name: house}\nbranding: {design: ghost}\n",
    })
    findings = edges.check(tmp_path)
    assert any("workflow/contexts/client.yaml :: design_ref" in f and "dead" in f for f in findings), findings
    assert any("themes/house.yaml :: branding.design" in f and "dead" in f for f in findings), findings


def test_a_template_design_ref_is_not_an_edge(tmp_path):
    _tree(tmp_path, {
        "workflow/contexts/_template.yaml": "design_ref: example-org\n",
        "themes/_template.yaml": "branding: {design: example-org}\n",
    })
    assert edges.check(tmp_path) == []
