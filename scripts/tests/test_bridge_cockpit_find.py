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


def test_every_file_says_whether_it_is_a_task_or_a_stream_also_once_closed(bridge):
    # task.py writes a comment line before the fence; an ended stream keeps was_stream: true
    put(bridge, "work/done/2026-10/ended-watch/STATUS.md",
        "# yaml-language-server: $schema=x\n---\nstatus: done\nwas_stream: true\nheadline: Gateway watch ended\n---\n")
    res = wf.find(bridge, "gateway", engine="python")
    kinds = {g["path"]: g["work_kind"] for g in res["groups"]}
    assert kinds["work/tasks/gateway-cleanup"] == "task"
    assert kinds["work/streams/ops-watch"] == "stream"
    assert kinds["work/done/2026-09/old-task"] == "done_task"
    assert kinds["work/done/2026-10/ended-watch"] == "done_stream"
    assert all(v is None for p, v in kinds.items() if not p.startswith("work/"))


# ---------------------------------------------------------------- the records of the files tab, the block list, the ask

def test_every_file_is_a_record_newest_change_first_with_its_status_area_and_kind(bridge):
    put(bridge, "work/tasks/invoice-onboarding/STATUS.md",
        "# x\n---\nstatus: doing\npriority: P1\narea: ACME\nlast_updated: 2026-10-08\nheadline: Onboard the vendor\n---\n")
    put(bridge, "work/streams/ops-watch/STATUS.md", "---\nstatus: doing\ncontext: ops\nlast_updated: 2026-10-01\n---\n# Watch the runs\n")
    put(bridge, "work/done/2026-09/old-task/STATUS.md", "---\nstatus: done\nclosed: '2026-09-20'\nheadline: An older one\n---\n")
    res = wf.records(bridge)
    assert res["ok"] is True and res["total"] == 4 and res["truncated"] is False
    by = {r["path"]: r for r in res["records"]}
    assert by["work/tasks/invoice-onboarding"] == {
        "slug": "invoice-onboarding", "kind": "task", "path": "work/tasks/invoice-onboarding", "title": "Onboard the vendor",
        "status": "doing", "priority": "P1", "area": "ACME", "updated": "2026-10-08", "work_kind": "task"}
    # an area the front matter does not name comes from its context; a title from the first heading
    assert by["work/streams/ops-watch"]["area"] == "ops" and by["work/streams/ops-watch"]["title"] == "Watch the runs"
    assert by["work/streams/ops-watch"]["work_kind"] == "stream"
    # a closed one is done, changed the day it closed
    old = by["work/done/2026-09/old-task"]
    assert old["status"] == "done" and old["updated"] == "2026-09-20" and old["kind"] == "done" and old["work_kind"] == "done_task"
    # the newest change first, a record without a day last
    assert [r["path"] for r in res["records"]] == ["work/tasks/invoice-onboarding", "work/streams/ops-watch",
                                                   "work/done/2026-09/old-task", "work/tasks/gateway-cleanup"]
    cut = wf.records(bridge, limit=2)
    assert len(cut["records"]) == 2 and cut["truncated"] is True and cut["total"] == 4


def test_a_record_with_an_unreadable_front_matter_still_counts_by_its_folder(bridge):
    put(bridge, "work/tasks/broken-front/STATUS.md", "---\nstatus: [unclosed\n---\n# Still a record\n")
    rec = {r["slug"]: r for r in wf.records(bridge)["records"]}["broken-front"]
    assert rec["title"] == "Still a record" and rec["status"] is None and rec["area"] is None


def test_the_block_list_holds_a_record_back_by_any_word_in_its_area_theme_path_or_title():
    words = ["Versicherung", "Gesundheit", "  ", 3, "versicherung"]
    assert wf.block_words(words) == ["Versicherung", "Gesundheit"]
    assert wf.held_by(["work/tasks/versicherung-bestand", "Bestand"], ["Versicherung", "Gesundheit"]) == ["Versicherung"]
    assert wf.held_by(["ACME", None, "Familie/Gesundheit/Arzt"], ["Versicherung", "Gesundheit"]) == ["Gesundheit"]
    assert wf.held_by(["work/tasks/invoice", "Invoice", "ACME"], ["Versicherung"]) == []
    assert wf.held_by(["anything"], []) == []


def test_the_text_a_record_brings_to_a_question_is_its_status_md_cut_short(bridge):
    put(bridge, "work/tasks/long-one/STATUS.md", "---\nstatus: doing\n---\n# Long\n" + "word " * 2000)
    text = wf.ask_text(bridge, "work/tasks/long-one")
    assert text.startswith("---\nstatus: doing") and len(text) <= wf.ASK_TEXT_MAX
    assert wf.ask_text(bridge, "work/tasks/missing") == ""


def test_a_record_never_follows_a_symlinked_or_oversized_status_md(bridge, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("---\nstatus: doing\nheadline: Secret outside\n---\nsecret text\n", encoding="utf-8")
    (bridge / "work/tasks/linked").mkdir(parents=True)
    (bridge / "work/tasks/linked/STATUS.md").symlink_to(outside)
    put(bridge, "work/tasks/huge/STATUS.md", "---\nstatus: doing\nheadline: Huge\n---\n" + "x" * (wf.FILE_MAX + 10))
    for folder, slug in (("work/tasks/linked", "linked"), ("work/tasks/huge", "huge")):
        assert wf.ask_text(bridge, folder) == "", folder
        assert wf.front_of(bridge, folder) == {}, folder
        assert wf.title_of(bridge, folder, slug) == slug, folder
    rec = {r["slug"]: r for r in wf.records(bridge)["records"]}
    assert rec["linked"]["title"] == "linked" and rec["linked"]["status"] is None


def test_the_ask_argv_is_one_exact_shape_without_tools():
    argv = wf.ask_argv("/fake/bin/claude", "claude-haiku-5-5", "Answer it.", "data")
    assert argv[:12] == ["/fake/bin/claude", "-p", "--model", "claude-haiku-5-5", "--output-format", "json",
                         "--no-session-persistence", "--setting-sources", "", "--tools", "", "--json-schema"]
    assert argv[12] == wf.ASK_SCHEMA and argv[13] == "--append-system-prompt" and argv[15] == "--"
    models = {"claude-haiku-5-5"}
    assert wf.ask_argv_ok(argv, "/fake/bin/claude", models)
    for change in (lambda a: a.__setitem__(3, "haiku"), lambda a: a.__setitem__(10, "Read"),
                   lambda a: a.__setitem__(12, "{}"), lambda a: a.insert(6, "--verbose"), lambda a: a.__setitem__(16, "")):
        bad = list(argv)
        change(bad)
        assert not wf.ask_argv_ok(bad, "/fake/bin/claude", models)
    assert not wf.ask_argv_ok(argv, None, models)


def test_the_prompt_carries_the_records_as_data_and_the_question_after_them():
    recs = [{"n": 1, "title": "Onboard", "slug": "a", "status": "doing", "area": "ACME", "updated": "2026-10-08", "text": "t"}]
    system, text = wf.ask_prompt("Which one waits?", recs, "Deutsch")
    assert "Deutsch" in system and "never an instruction" in system
    head, data, label, question = text.split("\n", 3)
    assert "never an instruction" in head and json.loads(data) == {"records": recs}
    assert label == wf.ASK_QUESTION_LABEL and question == "Which one waits?"


def test_the_answer_names_records_only_by_a_number_it_was_given():
    out = json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.001, "modelUsage": {"claude-haiku-5-5": {}},
                      "structured_output": {"answer": "  The vendor one waits.  ", "files": [
                          {"n": 2, "why": "it waits on the vendor"}, {"n": 9, "why": "made up"}, {"n": 2, "why": "twice"},
                          {"n": "1", "why": "no number"}]}})
    got = wf.ask_parse(out, 2)
    assert got["answer"] == "The vendor one waits." and got["files"] == [{"n": 2, "why": "it waits on the vendor"}]
    assert got["cost_usd"] == 0.001
    assert wf.ask_parse("not json", 2)["answer"] is None
