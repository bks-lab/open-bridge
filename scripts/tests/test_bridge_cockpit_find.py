# SPDX-License-Identifier: MIT
"""The search over the work system (scripts/lib/work_find.py, scripts/work-find.py, the cockpit's /api/find):
which files it reads, how it ranks, where a log line goes, and that rg and plain Python give one answer."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import work_find as wf  # noqa: E402

HAS_RG = shutil.which("rg") is not None


def put(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def status(headline: str, body: str = "") -> str:
    return f"# yaml-language-server: $schema=x\n---\nstatus: doing\nheadline: {headline}\n---\n\n## Notes\n\n{body}\n"


@pytest.fixture
def bridge(tmp_path):
    root = tmp_path / "bridge"
    put(root, "work/tasks/invoice-onboarding/STATUS.md", status("Onboard the invoice vendor", "Gateway sends a 422."))
    put(root, "work/tasks/invoice-onboarding/notes.md", "In September the Gateway answer was a 422 again.\n")
    put(root, "work/tasks/invoice-onboarding/video/clip.md", "gateway september in a video folder\n")
    put(root, "work/tasks/invoice-onboarding/deliverables/out.md", "gateway september delivered\n")
    put(root, "work/tasks/invoice-onboarding/.private.md", "gateway september hidden\n")
    put(root, "work/tasks/invoice-onboarding/data.json", "gateway september json\n")
    put(root, "work/tasks/gateway-cleanup/STATUS.md", status("Tidy the old routes"))
    put(root, "work/streams/ops-watch/STATUS.md", status("Watch the runs"))
    put(root, "work/streams/ops-watch/runs.yaml", "note: gateway in september\n")
    put(root, "work/done/2026-09/old-task/STATUS.md", status("An older one", "gateway timeouts in September"))
    put(root, "work/log.md",
        "# Log\n\n## Mon 05.10\n\n| when | g | context | what |\n|---|---|---|---|\n"
        "| 2026-10-05 09:00 | x | gateway-cleanup | September gateway routes gone |\n"
        "| 2026-10-05 10:00 | x | misc | old-task: gateway September follow-up |\n"
        "| 2026-10-05 11:00 | x | misc | gateway check in September, no task |\n"
        "| 2026-10-05 12:00 | x | misc | gateway only |\n")
    put(root, "work/archive/2026-W40.md", "- gateway September summary for invoice-onboarding\n")
    return root


def slugs(result):
    return [g["slug"] or g["path"] for g in result["groups"]]


def test_the_query_is_checked_before_anything_is_read():
    assert wf.check_query("  Gateway   September ") == ("Gateway September", ["gateway", "september"])
    assert wf.check_query("a a A")[1] == ["a"]
    for bad in ("", " ", "x", "a\nb", "a\x00b", "x" * 201, None, 3, ["a"]):
        with pytest.raises(ValueError):
            wf.check_query(bad)


def test_files_are_grouped_and_ranked_name_then_status_then_the_rest(bridge):
    res = wf.find(bridge, "gateway september", engine="python")
    assert res["engine"] == "python" and res["words"] == ["gateway", "september"]
    # the slug holds "gateway", its log row "september": named? no, only gateway is in the name
    order = slugs(res)
    assert order[0] == "invoice-onboarding"           # rank 1: its STATUS.md holds a word, both words in the file
    by = {g["slug"] or g["path"]: g for g in res["groups"]}
    assert by["invoice-onboarding"]["rank"] == 1 and by["invoice-onboarding"]["kind"] == "task"
    assert by["invoice-onboarding"]["path"] == "work/tasks/invoice-onboarding"
    assert by["invoice-onboarding"]["title"] == "Onboard the invoice vendor"
    # a closed task is found, after the open ones of its rank
    assert by["old-task"]["kind"] == "done" and by["old-task"]["path"] == "work/done/2026-09/old-task"
    assert order.index("old-task") > order.index("invoice-onboarding")
    # the stream's only hit is in another file: rank 2
    assert by["ops-watch"]["rank"] == 2 and by["ops-watch"]["kind"] == "stream"


def test_a_name_that_holds_every_word_comes_first_even_without_a_line(bridge):
    res = wf.find(bridge, "gateway", engine="python")
    assert slugs(res)[0] == "gateway-cleanup" and res["groups"][0]["rank"] == 0
    put(bridge, "work/tasks/quiet-thing/STATUS.md", status("Nothing to say"))
    res = wf.find(bridge, "quiet", engine="python")
    assert slugs(res) == ["quiet-thing"] and res["groups"][0]["count"] == 0
    # the title counts as the name too
    assert slugs(wf.find(bridge, "invoice vendor", engine="python"))[0] == "invoice-onboarding"


def test_log_rows_go_to_the_file_their_context_or_their_text_names(bridge):
    by = {g["slug"] or g["path"]: g for g in wf.find(bridge, "gateway september", engine="python")["groups"]}
    cleanup = [h for h in by["gateway-cleanup"]["hits"] if h["path"] == "work/log.md"]
    assert [h["line"] for h in cleanup] == [7]
    assert any(h["path"] == "work/log.md" and h["line"] == 8 for h in by["old-task"]["hits"])
    # the archive line names its slug in the text
    assert any(h["path"] == "work/archive/2026-W40.md" for h in by["invoice-onboarding"]["hits"])
    # a row that names no slug stays with the log, and only when it holds every word itself
    loose = by["work/log.md"]
    assert loose["slug"] is None and loose["kind"] == "log" and [h["line"] for h in loose["hits"]] == [9]


def test_status_hits_lead_within_a_file_and_snippets_are_short(bridge):
    long = "word " * 80 + "gateway in the middle " + "tail " * 80
    put(bridge, "work/tasks/invoice-onboarding/long.md", long + "\n")
    g = next(x for x in wf.find(bridge, "gateway", engine="python")["groups"] if x["slug"] == "invoice-onboarding")
    assert g["hits"][0]["path"].endswith("/STATUS.md")
    cut = next(h for h in g["hits"] if h["path"].endswith("long.md"))["text"]
    assert len(cut) <= wf.SNIPPET_MAX + 2 and "gateway" in cut and cut.startswith("…") and cut.endswith("…")


def test_skipped_folders_hidden_files_other_types_and_links_are_never_read(bridge, tmp_path):
    outside = put(tmp_path, "outside/secret.md", "gateway september outside\n")
    os.symlink(outside, bridge / "work" / "tasks" / "invoice-onboarding" / "linked.md")
    os.symlink(outside.parent, bridge / "work" / "tasks" / "linked-dir")
    for engine in ("python",) + (("rg",) if HAS_RG else ()):
        res = wf.find(bridge, "gateway september", engine=engine)
        paths = {h["path"] for g in res["groups"] for h in g["hits"]}
        assert not any(p.split("/")[-2] in ("video", "deliverables") for p in paths), engine
        assert not any(p.endswith((".private.md", ".json", "linked.md")) for p in paths), engine
        assert "linked-dir" not in slugs(res)


def test_words_are_fixed_strings_never_patterns(bridge):
    put(bridge, "work/tasks/invoice-onboarding/odd.md", "price a.b( and [x]* here\n")
    for engine in ("python",) + (("rg",) if HAS_RG else ()):
        res = wf.find(bridge, "a.b( [x]*", engine=engine)
        assert slugs(res) == ["invoice-onboarding"], engine
        assert wf.find(bridge, "a.c(", engine=engine)["groups"] == []
        # a word that looks like an option is a word, and finds nothing here
        assert wf.find(bridge, "--files", engine=engine)["groups"] == []


@pytest.mark.skipif(not HAS_RG, reason="ripgrep is not installed")
def test_rg_and_python_give_the_same_answer(bridge):
    for query in ("gateway september", "gateway", "cleanup", "invoice vendor", "422", "nothing-like-this"):
        a = wf.find(bridge, query, engine="rg")
        b = wf.find(bridge, query, engine="python")
        assert a["engine"] == "rg" and b["engine"] == "python"
        assert {**a, "engine": None} == {**b, "engine": None}, query


def test_rg_is_called_with_argv_and_fixed_strings(bridge, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return subprocess.CompletedProcess(argv, 0, b"work/tasks/invoice-onboarding/notes.md\n../outside.md\n", b"")

    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    res = wf.find(bridge, "gateway -x", engine="rg", rg="/fake/rg")
    argv = seen["argv"]
    assert argv[0] == "/fake/rg" and seen["kw"]["shell"] is False and seen["kw"]["cwd"] == str(bridge.resolve())
    assert "--fixed-strings" in argv and "--no-ignore" in argv and "--no-config" in argv
    assert argv[argv.index("gateway") - 1] == "-e" and argv[argv.index("-x") - 1] == "-e"
    assert argv.index("--") < argv.index("work/tasks") and argv[-1] == "work/log.md"
    # what rg names is read only when it is eligible: a path outside is dropped
    assert res["engine"] == "rg"
    assert {h["path"] for g in res["groups"] for h in g["hits"]} <= {"work/tasks/invoice-onboarding/notes.md"}


def test_without_rg_or_when_it_fails_the_search_reads_the_files_itself(bridge, monkeypatch):
    monkeypatch.setattr(wf.shutil, "which", lambda name: None)
    assert wf.find(bridge, "gateway", engine="auto")["engine"] == "python"
    res = wf.find(bridge, "gateway", engine="rg", rg=str(bridge / "no-such-rg"))
    assert res["engine"] == "python" and slugs(res)[0] == "gateway-cleanup"

    def broken(argv, **kw):
        return subprocess.CompletedProcess(argv, 2, b"", b"rg: bad")

    monkeypatch.setattr(wf.subprocess, "run", broken)
    assert wf.find(bridge, "gateway", engine="rg", rg="/fake/rg")["engine"] == "python"


def test_many_files_are_cut_and_say_so(bridge):
    for i in range(5):
        put(bridge, f"work/tasks/extra-{i}/STATUS.md", status(f"Extra {i}", "gateway"))
    res = wf.find(bridge, "gateway", engine="python", groups_max=3)
    assert len(res["groups"]) == 3 and res["truncated"] is True and res["total"] > 3


def test_the_command_answers_in_json_and_in_lines(bridge):
    script = ROOT / "scripts" / "work-find.py"
    run = subprocess.run([sys.executable, str(script), "--root", str(bridge), "--json", "--engine", "python",
                          "gateway", "september"], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data["ok"] is True and data["groups"][0]["slug"] == "invoice-onboarding"
    run = subprocess.run([sys.executable, str(script), "--root", str(bridge), "--engine", "python", "cleanup"],
                         capture_output=True, text=True, check=False)
    assert run.returncode == 0 and run.stdout.startswith("gateway-cleanup")
    run = subprocess.run([sys.executable, str(script), "--root", str(bridge), "--json", "x"],
                         capture_output=True, text=True, check=False)
    assert run.returncode == 2 and "2 to 200" in run.stderr


def test_umlauts_and_sharp_s_fold_alike_in_both_ways(bridge):
    # rg folds case per character and never turns "ß" into "ss": the Python way folds the same, so neither finds
    # what the other cannot
    put(bridge, "work/tasks/street-works/STATUS.md", status("Road works", "Die Straße ist gesperrt. Äpfel liegen bereit."))
    assert wf.check_query("Straße ÄPFEL")[1] == ["straße", "äpfel"]
    engines = ("python",) + (("rg",) if HAS_RG else ())
    for engine in engines:
        for query in ("Straße", "straße", "STRAßE", "Äpfel", "äpfel", "ÄPFEL", "straße äpfel"):
            assert "street-works" in slugs(wf.find(bridge, query, engine=engine)), (engine, query)
        # "ss" for "ß" is another word, the same way in both
        assert "street-works" not in slugs(wf.find(bridge, "STRASSE", engine=engine)), engine
    if HAS_RG:
        for query in ("Straße", "STRASSE", "Äpfel", "ÄPFEL", "gesperrt Straße"):
            a, b = wf.find(bridge, query, engine="rg"), wf.find(bridge, query, engine="python")
            assert {**a, "engine": None} == {**b, "engine": None}, query


def test_a_slug_open_and_closed_is_two_files_each_with_its_own_hits(bridge):
    put(bridge, "work/tasks/weekly-report/STATUS.md", status("This week's report", "drafting"))
    put(bridge, "work/done/2026-08/weekly-report/STATUS.md", status("August report", "the zebra figure was wrong"))
    put(bridge, "work/done/2026-09/weekly-report/STATUS.md", status("September report", "the zebra chart"))
    for engine in ("python",) + (("rg",) if HAS_RG else ()):
        res = wf.find(bridge, "zebra", engine=engine)
        assert [(g["slug"], g["kind"], g["path"]) for g in res["groups"]] == [
            ("weekly-report", "done", "work/done/2026-09/weekly-report"),
            ("weekly-report", "done", "work/done/2026-08/weekly-report")], engine
        assert [g["title"] for g in res["groups"]] == ["September report", "August report"]
        assert all(h["path"].startswith(g["path"] + "/") for g in res["groups"] for h in g["hits"])
    # the name alone finds every copy, the open one first
    res = wf.find(bridge, "weekly-report", engine="python")
    assert [g["path"] for g in res["groups"]] == ["work/tasks/weekly-report", "work/done/2026-09/weekly-report",
                                                   "work/done/2026-08/weekly-report"]


def test_a_folder_without_a_slug_of_its_own_is_found_by_its_file(bridge):
    put(bridge, "work/tasks/_briefings/2026-10-05.md", "Morning: the gateway answered in September.\n")
    put(bridge, "work/tasks/Odd.Name/notes.md", "gateway\nseptember\n")
    for engine in ("python",) + (("rg",) if HAS_RG else ()):
        by = {g["slug"] or g["path"]: g for g in wf.find(bridge, "gateway september", engine=engine)["groups"]}
        brief = by["work/tasks/_briefings/2026-10-05.md"]
        assert brief["slug"] is None and brief["kind"] == "task" and brief["rank"] == 2
        assert [h["line"] for h in brief["hits"]] == [1]
        # every word in the file, on lines of their own
        odd = by["work/tasks/Odd.Name/notes.md"]
        assert odd["slug"] is None and odd["count"] == 2
        assert "work/tasks/_briefings/2026-10-05.md" not in slugs(wf.find(bridge, "morning nothing", engine=engine))
