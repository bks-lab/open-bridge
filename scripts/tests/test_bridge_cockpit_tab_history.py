# SPDX-License-Identifier: MIT
"""Contract for the history of a tab (scripts/lib/bridge_cockpit/tab_history.py, GET /api/tab-history).

The tab view shows what the terminal shows now; the history is the whole conversation of the tab, searchable.
A tab that runs an agent session answers from the session's transcript (~/.claude/projects/<folder>/<id>.jsonl),
found through the live session the tab runs (sessions.py); a tab with none answers from the terminal's
scrollback through the driver. The rules:

* a transcript gives a person's words, the agent's words and one short line per tool call, never a tool's result,
  thinking, the harness's reminders, a subagent's turns or a meta line; a line that does not parse is skipped;
* the file is streamed and its parsed form kept by path, mtime and size, a file that grew is read from where it
  ended; the cockpit's key never leaves in a turn, and a search cannot find it;
* a search is a plain case-insensitive substring over the turns' text; the answer is capped in turns and bytes,
  the newest kept, with `truncated` saying that older turns were left out and `before` paging back to them;
* a tab with no session (or no transcript) reads the terminal with 5000 lines; the drivers and workplace.py let
  that many through;
* it reads and writes nothing and runs no agent.

Hermetic: no terminal driver, the Claude folder a temp one.

Run: pytest -q scripts/tests/test_bridge_cockpit_tab_history.py
"""
from __future__ import annotations

import json
import sys
import tracemalloc
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, W, ok, fail, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from test_bridge_cockpit_sessions import SID, SID_B, SURF, Home, asked, at, bash, lines, ms, result, said  # noqa: E402
from lib.bridge_cockpit import tab_history as th  # noqa: E402


# ---------------------------------------------------------------- a transcript as Claude Code writes it

def put(path: Path, *events, tail: str = "") -> Path:
    path.write_text("\n".join(lines(*events)) + "\n" + tail, encoding="utf-8")
    return path


def tool(name: str, data: dict, minute: int = 1) -> dict:
    return {"type": "assistant", "timestamp": at(minute), "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": name, "id": "t", "input": data}]}}


def pairs(turns: list[dict]) -> list[tuple]:
    return [(t["role"], t["text"]) for t in turns]


def mine(minute: int = 1) -> dict:
    return asked("fix the readme", minute)


# ---------------------------------------------------------------- what a transcript gives

def test_a_transcript_gives_the_conversation_and_nothing_else(tmp_path):
    path = put(tmp_path / "t.jsonl",
               {"type": "ai-title", "aiTitle": "A title"},
               {"type": "attachment", "attachment": {"type": "hook", "text": "attached"}},
               mine(1),
               said("let me look at it", 2, "thinking"),
               said("I will read the file first.", 3),
               bash("git status\nmore", 4),
               result("On branch main\n" * 500, 5),
               asked("<system-reminder>a reminder</system-reminder>", 6),
               asked("ok", 7, isMeta=True),
               {**said("a subagent talking", 8), "isSidechain": True},
               {"type": "api-request-blob", "blocks": [{"type": "text", "text": "blob"}]},
               {"type": "system", "subtype": "turn_duration", "content": "took 4s"},
               {**asked("This session is being continued", 9), "isCompactSummary": True},
               said("Done, README.md names the flag.", 10))
    turns, offset, dropped = th.read_turns(path)
    assert dropped == 0
    assert [(t["role"], t["text"], t["at_ms"]) for t in turns] == [
        ("user", "fix the readme", ms(1)),
        ("agent", "I will read the file first.", ms(3)),
        ("tool", "Bash: git status more", ms(4)),
        ("agent", "Done, README.md names the flag.", ms(10))]
    assert offset == path.stat().st_size


def test_a_tool_call_is_one_short_line_and_a_result_is_never_kept(tmp_path):
    long = "echo " + "x" * 5000
    path = put(tmp_path / "t.jsonl",
               tool("Read", {"file_path": "/a/b.py", "offset": 3}),
               tool("Grep", {"pattern": "needle", "path": "src"}),
               tool("Agent", {"description": "check the docs", "prompt": "a long brief " * 100}),
               tool("WebSearch", {"query": "cockpit history"}),
               tool("Bash", {"command": long}),
               tool("TodoWrite", {"todos": [{"content": "x"}]}),
               tool("NotebookEdit", {"notebook_path": "/n.ipynb", "new_source": "y"}),
               result("A SECRET RESULT " * 100, 2))
    turns, _, _ = th.read_turns(path)
    texts = [t["text"] for t in turns]
    assert texts[:4] == ["Read: /a/b.py", "Grep: needle", "Agent: check the docs", "WebSearch: cockpit history"]
    assert texts[4].startswith("Bash: echo xxx") and texts[4].endswith("…") and len(texts[4]) <= th.TOOL_MAX
    assert texts[5:] == ["TodoWrite", "NotebookEdit: /n.ipynb"]
    assert all("\n" not in x and "SECRET" not in x and t["role"] == "tool" for x, t in zip(texts, turns))


def test_the_persons_words_come_without_the_harness_reminders_and_a_command_reads_as_typed(tmp_path):
    path = put(tmp_path / "t.jsonl",
               asked("<system-reminder>be brief</system-reminder>\nplease check the build", 1),
               asked([{"type": "text", "text": "and then <local-command-stdout>ok</local-command-stdout>deploy"},
                      {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
                      {"type": "tool_result", "tool_use_id": "t", "content": "not a word of it"}], 2),
               asked("<command-name>/model</command-name>\n<command-message>model</command-message>\n"
                     "<command-args>opus</command-args>", 3),
               asked("<local-command-stdout>Set model to opus</local-command-stdout>", 4),
               asked("[Request interrupted by user]", 5))
    turns, _, _ = th.read_turns(path)
    assert pairs(turns) == [("user", "please check the build"), ("user", "and then  deploy"), ("user", "/model opus"),
                            ("user", "[Request interrupted by user]")]


def test_a_line_that_does_not_parse_is_skipped_and_a_turn_without_a_time_has_none(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join([
        "not json at all", '["a", "list"]', '{"type": "user", "message": {"content": "cut off', "",
        json.dumps({"type": "user", "message": {"content": "no time"}}),
        json.dumps({"type": "user", "timestamp": "yesterday", "message": {"content": "bad time"}}),
        json.dumps(mine(3)), json.dumps({"type": "assistant", "message": "not a dict"})]) + "\n", encoding="utf-8")
    turns, _, _ = th.read_turns(path)
    assert [(t["text"], t["at_ms"]) for t in turns] == [("no time", None), ("bad time", None), ("fix the readme", ms(3))]


def test_a_line_longer_than_the_limit_is_skipped_unread_and_the_next_one_still_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(th, "LINE_MAX", 1000)
    path = put(tmp_path / "t.jsonl", asked("first", 1), asked("y" * 5000, 2), asked("last", 3))
    turns, offset, _ = th.read_turns(path)
    assert pairs(turns) == [("user", "first"), ("user", "last")] and offset == path.stat().st_size


def test_a_turn_is_cut_where_it_is_kept_and_a_text_is_scrubbed_as_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(th, "TURN_MAX", 50)
    path = put(tmp_path / "t.jsonl", said("a" * 200, 1), asked("my key is SECRET-1", 2))
    turns, _, _ = th.read_turns(path, scrub=lambda s: s.replace("SECRET-1", "[token]"))
    assert turns[0]["text"] == "a" * 49 + "…" and turns[1]["text"] == "my key is [token]"


def test_a_large_transcript_is_streamed_not_loaded(tmp_path):
    path = tmp_path / "big.jsonl"
    big = json.dumps(result("x" * 100_000, 1))
    with path.open("w", encoding="utf-8") as fh:
        for n in range(200):
            fh.write(big + "\n" + json.dumps(asked(f"question {n}", 2)) + "\n")
    assert path.stat().st_size > 20_000_000
    tracemalloc.start()
    try:
        turns, _, _ = th.read_turns(path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert len(turns) == 200 and peak < 5_000_000


# ---------------------------------------------------------------- kept by path, mtime and size

def reads(monkeypatch) -> list[int]:
    """The byte every read of a transcript began at"""
    starts: list[int] = []
    real = th.read_turns

    def spy(path, start=0, scrub=str, keep=None):
        starts.append(start)
        return real(path, start, scrub, keep)
    monkeypatch.setattr(th, "read_turns", spy)
    return starts


def history() -> th.TabHistory:
    return th.TabHistory(types.SimpleNamespace(scrub=lambda s: s))


def test_a_transcript_unchanged_is_read_once_and_one_that_grew_from_where_it_ended(tmp_path, monkeypatch):
    starts = reads(monkeypatch)
    path = put(tmp_path / "t.jsonl", mine(1), said("one", 2))
    h = history()
    assert pairs(h.session_turns(path)[0]) == [("user", "fix the readme"), ("agent", "one")]
    assert len(h.session_turns(path)[0]) == 2 and starts == [0]
    ended = path.stat().st_size
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines(said("two", 3))) + "\n")
    turns, dropped = h.session_turns(path)
    assert pairs(turns)[-1] == ("agent", "two") and len(turns) == 3 and dropped == 0
    assert starts == [0, ended]


def test_a_line_still_being_written_waits_until_it_is_whole(tmp_path, monkeypatch):
    starts = reads(monkeypatch)
    path = put(tmp_path / "t.jsonl", mine(1))
    h = history()
    h.session_turns(path)
    whole = json.dumps(said("later", 2))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(whole[:30])
    assert len(h.session_turns(path)[0]) == 1
    with path.open("a", encoding="utf-8") as fh:
        fh.write(whole[30:] + "\n")
    assert pairs(h.session_turns(path)[0]) == [("user", "fix the readme"), ("agent", "later")]
    assert starts[1] == starts[2] != 0


def test_a_transcript_that_was_rewritten_is_read_again_from_its_start(tmp_path, monkeypatch):
    starts = reads(monkeypatch)
    path = put(tmp_path / "t.jsonl", mine(1), said("one", 2))
    h = history()
    h.session_turns(path)
    put(path, asked("a different conversation entirely", 1), said("with more words than before in it", 2), said("x", 3))
    assert pairs(h.session_turns(path)[0])[0] == ("user", "a different conversation entirely")
    assert starts == [0, 0]


def test_a_missing_transcript_is_none_and_at_most_a_few_are_kept(tmp_path, monkeypatch):
    h = history()
    assert h.session_turns(tmp_path / "gone.jsonl") is None
    monkeypatch.setattr(th, "CACHE_MAX", 2)
    paths = [put(tmp_path / f"{n}.jsonl", mine(1)) for n in range(4)]
    for p in paths:
        h.session_turns(p)
    assert list(h.cache) == [str(p) for p in paths[-2:]]


def test_a_conversation_over_the_store_keeps_the_newest_and_counts_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(th, "STORE_MAX", 5)
    path = put(tmp_path / "t.jsonl", *[asked(f"q{n}", 1) for n in range(8)])
    h = history()
    turns, dropped = h.session_turns(path)
    assert [t["text"] for t in turns] == ["q3", "q4", "q5", "q6", "q7"] and dropped == 3
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asked("q8", 1)) + "\n")
    turns, dropped = h.session_turns(path)
    assert turns[0]["text"] == "q4" and dropped == 4
    answer = th.window(turns, dropped, "", 50, None)
    assert answer["total"] == 9 and answer["matched"] == 5 and answer["truncated"] is True
    assert answer["turns"][0]["i"] == 4


# ---------------------------------------------------------------- search, paging and the caps

def convo(n: int, text=lambda k: f"turn {k}") -> list[dict]:
    return [{"role": "user" if k % 2 == 0 else "agent", "text": text(k), "at_ms": 1000 + k} for k in range(n)]


def test_a_search_is_a_case_insensitive_substring_over_the_text_alone():
    turns = convo(6, lambda k: ["README is here", "nothing", "the readme again", "a user said so", "Straße", "last"][k])
    got = th.window(turns, 0, "ReadMe", 50, None)
    assert [t["i"] for t in got["turns"]] == [0, 2] and got["matched"] == 2 and got["total"] == 6
    assert got["truncated"] is False
    assert th.window(turns, 0, "agent", 50, None)["matched"] == 0          # the role is no text
    assert th.window(turns, 0, "STRASSE", 50, None)["matched"] == 1
    assert th.window(turns, 0, "zzz", 50, None) == {"turns": [], "total": 6, "matched": 0, "truncated": False}
    assert th.window(turns, 0, "e.*a", 50, None)["matched"] == 0            # plain text, no pattern


def test_the_newest_turns_are_kept_in_order_and_before_pages_back(tmp_path):
    turns = convo(300)
    first = th.window(turns, 0, "", 100, None)
    assert [t["i"] for t in first["turns"]] == list(range(200, 300))
    assert (first["total"], first["matched"], first["truncated"]) == (300, 300, True)
    second = th.window(turns, 0, "", 100, first["turns"][0]["i"])
    assert [t["i"] for t in second["turns"]] == list(range(100, 200)) and second["truncated"] is True
    last = th.window(turns, 0, "", 100, second["turns"][0]["i"])
    assert [t["i"] for t in last["turns"]] == list(range(100)) and last["truncated"] is False
    assert last["matched"] == 300
    searched = th.window(turns, 0, "turn 2", 5, None)           # 2, 20-29, 200-299: the newest five of 111
    assert [t["i"] for t in searched["turns"]] == [295, 296, 297, 298, 299]
    assert searched["matched"] == 111 and searched["truncated"] is True


def test_the_answer_is_capped_in_bytes_newest_first_and_never_empty(monkeypatch):
    turns = convo(5, lambda k: f"{k}" * 60)
    monkeypatch.setattr(th, "ANSWER_BYTES", 150)
    got = th.window(turns, 0, "", 50, None)
    assert [t["i"] for t in got["turns"]] == [3, 4] and got["truncated"] is True
    monkeypatch.setattr(th, "ANSWER_BYTES", 10)
    got = th.window(turns, 0, "", 50, None)
    assert [t["i"] for t in got["turns"]] == [4] and got["truncated"] is True
    monkeypatch.setattr(th, "ANSWER_BYTES", 10_000)
    assert th.window(turns, 0, "", 50, None)["truncated"] is False
    assert th.window([], 0, "", 50, None) == {"turns": [], "total": 0, "matched": 0, "truncated": False}


def test_the_bytes_are_counted_in_utf8_not_in_characters(monkeypatch):
    monkeypatch.setattr(th, "ANSWER_BYTES", 100)
    got = th.window(convo(4, lambda k: "ä" * 30), 0, "", 50, None)       # 60 bytes each
    assert [t["i"] for t in got["turns"]] == [3]


@pytest.mark.parametrize("limit,before,want", [("", "", (th.ANSWER_TURNS, None)), ("10", "5", (10, 5)),
                                                ("0", "0", (1, 0)), ("100000", "", (th.ANSWER_TURNS_MAX, None))])
def test_the_paging_words_are_numbers_and_the_limit_is_held_to_its_range(limit, before, want):
    assert th.paging(limit, before) == want


@pytest.mark.parametrize("limit,before,field", [("ten", "", "limit"), ("", "x", "before"), ("", "-1", "before"),
                                                ("1.5", "", "limit")])
def test_a_paging_word_that_is_no_number_names_itself(limit, before, field):
    with pytest.raises(ValueError, match=field):
        th.paging(limit, before)


def test_the_terminal_is_cut_into_blocks_at_the_blank_lines_and_at_a_cap(monkeypatch):
    monkeypatch.setattr(th, "BLOCK_LINES", 3)
    blocks = th.blocks_of("$ ls\na\nb\n\n\n$ make\n1\n2\n3\n4\n5\n  \n$ ")
    assert [(b["role"], b["text"], b["at_ms"]) for b in blocks] == [
        ("terminal", "$ ls\na\nb", None), ("terminal", "$ make\n1\n2", None), ("terminal", "3\n4\n5", None),
        ("terminal", "$", None)]
    assert th.blocks_of("") == [] and th.blocks_of("\n\n") == []


# ---------------------------------------------------------------- the route

@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


@pytest.fixture
def home(tmp_path):
    w = World(tmp_path)
    yield w, Home(w, tmp_path)
    w.close()


def get(w, query: str, headers=True) -> tuple[int, dict]:
    status, _, body = w.request("GET", f"/api/tab-history?{query}", headers=w.cookie if headers else None)
    return status, json.loads(body)


def test_a_tab_with_a_session_answers_from_its_transcript_and_not_from_the_terminal(home):
    w, h = home
    h.session(SID, w.root, said("let me think", 1, "thinking"), said("I will read it.", 2), bash("git status", 3),
              result("a long result", 4), asked("thanks", 5), said("Done.", 6))
    h.poll()
    w.runner.calls.clear()
    status, data = get(w, "ref=surface:4100")
    assert status == 200 and data["ok"] is True and data["source"] == "session" and data["ref"] == "surface:4100"
    assert pairs(data["turns"]) == [("user", "hello"), ("agent", "I will read it."), ("tool", "Bash: git status"),
                                    ("user", "thanks"), ("agent", "Done.")]
    assert [t["i"] for t in data["turns"]] == [0, 1, 2, 3, 4] and data["turns"][1]["at_ms"] == ms(2)
    assert (data["total"], data["matched"], data["truncated"]) == (5, 5, False)
    assert w.runner.of("workplace.screen") == [] and w.runner.calls == []


def test_the_search_and_the_paging_reach_the_route(home):
    w, h = home
    h.session(SID, w.root, *[x for n in range(30) for x in (asked(f"question {n}", 1), said(f"answer {n} about the README", 2))])
    h.poll()
    status, data = get(w, "ref=surface:4100&q=readme&limit=5")
    assert status == 200 and data["matched"] == 30 and data["total"] == 61 and data["truncated"] is True
    assert pairs(data["turns"])[-1] == ("agent", "answer 29 about the README") and len(data["turns"]) == 5
    status, older = get(w, f"ref=surface:4100&q=readme&limit=5&before={data['turns'][0]['i']}")
    assert status == 200 and older["turns"][-1]["text"] == "answer 24 about the README"
    assert get(w, "ref=surface:4100&q=nothing+like+it")[1]["turns"] == []


def test_the_key_never_leaves_in_a_turn_and_a_search_cannot_find_it(home):
    w, h = home
    key = w.app.token
    h.session(SID, w.root, said(f"the key is {key}", 1), bash(f"curl -H 'X-Bridge-Token: {key}' x", 2))
    h.poll()
    status, _, body = w.request("GET", "/api/tab-history?ref=surface:4100", headers=w.cookie)
    assert status == 200 and key.encode() not in body and b"[token]" in body
    assert get(w, f"ref=surface:4100&q={key}")[1]["matched"] == 0


def test_the_newest_session_of_a_tab_decides_and_a_session_without_its_file_falls_to_the_terminal(home):
    w, h = home
    h.session(SID, w.root, said("from the old session", 1), pid=4100, surface=SURF, started_ms=ms(0))
    h.session(SID_B, w.root, said("from the new session", 1), pid=4200, surface=SURF, started_ms=ms(5))
    h.poll()
    status, data = get(w, "ref=surface:4200")
    assert data["source"] == "session" and pairs(data["turns"])[-1] == ("agent", "from the new session")
    from lib.bridge_cockpit import sessions as sess
    sess.transcript_path(h.base, str(w.root), SID_B).unlink()
    w.runner.handlers["workplace.screen"] = lambda argv: ok({"text": "$ pwd\n/work\n"})
    status, data = get(w, "ref=surface:4200")
    assert status == 200 and data["source"] == "session" and pairs(data["turns"])[-1] == ("agent", "from the old session")
    sess.transcript_path(h.base, str(w.root), SID).unlink()
    status, data = get(w, "ref=surface:4200")
    assert data["source"] == "terminal" and pairs(data["turns"]) == [("terminal", "$ pwd\n/work")]


def test_a_transcript_in_another_project_folder_is_still_found_by_its_session_id(home):
    w, h = home
    path = h.session(SID, w.root, said("moved", 1))
    elsewhere = h.base / "projects" / "-some-other-folder"
    elsewhere.mkdir()
    path.rename(elsewhere / path.name)
    h.poll()
    status, data = get(w, "ref=surface:4100")
    assert data["source"] == "session" and pairs(data["turns"])[-1] == ("agent", "moved")


def test_a_tab_without_a_session_reads_the_terminal_with_five_thousand_lines(world):
    scrollback = "$ make\nbuilding\n\n$ ls\nREADME.md\n  \n$ echo SECRET-KEY  \n"
    world.runner.handlers["workplace.screen"] = lambda argv: ok({"text": scrollback.replace("SECRET-KEY", world.app.token)})
    world.runner.calls.clear()
    status, _, body = world.request("GET", "/api/tab-history?ref=surface:11", headers=world.cookie)
    data = json.loads(body)
    assert status == 200 and data["source"] == "terminal" and data["name"] == "free tab"
    assert pairs(data["turns"]) == [("terminal", "$ make\nbuilding"), ("terminal", "$ ls\nREADME.md"),
                                    ("terminal", "$ echo [token]")]
    assert all(t["at_ms"] is None for t in data["turns"]) and world.app.token.encode() not in body
    assert (data["total"], data["matched"], data["truncated"]) == (3, 3, False)
    assert world.runner.calls == [W(world, "screen", "surface:11", "--lines", "5000", "--json")]
    assert get(world, "ref=surface:11&q=README")[1]["matched"] == 1


def test_the_terminal_is_read_again_only_after_a_moment(world):
    world.runner.handlers["workplace.screen"] = lambda argv: ok({"text": "$ one\n"})
    world.runner.calls.clear()
    get(world, "ref=surface:11")
    get(world, "ref=surface:11&q=one")
    assert len(world.runner.of("workplace.screen")) == 1
    world.clock.advance(th.TERMINAL_CACHE_MS / 1000 + 1)
    world.runner.handlers["workplace.screen"] = lambda argv: ok({"text": "$ one\n\n$ two\n"})
    assert get(world, "ref=surface:11")[1]["total"] == 2 and len(world.runner.of("workplace.screen")) == 2


def test_a_terminal_that_cannot_be_read_is_unreadable_and_says_so_without_the_key(world):
    world.runner.handlers["workplace.screen"] = lambda argv: fail(f"driver {world.app.token} failed")
    status, data = get(world, "ref=surface:11")
    assert status == 502 and data["error"]["code"] == "unreadable" and world.app.token not in json.dumps(data)
    world.runner.handlers["workplace.screen"] = lambda argv: ok("not json")
    assert get(world, "ref=surface:11")[0] == 502


@pytest.mark.parametrize("query,status,field", [
    ("ref=surface:7;ls", 400, "ref"), ("", 400, "ref"), ("ref=surface:99", 404, None),
    ("ref=surface:7&limit=ten", 400, "limit"), ("ref=surface:7&before=-2", 400, "before"),
    (f"ref=surface:7&q={'x' * 201}", 400, "q")])
def test_a_bad_ref_or_word_is_refused_before_anything_is_read(world, query, status, field):
    world.runner.calls.clear()
    got, data = get(world, query)
    assert got == status and data["ok"] is False and data["error"]["field"] == field
    assert world.runner.calls == []


def test_the_page_needs_its_cookie(world):
    assert world.request("GET", "/api/tab-history?ref=surface:7")[0] == 401


def test_it_reads_and_writes_nothing_and_runs_no_agent(home):
    w, h = home
    path = h.session(SID, w.root, said("a", 1), bash("ls", 2))
    h.poll()
    before = (path.stat().st_mtime_ns, path.read_bytes(), sorted(p.name for p in w.state.rglob("*")))
    w.runner.calls.clear()
    assert get(w, "ref=surface:4100&q=a")[0] == 200
    assert (path.stat().st_mtime_ns, path.read_bytes(), sorted(p.name for p in w.state.rglob("*"))) == before
    assert w.runner.calls == []
