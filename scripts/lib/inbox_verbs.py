# SPDX-License-Identifier: MIT
"""Which inbox verbs end an item, and which art a kind is, in one place.

Two callers read it and must never disagree about when an item is over: `scripts/inbox.py` (the state of
an item) and the cockpit's return channel (`bridge_cockpit/returns.py`: whether a tab has nothing left to
do and whether a start is done). A verb that ends an item is added here, and both follow.

The art is what a person sees an item as, derived from its kind and never stored: an `ask` needs their
yes, word or click, a `report` tells how something stands, an `idea` was mentioned and nothing came of
it yet. The inbox (`list --art`), the briefing and the cockpit ("waits for you" counts the asks) read it
here, so a kind added later lands in one art everywhere.
"""
from __future__ import annotations

#: verb -> the state it leaves the item in. A `reopen` after any of them takes the end back.
TERMINAL = {"close": "done", "executed": "done", "reject": "dropped", "drop": "dropped"}

#: kind -> art. A kind this table does not know is an ask: a person sees it rather than missing it.
ARTS = ("ask", "report", "idea")
ART_OF_KIND = {"decision": "ask", "question": "ask", "draft": "ask",
               "finding": "report", "result": "report", "idea": "idea"}


def art_of_kind(kind) -> str:
    """The art of an inbox kind; an unknown or missing kind is an ask."""
    return ART_OF_KIND.get(str(kind or ""), "ask")
