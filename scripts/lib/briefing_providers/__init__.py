# SPDX-License-Identifier: MIT
"""Tracker adapters for scripts/briefing.py, one module per provider.

Contract of a module: `collect(section, ctx) -> list[dict]`, items in the
normalized schema of trackers/README.md (id, title, state, raw_state, type,
assignee, assigned_to_me, url, changed_at, project, tracker, labels, priority,
category). `ctx.run(argv, timeout=)` runs a CLI and returns stdout,
`ctx.http(method, url, headers, body)` returns parsed JSON, `ctx.secret(ref)`
returns the value behind a reference URI, `ctx.account(section)` reads the
section's `account_ref` file. Each raises `SourceError` (from briefing) on
failure; the engine turns it into an error line, never an abort.

Every adapter is tested against recorded answers in
scripts/tests/fixtures/briefing/<provider>/. The prose playbooks in
trackers/*.md stay the documentation of each system.
"""
from __future__ import annotations

import importlib

MODULES = {
    "github": "github",
    "github-board": "github_board",
    "github-work": "github_work",
    "gitlab": "gitlab",
    "ado": "ado",
    "jira": "jira",
    "linear": "linear",
}


def get(name):
    if name not in MODULES:
        raise KeyError(f"unknown tracker provider {name!r}; known: {', '.join(MODULES)}")
    return importlib.import_module(f"{__name__}.{MODULES[name]}")


def source_error(message: str) -> Exception:
    """The engine's SourceError, without a circular import at module load."""
    import sys
    engine = sys.modules.get("briefing")
    cls = getattr(engine, "SourceError", RuntimeError)
    return cls(message)


def load_json(text: str, what: str):
    import json
    try:
        return json.loads(text)
    except ValueError:
        raise source_error(f"{what}: output is not JSON") from None
