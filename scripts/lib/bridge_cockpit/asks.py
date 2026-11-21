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
# a rule may carry the session's name (`claude -n <name>`): `──── docs-update ─`
RULE = re.compile(f"^\\s*[{FRAME}]+(?: [^{FRAME}]+ [{FRAME}]+)?\\s*$")
OPTION = re.compile(r"^\s*[>❯]?\s*(\d)\.\s+(.+)$")
PROMPT = re.compile(r"^[>❯](?:\s+(.*))?$")
TOOL_CALL = re.compile(r"^⏺\s*[A-Za-z][\w.:-]*\(")
STATUS = re.compile(r"^(?:[✻✶✳✢✽✦⏵⏸⏹·*]\s|\?\s+for shortcuts)|esc to interrupt|shift\+tab to cycle|auto-compact",
                    re.IGNORECASE)
YES = re.compile(r"^(yes|ja)\b", re.IGNORECASE)
# Claude Code's own lines around the agent's words, never part of them: a turn's status line (`✻ Baked for 3s`), the
# session recap (`※ recap: ...`, wrapped over the lines under it), and the hints it right-aligns above the input line
TURN_CHROME = re.compile(r"^(?:[✻✶✳✢✽✦]\s|※)")
RECAP = re.compile(r"^※")
HINT = re.compile(r"/clear to save|/restart to apply|update installed|turn off recaps|\?\s+for shortcuts", re.IGNORECASE)
RIGHT_ALIGNED = 24  # leading spaces of a line Claude Code puts at the right edge
WORD = re.compile(r"\w")


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


def _chrome(raw: str, clean: str) -> bool:
    """A line of Claude Code itself: a turn's status, the recap, a hint, a line at the right edge"""
    indent = len(raw) - len(raw.lstrip(" "))
    return bool(TURN_CHROME.match(clean) or HINT.search(clean) or (clean and indent >= RIGHT_ALIGNED))


def _meaningful(line: str) -> bool:
    return bool(line) and not STATUS.search(line) and not line.startswith("⎿") and not TOOL_CALL.match(line)


def _said(raw: list[str], clean: list[str], end: int) -> list[str]:
    """The last lines of the agent's last block of words before `end`: the block starts at its `⏺` line and ends at
    the first line of Claude Code's own (a turn's status, the recap, a hint, the prompt) or a tool call;
    blank lines, tool output and status lines inside it are left out. Without a block of words, the last such lines
    of the screen, never a line of Claude Code's own nor the recap's wrapped lines."""
    start = None
    for i in range(end - 1, -1, -1):
        if clean[i].startswith("⏺") and not TOOL_CALL.match(clean[i]):
            start = i
            break
    out: list[str] = []
    if start is not None:
        for i in range(start, end):
            line = clean[i]
            if PROMPT.match(line) or TOOL_CALL.match(line) or _chrome(raw[i], line):
                break
            line = line[1:].strip() if line.startswith("⏺") else line
            if _meaningful(line):
                out.append(line)
    else:
        recap = False
        for i in range(end):
            line = clean[i]
            if RECAP.match(line):
                recap = True
            elif not line or _chrome(raw[i], line) or PROMPT.match(line):
                recap = False
            if recap or _chrome(raw[i], line) or PROMPT.match(line) or not _meaningful(line):
                continue
            out.append(line)
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
    """The question a tab in `state` asks on this screen: {text, options, hash, yes_no, draft, suggestion}, or
    None when nothing readable is left. `scrub` takes out what must never reach the page (the cockpit's key).

    `draft`: the input line holds text, so typed words would be appended to it. `suggestion`: that text as an
    answer the tab holds ready (None without a word in it). The screen cannot tell Claude Code's grey prompt
    suggestion from typed text; either goes out with Enter alone (tab_accept). It is no part of the hash."""
    raw = [line.rstrip() for line in str(text or "").splitlines()]
    clean = [_clean(line) for line in raw]
    last_said = max((i for i, line in enumerate(clean) if line.startswith("⏺")), default=-1)
    box = _prompt_box(raw, clean, last_said)
    draft, suggestion = False, None
    if box is not None:
        typed = (PROMPT.match(clean[box]).group(1) or "").strip()
        draft = bool(typed)
        if WORD.search(typed):
            suggestion = _cap(scrub(typed).strip())
    end = box if box is not None else len(clean)
    if box is not None and box > 0 and RULE.match(raw[box - 1]):
        end = box - 1                      # the rule above the prompt, and a session name on it, is no word said
    options: list[dict] = []
    dialog = _dialog(clean[:end], scrub) if state == "needs-you" else None
    if dialog:
        options, lines = dialog
    else:
        lines = _said(raw, clean, end)
    words = scrub("\n".join(lines)).strip()
    if not words and not options:
        return None
    words = _cap(words)
    yes_no = words.endswith("?") or bool(options and YES.match(options[0]["label"]))
    # the options belong to the question: the same words over other options are another question
    material = state + words + "".join(f"\n{o['n']}. {o['label']}" for o in options)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return {"text": words, "options": options, "hash": digest, "yes_no": yes_no, "draft": draft,
            "suggestion": suggestion}


def draft_of(text: str) -> bool:
    """Whether the prompt box at the bottom of this screen holds typed text: words sent now would be
    appended to it. Also for a tab without a readable question (a filed one, a screen with no words)."""
    raw = [line.rstrip() for line in str(text or "").splitlines()]
    clean = [_clean(line) for line in raw]
    last_said = max((i for i, line in enumerate(clean) if line.startswith("⏺")), default=-1)
    box = _prompt_box(raw, clean, last_said)
    if box is None:
        return False
    typed = PROMPT.match(clean[box]).group(1)
    return bool(typed and typed.strip())
