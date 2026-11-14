"""Shared test setup for the runtime suite."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _tasks_in_memory(monkeypatch):
    """Apps built from a checked-in instance (``_template``) must not write a task
    database into the repo. A test that needs the durable store builds its own
    ``SqliteTaskStore`` under ``tmp_path``."""
    monkeypatch.setenv("AGENT_TASK_STORE", "memory")
