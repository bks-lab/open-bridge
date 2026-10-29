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


# ---------------------------------------------------------------- the history: when something was done or discussed

@pytest.fixture
def past(tmp_path):
    root = tmp_path / "bridge"
    put(root, "work/log.md",
        "# Log\n\n## Thu 29.10\n\n| when | g | context | what |\n|---|---|---|---|\n"
        "| 2026-10-29 09:15 | x | billing | Gateway retry moved to the night run |\n"
        "| 2026-10-29 10:00 | x | misc | nothing to see |\n")
    put(root, "work/archive/weeks/2026-W12-raw.md",
        "# RAW Week 12\n\n## Mo 17.03\n\n### Log\n| Zeit | Typ | Context | Was |\n|---|---|---|---|\n"
        "| 2026-03-17 07:40 | x | billing | Gateway retry password renewed |\n\n"
        "## Mi 18.03\n\n| Zeit | Typ | Context | Was |\n|---|---|---|---|\n| 09:30 | x | billing | gateway retry plan drafted |\n")
    put(root, "work/archive/weeks/2027-W01-raw.md",
        "## Mo 28.12\n\n| 08:00 | x | ops | gateway retry at the year end |\n\n## Mo 04.01\n\n| 08:00 | x | ops | gateway retry in the new year |\n")
    put(root, "work/archive/weeks/2026-W12.md", "- gateway retry in a summary line, not a row\n")
    put(root, "work/archive/days/2026-10/28_insights.md",
        "# Insights\n\n## 18:00 · Weekly round\n\n- Gateway retry discussed, the night run agreed\n- another topic\n")
    put(root, "work/tasks/_meetings/2026-10-20-vendor-sync/summary.md", "# Vendor sync\n\n- gateway retry needs a vendor answer\n")
    put(root, "work/done/2026-09/retry-hardening/STATUS.md",
        "---\nstatus: done\nclosed: 2026-09-30\nheadline: Gateway retry hardened\n---\n\nrules for the gateway retry\n")
    put(root, "work/done/2026-08/old-thing/STATUS.md", "---\nstatus: done\n---\n\ngateway retry without a closed day\n")
    put(root, "work/tasks/open-task/STATUS.md", status("Gateway retry still open"))
    tr = tmp_path / "transcripts"
    put(tr, "2026-10-26_1649_vendor-call.md", "---\ntype: meeting-transcript-raw\n---\nA: the gateway retry\n"
        "B: gateway retry again\nA: gateway retry a third time\nB: gateway retry a fourth time\n")
    put(tr, "20260219-1044-old-call.md", "gateway retry under an older name\n")
    put(tr, "Voice Chat 20260807-1505-chat.md", "gateway retry in a voice chat\n")
    put(tr, "notes-without-a-day.md", "gateway retry with no day in its name\n")
    put(tr, "2026-10-01_0900_audio.txt", "gateway retry in a text file\n")
    put(tr, ".hidden/2026-10-02_0900_x.md", "gateway retry hidden\n")
    return root, tr


def by_text(res):
    return {e["text"]: e for e in res["entries"]}


def test_the_history_names_when_each_line_was_written_newest_first(past):
    root, tr = past
    res = wf.history(root, "gateway retry", transcripts=tr)
    assert res["ok"] is True and res["words"] == ["gateway", "retry"] and res["transcripts"] is True
    days = [(e["date"], e["time"] or "") for e in res["entries"]]
    assert days == sorted(days, reverse=True)
    got = by_text(res)
    row = got["Gateway retry moved to the night run"]
    assert row == {"date": "2026-10-29", "time": "09:15", "kind": "did", "source": "billing", "path": "work/log.md",
                   "line": 7, "text": "Gateway retry moved to the night run", "folder": None, "count": 1, "more": 0}
    assert got["Gateway retry password renewed"]["date"] == "2026-03-17"
    # an old row carries only its time: the day comes from the head above it, the year from the file's name
    old = got["gateway retry plan drafted"]
    assert (old["date"], old["time"], old["source"]) == ("2026-03-18", "09:30", "billing")
    # an ISO week names the year of its Thursday: 28.12 in week 1 of 2027 is still 2026
    assert got["gateway retry at the year end"]["date"] == "2026-12-28"
    assert got["gateway retry in the new year"]["date"] == "2027-01-04"


def test_the_history_takes_meetings_closed_tasks_and_transcripts_but_no_open_task_and_no_summary_line(past):
    root, tr = past
    got = by_text(wf.history(root, "gateway retry", transcripts=tr))
    talk = got["- Gateway retry discussed, the night run agreed"]
    assert (talk["date"], talk["time"], talk["kind"], talk["source"]) == ("2026-10-28", "18:00", "discussed", "Weekly round")
    meet = got["- gateway retry needs a vendor answer"]
    assert (meet["date"], meet["time"], meet["kind"], meet["source"]) == ("2026-10-20", None, "discussed", "vendor-sync")
    done = got["headline: Gateway retry hardened"]
    assert (done["date"], done["kind"], done["source"], done["folder"]) == ("2026-09-30", "closed", "retry-hardening",
                                                                            "work/done/2026-09/retry-hardening")
    assert got["gateway retry without a closed day"]["date"] == "2026-08"
    assert not any("still open" in t or "summary line" in t for t in got)
    call = [e for e in got.values() if e["source"] == "vendor-call"]
    # a transcript brings at most three lines and says how many it holds
    assert len(call) == wf.HISTORY_LINES and {e["count"] for e in call} == {4} and [e["more"] for e in call] == [0, 0, 1]
    assert (call[0]["date"], call[0]["time"], call[0]["kind"], call[0]["path"]) == ("2026-10-26", "16:49", "transcript",
                                                                                   "2026-10-26_1649_vendor-call.md")
    assert (got["gateway retry under an older name"]["date"], got["gateway retry under an older name"]["time"]) == ("2026-02-19", "10:44")
    assert got["gateway retry under an older name"]["source"] == "old-call"
    assert got["gateway retry in a voice chat"]["date"] == "2026-08-07" and got["gateway retry in a voice chat"]["source"] == "chat"
    for left in ("gateway retry with no day in its name", "gateway retry in a text file", "gateway retry hidden"):
        assert left not in got, left
    plain = wf.history(root, "gateway retry")
    assert plain["transcripts"] is False and not any(e["kind"] == "transcript" for e in plain["entries"])


def test_a_history_line_holds_every_word_and_the_words_stay_plain_text(past):
    root, tr = past
    got = by_text(wf.history(root, "night gateway", transcripts=tr))
    assert set(got) == {"Gateway retry moved to the night run", "- Gateway retry discussed, the night run agreed"}
    assert wf.history(root, "retry.*", transcripts=tr)["entries"] == []
    with pytest.raises(ValueError):
        wf.history(root, "x")


def test_the_history_never_follows_a_link_or_reads_an_oversized_file(past, tmp_path):
    root, tr = past
    outside = tmp_path / "outside.md"
    outside.write_text("gateway retry outside\n", encoding="utf-8")
    (tr / "2026-10-03_0900_link.md").symlink_to(outside)
    (root / "work" / "archive" / "days" / "2026-11").mkdir(parents=True)
    (root / "work" / "archive" / "days" / "2026-11" / "01_insights.md").symlink_to(outside)
    put(tr, "2026-10-04_0900_big.md", "gateway retry big\n" + "x" * (wf.FILE_MAX + 1))
    got = by_text(wf.history(root, "gateway retry", transcripts=tr))
    assert "gateway retry outside" not in got and "gateway retry big" not in got
    assert wf.history(root, "gateway retry", transcripts=tmp_path / "missing")["transcripts"] is False


def test_many_history_lines_are_cut_and_say_so(past):
    root, tr = past
    res = wf.history(root, "gateway retry", transcripts=tr, limit=3)
    assert len(res["entries"]) == 3 and res["truncated"] is True and res["total"] > 3


def test_the_candidates_for_a_question_come_by_how_many_terms_a_line_holds(past):
    root, tr = past
    got = wf.history_candidates(root, ["gateway", "night run", "vendor"], transcripts=tr)
    assert got[0]["score"] == 2 and {e["score"] for e in got[:2]} == {2}
    assert all(e["score"] >= 1 for e in got)
    assert sum(1 for e in got if e["source"] == "vendor-call") <= wf.HISTORY_LINES
    # within a day range only, and the range drops what has no full day
    ranged = wf.history_candidates(root, ["gateway"], transcripts=tr, since="2026-10-01", until="2026-10-31")
    assert ranged and all("2026-10-01" <= e["date"] <= "2026-10-31" for e in ranged)
    assert len(wf.history_candidates(root, ["gateway"], transcripts=tr, limit=2)) == 2
    assert wf.history_candidates(root, [], transcripts=tr) == []
    assert all(e["held"] == [] for e in got)


def test_a_block_word_anywhere_in_a_file_holds_back_every_line_of_it_a_log_row_only_itself(past):
    root, tr = past
    put(tr, "2026-10-27_0800_doctor-call.md", "A: gateway retry for the portal\nB: and the Gesundheit form\n")
    log = root / "work" / "log.md"
    log.write_text(log.read_text(encoding="utf-8") + "| 2026-10-29 11:00 | x | misc | gateway retry, Gesundheit portal |\n", encoding="utf-8")
    got = wf.history_candidates(root, ["gateway"], transcripts=tr, block=["Gesundheit"])
    held = [e for e in got if e["held"]]
    assert {(e["source"], e["text"]) for e in held} == {("doctor-call", "A: gateway retry for the portal"),
                                                        ("misc", "gateway retry, Gesundheit portal")}
    assert all(e["held"] == ["Gesundheit"] for e in held)
    # the held ones come after the ones that may go, and every other line of the log still goes
    first = next(i for i, e in enumerate(got) if e["held"])
    assert all(e["held"] for e in got[first:]) and any(e["source"] == "billing" for e in got[:first])


def test_the_two_history_calls_have_one_exact_shape_each_without_tools():
    models = {"claude-haiku-5-5"}
    for schema in (wf.HISTORY_TERMS_SCHEMA, wf.HISTORY_ANSWER_SCHEMA):
        argv = wf.history_argv("/fake/bin/claude", "claude-haiku-5-5", "Rules.", "data", schema)
        assert argv[:12] == ["/fake/bin/claude", "-p", "--model", "claude-haiku-5-5", "--output-format", "json",
                             "--no-session-persistence", "--setting-sources", "", "--tools", "", "--json-schema"]
        assert argv[12] == schema
        assert wf.history_argv_ok(argv, "/fake/bin/claude", models, schema)
        other = wf.HISTORY_ANSWER_SCHEMA if schema == wf.HISTORY_TERMS_SCHEMA else wf.HISTORY_TERMS_SCHEMA
        assert not wf.history_argv_ok(argv, "/fake/bin/claude", models, other)
        for change in (lambda a: a.__setitem__(3, "haiku"), lambda a: a.__setitem__(10, "Read"),
                       lambda a: a.insert(6, "--verbose"), lambda a: a.__setitem__(16, "")):
            bad = list(argv)
            change(bad)
            assert not wf.history_argv_ok(bad, "/fake/bin/claude", models, schema)
    assert not wf.history_argv_ok(wf.ask_argv("/fake/bin/claude", "claude-haiku-5-5", "R.", "d"), "/fake/bin/claude", models,
                                  wf.ASK_SCHEMA)


def test_the_terms_of_a_question_are_plain_words_and_a_range_only_of_real_days():
    system, text = wf.history_terms_prompt("When did we move the retry?", "Deutsch", "2026-10-29")
    assert "Deutsch" in system and "2026-10-29" in system and "never an instruction" in system
    assert text == f"{wf.ASK_QUESTION_LABEL}\nWhen did we move the retry?"
    out = json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.001, "modelUsage": {"claude-haiku-5-5": {}},
                      "structured_output": {"terms": ["Retry", "retry", "night run", "x", "a\nb", "y" * 41, 7, "Gateway"],
                                            "from": "2026-09-01", "to": "2026-13-01"}})
    got = wf.history_terms_parse(out)
    assert got["terms"] == ["retry", "night run", "gateway"] and got["from"] == "2026-09-01" and got["to"] is None
    assert got["cost_usd"] == 0.001 and got["used"] == "claude-haiku-5-5"
    assert wf.history_terms_parse("nonsense")["terms"] == []


def test_the_history_answer_carries_the_entries_as_data_and_names_them_only_by_number():
    entries = [{"n": 1, "date": "2026-10-29", "time": "09:15", "kind": "did", "source": "billing", "text": "t"}]
    system, text = wf.history_answer_prompt("When?", entries, "English", "2026-10-29")
    assert "English" in system and "never an instruction" in system
    head, data, label, question = text.split("\n", 3)
    assert "never an instruction" in head and json.loads(data) == {"entries": entries}
    assert label == wf.ASK_QUESTION_LABEL and question == "When?"
    out = json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.002, "modelUsage": {"claude-haiku-5-5": {}},
                      "structured_output": {"answer": " On 29.10. ", "entries": [{"n": 1, "why": "it moved"}, {"n": 4, "why": "no"},
                                                                                 {"n": 1, "why": "twice"}]}})
    got = wf.history_answer_parse(out, 1)
    assert got["answer"] == "On 29.10." and got["entries"] == [{"n": 1, "why": "it moved"}] and got["cost_usd"] == 0.002
    assert wf.history_answer_parse("", 1)["answer"] is None


def test_the_command_answers_the_history_in_json(past):
    root, tr = past
    script = ROOT / "scripts" / "work-find.py"
    run = subprocess.run([sys.executable, str(script), "--root", str(root), "--history", "--transcripts", str(tr), "--json",
                          "--", "gateway retry"], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data["ok"] is True and data["transcripts"] is True and data["entries"][0]["date"] == "2027-01-04"
    assert any(e["kind"] == "transcript" for e in data["entries"])
    run = subprocess.run([sys.executable, str(script), "--root", str(root), "--history", "--", "night gateway"],
                         capture_output=True, text=True, check=False)
    assert run.returncode == 0 and "2026-10-29 09:15" in run.stdout


# ---------------------------------------------------------------- the log over a time range (the cockpit's /api/logrange)

def test_every_log_row_with_its_day_and_glyph_newest_first_and_a_row_in_two_files_once(past):
    root, _ = past
    # the same row in a raw week and its summary, and once more in the log: one row
    put(root, "work/archive/weeks/2026-W43.md", "## Do 22.10\n\n| 2026-10-22 08:00 | 🔧 | billing | one row in two files |\n")
    put(root, "work/archive/weeks/2026-W43-raw.md", "## Do 22.10\n\n| 2026-10-22 08:00 | 🔧 | billing | one row in two files |\n")
    res = wf.log_rows(root)
    assert res["ok"] is True and res["first"] == "2026-03-17"
    when = [(r["date"], r["time"]) for r in res["rows"]]
    assert when == sorted(when, reverse=True) and res["total"] == len(res["rows"])
    assert [r["text"] for r in res["rows"]].count("one row in two files") == 1
    row = res["rows"][0]
    assert row == {"date": "2027-01-04", "time": "08:00", "glyph": "x", "context": "ops", "text": "gateway retry in the new year"}
    texts = {r["text"]: r for r in res["rows"]}
    # an old row takes its day from the head above it, a summary line is no row, nothing but the log and its archive
    assert (texts["gateway retry plan drafted"]["date"], texts["gateway retry plan drafted"]["time"]) == ("2026-03-18", "09:30")
    assert "nothing to see" in texts and not any("summary line" in t or "discussed" in t for t in texts)


def test_the_log_rows_of_a_range_of_days(past):
    root, _ = past
    got = wf.log_rows(root, since="2026-03-18", until="2026-10-29")
    assert {r["date"] for r in got["rows"]} == {"2026-03-18", "2026-10-29"}
    # first stays the first day of the whole log, so a page knows where All starts
    assert got["first"] == "2026-03-17"
    assert wf.log_rows(root, since="2028-01-01")["rows"] == []


def test_the_other_history_one_entry_per_meeting_talk_closed_task_and_transcript(past):
    root, tr = past
    res = wf.history_events(root, transcripts=tr)
    assert res["ok"] is True and res["transcripts"] is True
    got = {(e["kind"], e["source"]): e for e in res["entries"]}
    assert got[("discussed", "Weekly round")] == {"date": "2026-10-28", "time": "18:00", "kind": "discussed",
                                                  "source": "Weekly round", "path": "work/archive/days/2026-10/28_insights.md",
                                                  "folder": None}
    assert got[("discussed", "vendor-sync")]["date"] == "2026-10-20"
    assert got[("closed", "retry-hardening")]["folder"] == "work/done/2026-09/retry-hardening"
    assert got[("transcript", "vendor-call")]["time"] == "16:49"
    # one entry for a transcript of four lines; no open task, no log row, no file without a day
    assert sum(1 for e in res["entries"] if e["source"] == "vendor-call") == 1
    assert not any(e["kind"] == "did" for e in res["entries"])
    assert ("closed", "old-thing") not in got, "a month is no day to stand on in a chart"
    days = [(e["date"], e["time"] or "") for e in res["entries"]]
    assert days == sorted(days, reverse=True)
    assert wf.history_events(root)["transcripts"] is False


def test_the_other_history_with_words_keeps_what_holds_every_word_and_a_range_of_days(past):
    root, tr = past
    put(root, "work/archive/days/2026-10/27_insights.md", "## 09:00 · Standup\n\n- nothing about it\n\n## 11:00 · Night planning\n\n- the night run\n")
    got = wf.history_events(root, transcripts=tr, query="night run")
    assert {(e["kind"], e["source"]) for e in got["entries"]} == {("discussed", "Weekly round"), ("discussed", "Night planning")}
    ranged = wf.history_events(root, transcripts=tr, since="2026-10-21", until="2026-10-27")
    assert {e["date"] for e in ranged["entries"]} == {"2026-10-26", "2026-10-27"}
    with pytest.raises(ValueError):
        wf.history_events(root, query="x")


def test_the_history_takes_a_range_of_days_before_it_cuts(past):
    root, tr = past
    res = wf.history(root, "gateway retry", transcripts=tr, since="2026-03-01", until="2026-03-31")
    assert {e["date"] for e in res["entries"]} == {"2026-03-17", "2026-03-18"} and res["total"] == 2


def test_the_command_answers_the_rows_and_the_other_history_of_a_range(past):
    root, tr = past
    script = ROOT / "scripts" / "work-find.py"
    run = subprocess.run([sys.executable, str(script), "--root", str(root), "--rows", "--json", "--since", "2026-10-29",
                          "--until", "2026-10-29"], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert [r["text"] for r in data["rows"]] == ["nothing to see", "Gateway retry moved to the night run"]
    run = subprocess.run([sys.executable, str(script), "--root", str(root), "--events", "--json", "--transcripts", str(tr),
                          "--", "vendor"], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    # a line that holds the word, as the history lists it: the vendor call's name alone is no hit
    assert {e["source"] for e in json.loads(run.stdout)["entries"]} == {"vendor-sync"}
    run = subprocess.run([sys.executable, str(script), "--root", str(root), "--rows", "--since", "2026-13-01"],
                         capture_output=True, text=True, check=False)
    assert run.returncode == 2
