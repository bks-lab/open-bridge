# SPDX-License-Identifier: MIT
"""What a waiting tab asks, and answering it from the cockpit (feature A).

asks.py reads the question off a tab's screen (pure, no I/O); the tab poll reads the screens of the tabs
that wait, capped per poll and in time, only when a tab's state changed or its question grew old; a
reply names the question it answers (its hash), the tab's name and the state it expects, and the server
reads the screen fresh before anything reaches the tab. Uses the world of test_bridge_cockpit (fake runner).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import STATUS, World, W, ok, private_key_dir, writes  # noqa: E402,F401  (the autouse fixture comes along)

from lib.bridge_cockpit import asks  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402

PERMISSION = """\
⏺ I will remove the old build folder first.

⏺ Bash(rm -rf build)

 Bash command

   rm -rf build
   Remove the old build folder

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don't ask again for rm commands in this folder
   3. No, and tell Claude what to do differently (esc)
"""

BOXED = """\
╭──────────────────────────────────────────────────╮
│ Edit file                                        │
│ README.md                                        │
│                                                  │
│ Do you want to make this edit to README.md?      │
│ ❯ 1. Yes                                         │
│   2. Yes, allow all edits during this session    │
│   3. No, and tell Claude what to do differently  │
╰──────────────────────────────────────────────────╯
"""

PLAN = """\
 Here is the plan: three steps, the tests first.

 Would you like to proceed
 ❯ 1. Yes, and auto-accept edits
   2. Yes, and manually approve edits
   3. No, keep planning
"""

CHOICE = """\
 Which store should the cache use
 ❯ 1. Files
      One file per entry, simple
   2. A database
      Faster with many entries
"""

WAITING = """\
> fix the readme

⏺ Read(README.md)
  ⎿  Read 40 lines

⏺ The flag is documented now.
  README.md names it under Options,
  with one example.
  Should I also add it to the changelog?

✻ Cooked for 1m 12s

──────────────────────────────────────────
❯
──────────────────────────────────────────
  ⏵⏵ accept edits on (shift+tab to cycle)
"""

SUMMARY = """\
⏺ Done. The three tests are green and the commit is on the branch.

──────────────────────────────────────────
❯
──────────────────────────────────────────
  ? for shortcuts
"""

DRAFTED = SUMMARY.replace("❯\n", "❯ and also the docs\n")
assert DRAFTED != SUMMARY
BOXED_DRAFT = """\
⏺ Done. Anything else?

╭──────────────────────────────────────────╮
│ > half a sentence                        │
╰──────────────────────────────────────────╯
"""


def plain(text: str) -> str:
    return text


def digest(state: str, text: str) -> str:
    return hashlib.sha256((state + text).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- asks.py

def test_question_of_reads_a_permission_dialog_with_its_options():
    ask = asks.question_of(PERMISSION, "needs-you", plain)
    assert ask["options"] == [{"n": 1, "label": "Yes"},
                              {"n": 2, "label": "Yes, and don't ask again for rm commands in this folder"},
                              {"n": 3, "label": "No, and tell Claude what to do differently (esc)"}]
    # the three lines above the options: what the dialog is about
    assert ask["text"] == "rm -rf build\nRemove the old build folder\nDo you want to proceed?"
    assert ask["yes_no"] is True and ask["draft"] is False
    assert len(ask["hash"]) == 16
    # a choice with descriptions under each option keeps the options, never a description as an option
    choice = asks.question_of(CHOICE, "needs-you", plain)
    assert choice["options"] == [{"n": 1, "label": "Files"}, {"n": 2, "label": "A database"}]
    assert choice["text"] == "Which store should the cache use"
    assert choice["yes_no"] is False
    # a plan approval asks without a question mark, but its first option is a yes
    assert asks.question_of(PLAN, "needs-you", plain)["yes_no"] is True


def test_question_of_reads_options_inside_box_frames():
    ask = asks.question_of(BOXED, "needs-you", plain)
    assert [o["n"] for o in ask["options"]] == [1, 2, 3]
    assert ask["options"][1]["label"] == "Yes, allow all edits during this session"
    assert ask["text"] == "Edit file\nREADME.md\nDo you want to make this edit to README.md?"
    assert "│" not in ask["text"] and all("│" not in o["label"] for o in ask["options"])
    # labels stay short, at most nine options
    many = "Pick one\n" + "".join(f" {i}. {'word ' * 30}\n" for i in range(1, 10))
    long = asks.question_of(many, "needs-you", plain)
    assert len(long["options"]) == 9 and all(len(o["label"]) <= 80 for o in long["options"])


def test_question_of_takes_the_last_assistant_lines_of_a_waiting_tab_without_frames_or_prompt_box():
    ask = asks.question_of(WAITING, "waiting", plain)
    assert ask["text"] == ("The flag is documented now.\nREADME.md names it under Options,\nwith one example.\n"
                           "Should I also add it to the changelog?")
    assert ask["options"] == [] and ask["yes_no"] is True and ask["draft"] is False
    summary = asks.question_of(SUMMARY, "waiting", plain)
    assert summary["text"] == "Done. The three tests are green and the commit is on the branch."
    assert summary["yes_no"] is False
    # never more than four lines, the last ones
    many = "⏺ " + "\n  ".join(f"line {i}" for i in range(1, 9)) + "\n"
    assert asks.question_of(many, "waiting", plain)["text"] == "line 5\nline 6\nline 7\nline 8"


def test_question_of_cuts_long_text_at_a_word_and_hashes_the_scrubbed_text():
    secret = "s3cr3t-key"
    screen = f"⏺ The key {secret} is in the file. " + ("and more words " * 60) + "\n"
    ask = asks.question_of(screen, "waiting", lambda x: x.replace(secret, "[token]"))
    assert secret not in ask["text"] and "[token]" in ask["text"]
    assert len(ask["text"]) <= 400 and ask["text"].endswith("…")
    full = screen[2:].strip().replace(secret, "[token]")
    kept = ask["text"][:-1]
    assert full.startswith(kept) and full[len(kept)] == " "          # cut where a word ends, never inside one
    assert ask["hash"] == digest("waiting", ask["text"])
    # the same words in another state are another question
    assert asks.question_of(screen, "needs-you", lambda x: x.replace(secret, "[token]"))["hash"] != ask["hash"]


def test_question_of_marks_yes_no_and_draft():
    assert asks.question_of(DRAFTED, "waiting", plain)["draft"] is True
    assert asks.question_of(SUMMARY, "waiting", plain)["draft"] is False
    boxed = asks.question_of(BOXED_DRAFT, "waiting", plain)
    assert boxed["draft"] is True and boxed["text"] == "Done. Anything else?" and boxed["yes_no"] is True
    # an earlier prompt of yours in the history is no draft
    assert asks.question_of(WAITING, "waiting", plain)["draft"] is False


def test_question_of_returns_none_for_an_empty_or_frame_only_screen():
    assert asks.question_of("", "waiting", plain) is None
    assert asks.question_of("╭────╮\n│    │\n╰────╯\n", "waiting", plain) is None
    assert asks.question_of("────\n❯ \n────\n  ? for shortcuts\n", "waiting", plain) is None
    assert asks.question_of("\n\n", "needs-you", plain) is None


# ---------------------------------------------------------------- the tab poll reads the questions

@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


def screens(world, by_ref: dict[str, str]) -> list[str]:
    """Answers each screen read from by_ref (changed in place by a test) and returns the refs read, in order"""
    read: list[str] = []

    def answer(argv):
        ref = argv[argv.index("screen") + 1]
        read.append(ref)
        return ok({"text": by_ref.get(ref, SUMMARY)})
    world.runner.handlers["workplace.screen"] = answer
    return read


def ask_of(world, ref: str):
    return next(t for t in world.app.tabs_state()["tabs"] if t["ref"] == ref)["ask"]


def test_waiting_tabs_carry_their_question_read_once_per_state(world):
    by_ref = {"surface:7": PERMISSION, "surface:13": WAITING}
    read = screens(world, by_ref)
    world.app.asks_enabled = True
    world.app.tabs.poll()
    # needs-you first; the control tab, the filed one, the working ones and the shell are not read
    assert read == ["surface:7", "surface:13"]
    assert [o["n"] for o in ask_of(world, "surface:7")["options"]] == [1, 2, 3]
    assert ask_of(world, "surface:13")["text"].endswith("Should I also add it to the changelog?")
    for ref in ("surface:3", "surface:8", "surface:9", "surface:11", "surface:12"):
        assert ask_of(world, ref) is None
    # the same state again: nothing is read
    world.clock.advance(2)
    world.app.tabs.poll()
    assert read == ["surface:7", "surface:13"]
    # the last line of one tab changed: only that one is read again
    world.runner.handlers["workplace.status"] = lambda argv: ok(
        [dict(t, last="new words") if t["ref"] == "surface:13" else t for t in STATUS])
    world.clock.advance(2)
    world.app.tabs.poll()
    assert read == ["surface:7", "surface:13", "surface:13"]
    # a minute later every question is read again
    world.clock.advance(61)
    world.app.tabs.poll()
    assert sorted(read[3:]) == ["surface:13", "surface:7"]
    # a tab that stops waiting loses its question
    world.runner.handlers["workplace.status"] = lambda argv: ok(
        [dict(t, state="working") if t["ref"] == "surface:13" else t for t in STATUS])
    world.app.tabs.poll()
    assert ask_of(world, "surface:13") is None and "surface:13" not in world.app.tabs.asks


def test_question_reads_are_capped_per_poll_needs_you_first_and_skip_working_filed_and_control_tabs(world):
    status = [t for t in STATUS if t["ref"] in ("surface:3", "surface:8", "surface:11")]
    status += [{"name": f"w{i}", "workspace": "Ops", "ref": f"surface:{20 + i}", "ws_ref": "workspace:3",
                "state": "waiting", "id": f"TAB-{20 + i}"} for i in range(6)]
    status.append({"name": "asks", "workspace": "Ops", "ref": "surface:30", "ws_ref": "workspace:3",
                   "state": "needs-you", "id": "TAB-30"})
    world.runner.handlers["workplace.status"] = lambda argv: ok(status)
    world.app.tabs.poll()                       # the new tabs are known, their states start now
    read = screens(world, {"surface:30": PERMISSION})
    world.app.asks_enabled = True
    world.app.tabs.poll()
    assert len(read) == 4 and read[0] == "surface:30"
    assert not {"surface:3", "surface:8", "surface:11"} & set(read)
    world.clock.advance(2)
    world.app.tabs.poll()
    assert len(read) == 7 and len(set(read)) == 7    # the rest at the next poll, nothing twice


def test_question_reads_stop_at_the_time_budget(world):
    status = [{"name": f"w{i}", "workspace": "Ops", "ref": f"surface:{20 + i}", "ws_ref": "workspace:3",
               "state": "waiting", "id": f"TAB-{20 + i}"} for i in range(4)]
    world.runner.handlers["workplace.status"] = lambda argv: ok(status)
    clock = {"s": 100.0}
    world.app.tabs.monotonic = lambda: clock["s"]
    read: list[str] = []

    def slow(argv):
        read.append(argv[argv.index("screen") + 1])
        clock["s"] += 2.0                          # every read takes two seconds
        return ok({"text": SUMMARY})
    world.runner.handlers["workplace.screen"] = slow
    world.app.asks_enabled = True
    world.app.tabs.poll()
    assert len(read) == 2                           # 0 s and 2 s started, at 4 s the budget of 3 s is spent


def test_without_the_screen_cap_no_question_is_read_and_caps_are_not_asked_without_candidates(world):
    read = screens(world, {"surface:7": PERMISSION})
    world.runner.handlers["workplace.caps"] = lambda argv: ok({"caps": ["tabs", "sessions", "send", "key"]})
    world.app.driver_caps(fresh=True)
    world.app.asks_enabled = True
    world.app.tabs.poll()
    assert read == [] and ask_of(world, "surface:7") is None
    # nothing waits: the driver is not even asked what it can do
    world.runner.handlers["workplace.status"] = lambda argv: ok([dict(t, state="working") for t in STATUS])
    world.app._caps = None
    world.runner.calls.clear()
    world.app.tabs.poll()
    assert world.runner.of("workplace.caps") == []
    # switched off, nothing is read either
    world.runner.handlers["workplace.status"] = lambda argv: ok(STATUS)
    world.runner.handlers["workplace.caps"] = lambda argv: ok({"caps": ["screen", "key", "send"]})
    world.app.asks_enabled = False
    world.runner.calls.clear()
    world.app.tabs.poll()
    assert read == [] and world.runner.of("workplace.caps") == []


def test_the_question_is_scrubbed_of_the_cockpit_token(world):
    screens(world, {"surface:13": f"⏺ Open it with the key {world.app.token} please?\n"})
    world.app.asks_enabled = True
    world.app.tabs.poll()
    text = ask_of(world, "surface:13")["text"]
    assert world.app.token not in text and "[token]" in text


def test_a_question_change_does_not_rebuild_the_model(world, monkeypatch):
    by_ref = {"surface:13": WAITING}
    screens(world, by_ref)
    world.app.asks_enabled = True
    world.app.tabs.poll()
    rebuilt, sent = [], []
    monkeypatch.setattr(world.app.collector, "rebuild", lambda *a, **k: rebuilt.append(1))
    real = world.app.broadcast
    monkeypatch.setattr(world.app, "broadcast", lambda event, payload: (sent.append(event), real(event, payload)))
    by_ref["surface:13"] = SUMMARY
    world.clock.advance(61)
    world.app.tabs.poll()
    assert ask_of(world, "surface:13")["text"].startswith("Done.")
    assert "tabs" in sent and rebuilt == []


# ---------------------------------------------------------------- answering from the cockpit

def asked(world, by_ref):
    read = screens(world, by_ref)
    world.app.asks_enabled = True
    world.app.tabs.poll()
    return read


def test_tab_send_with_seen_reads_the_screen_fresh_and_refuses_a_new_question(world):
    by_ref = {"surface:13": WAITING}
    read = asked(world, by_ref)
    seen = ask_of(world, "surface:13")["hash"]
    # the cache still holds the question the page saw, the screen shows another one by now
    by_ref["surface:13"] = SUMMARY
    world.runner.calls.clear()
    with pytest.raises(ActionError) as err:
        world.act("tab_send", tab_ref="surface:13", text="yes please", seen=seen)
    assert (err.value.status, err.value.code) == (409, "tab_moved")
    assert world.runner.of("workplace.send") == []
    assert read[-1] == "surface:13" and len(world.runner.of("workplace.screen")) == 1   # read fresh, past the cache
    # the question the page saw is still on screen: it goes out
    by_ref["surface:13"] = WAITING
    world.act("tab_send", tab_ref="surface:13", text="yes please", seen=seen)
    assert world.runner.of("workplace.send") == [W(world, "send", "surface:13", "--", "yes please")]
    # a hash that is no hash is refused before anything
    with pytest.raises(ActionError) as err:
        world.act("tab_send", tab_ref="surface:13", text="x", seen="nothex")
    assert err.value.code == "invalid_argument"


def test_tab_send_refuses_when_a_draft_is_typed(world):
    asked(world, {"surface:13": DRAFTED})
    seen = ask_of(world, "surface:13")["hash"]
    world.runner.calls.clear()
    with pytest.raises(ActionError) as err:
        world.act("tab_send", tab_ref="surface:13", text="go", seen=seen)
    assert (err.value.status, err.value.code) == (409, "tab_draft")
    assert world.runner.of("workplace.send") == []
    with pytest.raises(ActionError) as err:
        world.act("tab_go_on", tab_ref="surface:13", seen=seen)
    assert err.value.code == "tab_draft" and world.runner.of("workplace.send") == []


def test_a_reply_with_a_different_tab_name_is_refused(world):
    world.runner.calls.clear()
    with pytest.raises(ActionError) as err:
        world.act("tab_send", tab_ref="surface:13", text="go", name="another tab")
    assert (err.value.status, err.value.code) == (409, "tab_moved")
    assert world.runner.of("workplace.status") and world.runner.of("workplace.send") == []
    for verb in ("tab_yes", "tab_go_on"):
        with pytest.raises(ActionError) as err:
            world.act(verb, tab_ref="surface:7" if verb == "tab_yes" else "surface:13", name="another tab")
        assert err.value.code == "tab_moved"
    assert writes(world) == []
    world.act("tab_send", tab_ref="surface:13", text="go", name="waiting plain")
    assert writes(world) == [W(world, "send", "surface:13", "--", "go")]


def test_tab_send_with_expect_repolls_and_sends_when_unchanged(world):
    world.runner.calls.clear()
    world.act("tab_send", tab_ref="surface:13", text="go", expect="waiting")
    assert world.runner.of("workplace.status")
    assert world.runner.of("workplace.screen") == []          # no seen, no screen read
    assert writes(world) == [W(world, "send", "surface:13", "--", "go")]
    world.runner.handlers["workplace.status"] = lambda argv: ok(
        [dict(t, state="working") if t["ref"] == "surface:13" else t for t in STATUS])
    world.runner.calls.clear()
    with pytest.raises(ActionError) as err:
        world.act("tab_send", tab_ref="surface:13", text="go", expect="waiting")
    assert (err.value.status, err.value.code) == (409, "tab_moved")
    assert writes(world) == []
    with pytest.raises(ActionError) as err:
        world.act("tab_send", tab_ref="surface:13", text="go", expect="shell")
    assert err.value.code == "invalid_argument"


def test_tab_option_sends_the_digit_of_the_option(world):
    asked(world, {"surface:7": PERMISSION})
    seen = ask_of(world, "surface:7")["hash"]
    world.runner.calls.clear()
    res = world.act("tab_option", tab_ref="surface:7", n=2, seen=seen, name="demo-task")
    assert writes(world) == [W(world, "key", "surface:7", "2")]
    assert "Yes, and don't ask again" in res["note"]
    world.runner.calls.clear()
    with pytest.raises(ActionError) as err:
        world.act("tab_option", tab_ref="surface:7", n=5, seen=seen)
    assert (err.value.status, err.value.code) == (409, "not_applicable")
    for bad in ({"n": 0, "seen": seen}, {"n": "2", "seen": seen}, {"n": True, "seen": seen}, {"n": 2}):
        with pytest.raises(ActionError) as err:
            world.act("tab_option", tab_ref="surface:7", **bad)
        assert err.value.code == "invalid_argument"
    assert writes(world) == []
    # without the key right of the driver there is no option to press
    world.runner.handlers["workplace.caps"] = lambda argv: ok({"caps": ["tabs", "send", "screen"]})
    world.app.driver_caps(fresh=True)
    with pytest.raises(ActionError) as err:
        world.act("tab_option", tab_ref="surface:7", n=1, seen=seen)
    assert (err.value.status, err.value.code) == (503, "driver_cannot")


def test_tab_yes_keeps_the_repoll_guard_and_checks_seen(world):
    by_ref = {"surface:7": PERMISSION}
    asked(world, by_ref)
    seen = ask_of(world, "surface:7")["hash"]
    world.runner.calls.clear()
    world.act("tab_yes", tab_ref="surface:7", seen=seen, name="demo-task")
    assert writes(world) == [W(world, "key", "surface:7", "1")]
    # another dialog by now: nothing is pressed
    by_ref["surface:7"] = BOXED
    world.runner.calls.clear()
    with pytest.raises(ActionError) as err:
        world.act("tab_no", tab_ref="surface:7", seen=seen)
    assert (err.value.status, err.value.code) == (409, "tab_moved")
    assert writes(world) == []
    # without seen the old guard stands: a tab that moved on gets nothing
    world.runner.handlers["workplace.status"] = lambda argv: ok(
        [dict(t, state="working") if t["ref"] == "surface:7" else t for t in STATUS])
    res = world.act("tab_yes", tab_ref="surface:7")
    assert writes(world) == [] and "no longer asking, nothing pressed" in res["note"]


def test_question_of_scrubs_an_option_label_before_it_is_cut():
    # the key straddles the 80 characters of a label: scrubbed after the cut, a piece of it would stay
    secret = "s3cr3t-key-0123456789abcdef"
    label = "path/" * 14 + secret + " and the rest of the option"
    assert len("path/" * 14) < 80 < len("path/" * 14) + len(secret)
    screen = f"Use the key?\n ❯ 1. {label}\n   2. No\n"
    ask = asks.question_of(screen, "needs-you", lambda x: x.replace(secret, "[token]"))
    first = ask["options"][0]["label"]
    assert len(first) <= 80
    assert not any(secret[:k] in first for k in range(6, len(secret) + 1))


def test_a_typed_answer_never_goes_into_a_dialog(world):
    # a dialog takes its options (tab_option), never free text: a "2" typed there would pick an option
    # without the option guard
    asked(world, {"surface:7": PERMISSION})
    seen = ask_of(world, "surface:7")["hash"]
    world.runner.calls.clear()
    for extra in ({"seen": seen}, {"expect": "needs-you"}, {"name": "demo-task"}):
        with pytest.raises(ActionError) as err:
            world.act("tab_send", tab_ref="surface:7", text="2", **extra)
        assert (err.value.status, err.value.code) == (409, "not_applicable")
    assert writes(world) == []
