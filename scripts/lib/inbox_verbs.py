# SPDX-License-Identifier: MIT
"""Which inbox verbs end an item, in one place.

Two callers read it and must never disagree about when an item is over: `scripts/inbox.py` (the state of
an item) and the cockpit's return channel (`bridge_cockpit/returns.py`: whether a tab has nothing left to
do and whether a start is done). A verb that ends an item is added here, and both follow.
"""
from __future__ import annotations

#: verb -> the state it leaves the item in. A `reopen` after any of them takes the end back.
TERMINAL = {"close": "done", "executed": "done", "reject": "dropped", "drop": "dropped"}
