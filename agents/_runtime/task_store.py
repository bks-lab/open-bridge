"""Tasks that survive a restart.

The a2a-sdk ``InMemoryTaskStore`` loses every task when the process stops, so a
caller that asks for its task afterwards gets "Task not found", and an answer that
waits for its owner's approval is gone. ``SqliteTaskStore`` keeps the in-memory
store as the working copy and writes every save and delete through to one SQLite
file, which it reads back at start.

The same file keeps a journal of answers that wait for their owner (``pending``).
The executor writes an entry before it asks the owner and removes it once the task
ended; at start the executor asks the owner again for every entry still there
(see ``ClaudeAgentExecutor.resume_pending``).

Declared in ``agent.yaml``::

    task_store:
      path: state/tasks.sqlite     # relative to the instance folder; "memory" turns it off
      keep_days: 30                # finished tasks older than this are dropped at start

Standard library only (``sqlite3``); a task is stored as its protobuf JSON.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from a2a.server.context import ServerCallContext
from a2a.server.owner_resolver import OwnerResolver, resolve_user_scope
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import Task, TaskState
from google.protobuf.json_format import MessageToJson, Parse

logger = logging.getLogger(__name__)

FINAL_STATES = frozenset({
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    owner TEXT NOT NULL,
    id TEXT NOT NULL,
    task TEXT NOT NULL,
    final INTEGER NOT NULL DEFAULT 0,
    updated REAL NOT NULL,
    PRIMARY KEY (owner, id)
);
CREATE TABLE IF NOT EXISTS pending (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    request TEXT NOT NULL,
    created REAL NOT NULL
);
"""


class SqliteTaskStore(InMemoryTaskStore):
    """``InMemoryTaskStore`` that writes through to SQLite and reloads at start."""

    def __init__(
        self,
        path: str | Path,
        *,
        keep_days: float = 30.0,
        owner_resolver: OwnerResolver = resolve_user_scope,
    ) -> None:
        super().__init__(owner_resolver=owner_resolver)
        self._owner_of = owner_resolver
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._load(keep_days)

    def _load(self, keep_days: float) -> None:
        cutoff = time.time() - keep_days * 86400
        with self._lock:
            self._db.execute("DELETE FROM tasks WHERE final = 1 AND updated < ?", (cutoff,))
            rows = self._db.execute("SELECT owner, task FROM tasks").fetchall()
        loaded = 0
        for owner, raw in rows:
            try:
                task = Parse(raw, Task())
            except Exception:  # noqa: BLE001 — one bad row must not stop the agent
                logger.warning("task store: unreadable row skipped", extra={"owner": owner})
                continue
            self._impl.tasks.setdefault(owner, {})[task.id] = task
            loaded += 1
        logger.info("task store: %d task(s) loaded from %s", loaded, self.path)

    def _write(self, owner: str, task: Task) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO tasks (owner, id, task, final, updated) VALUES (?, ?, ?, ?, ?)",
                (owner, task.id, MessageToJson(task), int(task.status.state in FINAL_STATES), time.time()),
            )

    async def save(self, task: Task, context: ServerCallContext) -> None:
        await super().save(task, context)
        self._write(self._owner_of(context), task)

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        await super().delete(task_id, context)
        with self._lock:
            self._db.execute("DELETE FROM tasks WHERE owner = ? AND id = ?",
                             (self._owner_of(context), task_id))

    # Direct access by owner, for work that runs without a request (resume at start).

    def get_owned(self, owner: str, task_id: str) -> Task | None:
        task = self._impl.tasks.get(owner, {}).get(task_id)
        if task is None:
            return None
        copy = Task()
        copy.CopyFrom(task)
        return copy

    def put_owned(self, owner: str, task: Task) -> None:
        stored = Task()
        stored.CopyFrom(task)
        self._impl.tasks.setdefault(owner, {})[task.id] = stored
        self._write(owner, task)

    # Journal of answers that wait for their owner.

    def add_pending(self, task_id: str, owner: str, request: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO pending (id, owner, request, created) VALUES (?, ?, ?, ?)",
                (task_id, owner, json.dumps(request, ensure_ascii=False), time.time()),
            )

    def drop_pending(self, task_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM pending WHERE id = ?", (task_id,))

    def pending(self) -> list[tuple[str, str, dict]]:
        with self._lock:
            rows = self._db.execute("SELECT id, owner, request FROM pending ORDER BY created").fetchall()
        return [(tid, owner, json.loads(raw)) for tid, owner, raw in rows]
