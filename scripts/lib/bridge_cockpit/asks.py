# SPDX-License-Identifier: MIT
"""What a waiting tab asks, read off its screen: pure functions, no I/O.

The tab poll (tabs.py) hands the last lines of a waiting tab's terminal here and gets back the question
the page shows in "Waiting for you": for a tab that needs you, the last permission or choice dialog with
its numbered options; for a tab that waits, the last lines of what the agent said. The hash names the
question, so an answer from the page reaches only the question it was given for (actions.guard_fresh
reads the screen again and compares). A small Python twin of the line classes of screenLines in logic.js.
"""
from __future__ import annotations

import hashlib
import re
from typing import Callable

TEXT_MAX = 400
LABEL_MAX = 80
OPTIONS_MAX = 9
ABOVE = 3          # lines of a dialog above its options
LAST_LINES = 4     # lines of what the agent said
FRAME = "╭╮╰╯│─━═┌┐└┘├┤"
EDGES = re.compile(f"^[\\s{FRAME}]+|[\\s{FRAME}]+$")
RULE = re.compile(f"^\\s*[{FRAME}]+\\s*$")
OPTION = re.compile(r"^\s*[>❯]?\s*(\d)\.\s+(.+)$")
PROMPT = re.compile(r"^[>❯](?:\s+(.*))?$")
TOOL_CALL = re.compile(r"^⏺\s*[A-Za-z][\w.:-]*\(")
STATUS = re.compile(r"^(?:[✻✶✳✢✽✦⏵⏸⏹·*]\s|\?\s+for shortcuts)|esc to interrupt|shift\+tab to cycle|auto-compact",
                    re.IGNORECASE)
YES = re.compile(r"^(yes|ja)\b", re.IGNORECASE)


def _clean(line: str) -> str:
    """A line without the box frame at its edges: `│ ❯ 1. Yes │` reads `❯ 1. Yes`"""
    return EDGES.sub("", line)


def _cap(text: str) -> str:
    """At most TEXT_MAX characters, cut where a word ends, with … when cut"""
    if len(text) <= TEXT_MAX:
        return text
    cut = text[:TEXT_MAX - 1]
    space = max(cut.rfind(" "), cut.rfind("\n"))
    if space >= TEXT_MAX // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _label(text: str) -> str:
    line = re.sub(r"\s+", " ", text).strip()
    if len(line) <= LABEL_MAX:
        return line
    cut = line[:LABEL_MAX - 1]
    space = cut.rfind(" ")
    if space >= LABEL_MAX * 2 // 3:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def _prompt_box(raw: list[str], clean: list[str], after: int) -> int | None:
    """The input line at the bottom: a prompt glyph inside a box or right under a rule, after the agent's
    last words. None when the screen shows none (a dialog, or a tab at work)."""
    for i in range(len(clean) - 1, after, -1):
        if not PROMPT.match(clean[i]) or OPTION.match(clean[i]):
            continue
        boxed = raw[i].lstrip().startswith("│")
        under_rule = i > 0 and bool(RULE.match(raw[i - 1]))
        if boxed or under_rule:
            return i
    return None


def _meaningful(line: str) -> bool:
    return bool(line) and not STATUS.search(line) and not line.startswith("⎿") and not TOOL_CALL.match(line)


def _said(clean: list[str], end: int) -> list[str]:
    """The last lines of the agent's last block of words before `end`: no prompt box, frames, tool calls,
    tool output, status lines or blank lines. Without a block of words, the last such lines of the screen."""
    start = None
    for i in range(end - 1, -1, -1):
        if clean[i].startswith("⏺") and not TOOL_CALL.match(clean[i]):
            start = i
            break
    out: list[str] = []
    if start is not None:
        for line in clean[start:end]:
            if PROMPT.match(line) or TOOL_CALL.match(line):
                break
            line = line[1:].strip() if line.startswith("⏺") else line
            if _meaningful(line):
                out.append(line)
    else:
        out = [line for line in clean[:end] if _meaningful(line) and not PROMPT.match(line)]
    return out[-LAST_LINES:]


def _dialog(clean: list[str], scrub: Callable[[str], str]) -> tuple[list[dict], list[str]] | None:
    """The last block of numbered options and up to ABOVE lines above it; None without one"""
    last = next((i for i in range(len(clean) - 1, -1, -1) if OPTION.match(clean[i])), None)
    if last is None:
        return None
    found = OPTION.match(clean[last])
    options = {int(found.group(1)): found.group(2)}
    expect = int(found.group(1)) - 1
    top = last
    between = 0
    i = last - 1
    while i >= 0 and expect >= 1:
        hit = OPTION.match(clean[i])
        if hit and int(hit.group(1)) == expect:
            options[expect] = hit.group(2)
            expect -= 1
            top = i
            between = 0
        elif hit or between >= 2:
            break
        elif clean[i]:
            between += 1          # a description under an option
        i -= 1
    above = [line[1:].strip() if line.startswith("⏺") else line for line in clean[:top] if _meaningful(line)][-ABOVE:]
    # scrubbed before the cut: a key cut in half would no longer be found by scrub
    picked = [{"n": n, "label": _label(scrub(options[n]))} for n in sorted(options)][:OPTIONS_MAX]
    return picked, above


def question_of(text: str, state: str, scrub: Callable[[str], str]) -> dict | None:
    """The question a tab in `state` asks on this screen: {text, options, hash, yes_no, draft}, or None
    when nothing readable is left. `scrub` takes out what must never reach the page (the cockpit's key)."""
    raw = [line.rstrip() for line in str(text or "").splitlines()]
    clean = [_clean(line) for line in raw]
    last_said = max((i for i, line in enumerate(clean) if line.startswith("⏺")), default=-1)
    box = _prompt_box(raw, clean, last_said)
    draft = False
    if box is not None:
        typed = PROMPT.match(clean[box]).group(1)
        draft = bool(typed and typed.strip())
    end = box if box is not None else len(clean)
    options: list[dict] = []
    dialog = _dialog(clean[:end], scrub) if state == "needs-you" else None
    if dialog:
        options, lines = dialog
    else:
        lines = _said(clean, end)
    words = scrub("\n".join(lines)).strip()
    if not words and not options:
        return None
    words = _cap(words)
    yes_no = words.endswith("?") or bool(options and YES.match(options[0]["label"]))
    # the options belong to the question: the same words over other options are another question
    material = state + words + "".join(f"\n{o['n']}. {o['label']}" for o in options)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return {"text": words, "options": options, "hash": digest, "yes_no": yes_no, "draft": draft}
