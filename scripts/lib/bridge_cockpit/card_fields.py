# SPDX-License-Identifier: MIT
"""The shape of a card, and of the `brief` it is written from, in one place (docs/bridge-cockpit.md).

A card is how the cockpit shows any item (a task, a stream, an inbox item, a tracker row) with the same
parts in the same places. `CARD_FIELDS` is its wire shape, in order; `next`, `state`, `story` and `progress`
are mappings with the fields named beside it. Nothing here builds a card: this module only says what one
holds, so the server that fills it and the page that draws it agree.

A brief is what was written about one item: a `goal` (one sentence), an optional user `story` {as, want,
so_that} and a few `acceptance` criteria (testable outcomes, none for a stream), plus where it comes from:
`by` (the model id exactly as the run's modelUsage reports it, never an alias such as `haiku`), `at` (the
day), `basis` (`brief_basis` of the text it was written against) and `edited` (true once a person changed
it). It has one shape in two places: the `brief:` block of a STATUS.md (work/templates/_schema.status.yaml,
`$defs/Brief`) and the `describe` event of an inbox item (work/templates/_schema.inbox-item.yaml,
`$defs/brief`, the same definition). `BRIEF_LIMITS` are the limits both schemas declare.

`validate_brief(obj)` is the one gate every writer passes. It returns (clean, errors): `clean` is what may be
stored or shown, `errors` says everything that was wrong. A text over its limit or holding a dash as
punctuation (U+2012 to U+2015, em and en dash among them) or a control or format character (Unicode Cc or
Cf, a line break included, and U+2028, U+2029: YAML reads some as a line break and refuses others, so the text
would not read back as written) is an error and left out of `clean`, never cut or rewritten, so a wrong text is never shown as if it were right; a list of more than five criteria keeps the
first five and says so. Without a usable goal there is no brief and `clean` is None.

`brief_basis(text)` is the sha256 prefix (16 hex characters) of a STATUS.md with its `brief:` block taken out
of the front matter (and one blank line directly before it), so writing the brief does not change it and any
other change does: a brief whose basis differs from the file's is stale. A writer adds at most that one
separator line; a second one is a change to the file.

The card's `next` {what, who, due} is built from a task row's flat `next`, `next_who` and `next_due`
(workplace.py tasks, docs/workplace.md): `next` stays the text it always was for the callers that read it.

Pure: no I/O, nothing raises on bad input.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from typing import Any

CARD_FIELDS = ("kind", "subkind", "title", "summary", "goal", "story", "acceptance", "next", "state",
               "owner", "priority", "due", "area", "updated", "source", "links", "progress", "written", "gaps")
NEXT_FIELDS = ("what", "who", "due", "from", "since")
STATE_FIELDS = ("word", "blocked_by", "since")
PROGRESS_FIELDS = ("done", "total")
STORY_FIELDS = ("as", "want", "so_that")
BRIEF_FIELDS = ("goal", "story", "acceptance", "by", "at", "basis", "edited")
#: characters; `acceptance_items` is the most criteria a brief keeps (a stream has none)
BRIEF_LIMITS = {"goal": 140, "story": 80, "acceptance_items": 5, "acceptance_len": 120}

_DASH_RE = re.compile("[‒-―]")
# matched with fullmatch: `$` would also take a value that ends in a newline
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BASIS_RE = re.compile(r"[0-9a-f]{16}")
# a model id names a version, so it holds a digit; an alias (haiku, opus[1m]) does not
_MODEL_RE = re.compile(r"(?=.*\d)[A-Za-z0-9][A-Za-z0-9._:/@-]*")


def _text(value: Any, name: str, limit: int, errors: list) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{name}: not a text")
        return None
    text = value.strip()
    if len(text) > limit:
        errors.append(f"{name}: {len(text)} characters, at most {limit}")
        return None
    if _DASH_RE.search(text):
        errors.append(f"{name}: a dash as punctuation, use a comma, colon or parentheses")
        return None
    if any(c in "\u2028\u2029" or unicodedata.category(c) in ("Cc", "Cf") for c in text):
        # YAML reads some of them as a line break and refuses others: the brief would not read back as written
        errors.append(f"{name}: a control or format character (a line break included), one plain line of text")
        return None
    return text


def validate_brief(obj: Any) -> tuple[dict | None, list[str]]:
    """(clean, errors) for a brief: see the module doc. `clean` is a new dict, None without a usable goal."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return None, ["brief: not a mapping"]
    clean: dict = {}
    for key in obj:
        if key not in BRIEF_FIELDS:
            errors.append(f"{key}: not a brief field ({', '.join(BRIEF_FIELDS)})")
    if "goal" not in obj:
        errors.append("goal: missing")
    else:
        goal = _text(obj["goal"], "goal", BRIEF_LIMITS["goal"], errors)
        if goal is not None:
            clean["goal"] = goal
    if "story" in obj:
        story = obj["story"]
        if not isinstance(story, dict):
            errors.append("story: not a mapping")
        else:
            parts, ok = {}, True
            for key in story:
                if key not in STORY_FIELDS:
                    errors.append(f"story.{key}: not a story part ({', '.join(STORY_FIELDS)})")
            for part in STORY_FIELDS:
                if part not in story:
                    errors.append(f"story.{part}: missing, a story has as, want and so_that")
                    ok = False
                    continue
                value = _text(story[part], f"story.{part}", BRIEF_LIMITS["story"], errors)
                ok = ok and value is not None
                parts[part] = value
            if ok:
                clean["story"] = parts
    if "acceptance" in obj:
        items = obj["acceptance"]
        if not isinstance(items, list):
            errors.append("acceptance: not a list")
        else:
            most = BRIEF_LIMITS["acceptance_items"]
            if len(items) > most:
                errors.append(f"acceptance: {len(items)} criteria, kept the first {most}")
            kept = [_text(x, f"acceptance[{n}]", BRIEF_LIMITS["acceptance_len"], errors)
                    for n, x in enumerate(items[:most])]
            clean["acceptance"] = [x for x in kept if x is not None]
    if "by" in obj:
        by = obj["by"]
        if isinstance(by, str) and _MODEL_RE.fullmatch(by.strip()):
            clean["by"] = by.strip()
        else:
            errors.append(f"by: {by!r} is no model id (as modelUsage reports it, never an alias)")
    if "at" in obj:
        at = obj["at"]
        if isinstance(at, dt.datetime):
            at = at.date()
        if isinstance(at, dt.date):
            clean["at"] = at.isoformat()
        elif isinstance(at, str) and _DATE_RE.fullmatch(at.strip()):
            try:
                clean["at"] = dt.date.fromisoformat(at.strip()).isoformat()
            except ValueError:
                errors.append(f"at: {at!r} is no date")
        else:
            errors.append(f"at: {at!r} is no date (YYYY-MM-DD)")
    if "basis" in obj:
        if isinstance(obj["basis"], str) and _BASIS_RE.fullmatch(obj["basis"]):
            clean["basis"] = obj["basis"]
        else:
            errors.append("basis: not 16 lowercase hex characters")
    if "edited" in obj:
        if isinstance(obj["edited"], bool):
            clean["edited"] = obj["edited"]
        else:
            errors.append("edited: not true or false")
    if "goal" not in clean:
        return None, errors
    return {k: clean[k] for k in BRIEF_FIELDS if k in clean}, errors


_FENCE_RE = re.compile(r"^---\s*$")


def strip_brief(text: str) -> str:
    """The text with the `brief:` block of its front matter taken out (line endings made `\\n`), and with it
    one blank line directly before it, so a writer may append the block after a separator line; a text
    without front matter, or a front matter without a brief, comes back as it was."""
    lines = text.replace("\r\n", "\n").split("\n")
    fences = [i for i, line in enumerate(lines) if _FENCE_RE.match(line)][:2]
    if len(fences) < 2:
        return "\n".join(lines)
    start, end = fences
    out, i = lines[:start + 1], start + 1
    while i < end:
        if re.match(r"^brief\s*:", lines[i]):
            if len(out) > start + 1 and not out[-1].strip():
                out.pop()  # the one separator line a writer may put before the block
            i += 1
            block_end = i
            # the block runs on over indented and blank lines; trailing blank lines belong to what follows
            while i < end and (lines[i][:1] in (" ", "\t") or not lines[i].strip()):
                i += 1
                if lines[i - 1].strip():
                    block_end = i
            i = block_end
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out + lines[end:])


def brief_basis(text: str) -> str:
    """The sha256 prefix (16 hex characters) of `text` without its brief block (see the module doc)."""
    return hashlib.sha256(strip_brief(text).encode("utf-8")).hexdigest()[:16]
