#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The confirmation prompts of scripts/overlay.py insist on an answer.

Origin: on 2026-10-31 a consumer answered "a" at the behavioural gate of a
skill folder. prompt_yes() read every answer but y/yes as "no", so the folder
was WITHHELD without a word, and the next question (overwrite a user-owned
file?) came up as if nothing had happened. These tests pin the repaired
contract:

  1. an unrecognised answer repeats the question instead of counting as no
  2. "a" means yes, and yes to every remaining batch question of this run
  3. questions that delete or overwrite the consumer's own file are asked one
     by one even after "a"
  4. an empty line (and end of input, which prompt_line maps to it) is no, so
     a non-tty never loops
  5. the [k]eep/[u]pstream/[s]kip choice re-asks on an unknown letter

Run: python3 -m pytest scripts/tests/test_overlay_prompts.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("overlay", REPO / "scripts" / "overlay.py")
assert _spec and _spec.loader, "cannot load scripts/overlay.py"
overlay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(overlay)


class Script:
    """Feeds scripted answers to prompt_line and records every question."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, msg: str) -> str:
        self.asked.append(msg)
        if not self.answers:
            return ""          # end of input: prompt_line returns "" on EOF
        return self.answers.pop(0)


@pytest.fixture(autouse=True)
def _fresh_state():
    overlay.reset_prompts()
    yield
    overlay.reset_prompts()


def test_unrecognised_answer_repeats_the_question(monkeypatch, capsys):
    sc = Script(["x", "maybe", "y"])
    monkeypatch.setattr(overlay, "prompt_line", sc)
    assert overlay.prompt_yes("Materialize skills/x/?") is True
    assert len(sc.asked) == 3
    out = capsys.readouterr().out
    assert "unrecognised answer 'x'" in out
    assert "unrecognised answer 'maybe'" in out


def test_plain_no_and_empty_line_are_no(monkeypatch):
    sc = Script(["n", ""])
    monkeypatch.setattr(overlay, "prompt_line", sc)
    assert overlay.prompt_yes("q1?") is False
    assert overlay.prompt_yes("q2?") is False
    assert len(sc.asked) == 2


def test_end_of_input_never_loops(monkeypatch):
    sc = Script([])          # every call returns "", the EOF shape
    monkeypatch.setattr(overlay, "prompt_line", sc)
    assert overlay.prompt_yes("q?") is False
    assert len(sc.asked) == 1


def test_a_is_yes_and_covers_the_remaining_batch_questions(monkeypatch, capsys):
    sc = Script(["a"])
    monkeypatch.setattr(overlay, "prompt_line", sc)
    assert overlay.prompt_yes("skills/one/?") is True
    assert overlay.prompt_yes("skills/two/?") is True
    assert overlay.prompt_yes("skills/three/?") is True
    assert len(sc.asked) == 1, "after 'a' no further batch question reaches the tty"
    out = capsys.readouterr().out
    assert out.count("(yes to all)") == 2


def test_a_never_covers_single_questions(monkeypatch, capsys):
    sc = Script(["a", "a", "n"])
    monkeypatch.setattr(overlay, "prompt_line", sc)
    assert overlay.prompt_yes("skills/one/?") is True
    # a delete / overwrite question is asked one by one; "a" is not an answer
    # there, so it repeats, and "n" declines.
    assert overlay.prompt_yes("x exists (user-owned). Overwrite?", batch=False) is False
    assert len(sc.asked) == 3
    assert "[y/N] " in sc.asked[1] and "[y/N/a]" not in sc.asked[1]
    assert "asked one by one" in capsys.readouterr().out


def test_yes_all_resets_per_run(monkeypatch):
    sc = Script(["a", "n"])
    monkeypatch.setattr(overlay, "prompt_line", sc)
    assert overlay.prompt_yes("q1?") is True
    overlay.reset_prompts()
    assert overlay.prompt_yes("q2?") is False
    assert len(sc.asked) == 2


def test_choice_reasks_on_unknown_letter_and_defaults_on_empty(monkeypatch, capsys):
    sc = Script(["q", "u"])
    monkeypatch.setattr(overlay, "prompt_line", sc)
    assert overlay.prompt_choice("    choose: ", "kus", "s") == "u"
    assert len(sc.asked) == 2
    assert "unrecognised answer 'q'" in capsys.readouterr().out
    sc2 = Script([""])
    monkeypatch.setattr(overlay, "prompt_line", sc2)
    assert overlay.prompt_choice("    choose: ", "kus", "s") == "s"


def test_main_resets_yes_all_before_a_run(monkeypatch):
    overlay._YES_ALL = True
    monkeypatch.setattr(overlay, "resolve_repo_root", lambda args: "/nonexistent/x")
    rc = overlay.main(["status"])
    assert rc == 2            # cannot enter repo root: the reset ran before it
    assert overlay._YES_ALL is False
