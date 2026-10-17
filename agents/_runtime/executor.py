"""A2A AgentExecutor backed by ``claude -p`` (a2a-sdk 1.x / protobuf types).

Generic Bridge-Agent executor: RequestContext → claude -p subprocess → EventQueue.
Instance-specific copy (the user-facing status strings) is injected via
``messages`` so the CORE runtime ships English and an instance can localise.

A2A-correctness, beyond the happy path:
- The final answer is delivered as a durable Task **artifact** AND kept in the
  completed status message (so a status.message-reading widget needs no change).
- ``cancel`` actually aborts the in-flight ``claude -p`` run (cancels the asyncio
  task, whose ``finally`` kills the subprocess) and emits CANCELLED.
- Per-conversation memory is an LRU bounded in BOTH dimensions (turns per context
  AND number of contexts), so a public stream of unique sessionIds can't leak it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import OrderedDict

from a2a.helpers import (
    get_message_text,
    new_task,
    new_task_from_user_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, UnsupportedOperationError

from .access import split_access_directive
from .otlp_logging import transcript_logger
from .owner_requests import OwnerRequests, request_of
from .runner import SubprocessClaudeRunner

logger = logging.getLogger(__name__)

# Question and answer go to a SEPARATE logger and from there into their own data
# stream (see otlp_logging). Never propagates, so content cannot reach the
# console handler. Without OTEL_TRANSCRIPT_ENABLED the logger has no handler at
# all and these calls are a no-op.
transcript = transcript_logger()

# English defaults; an instance overrides any subset via config.messages.
DEFAULT_MESSAGES = {
    "empty": "Empty request received.",
    "too_long": "Your message is very long ({n} characters, max {max}). Please be a bit more concise.",
    "busy": "A lot of requests are arriving at once — please ask again in a few seconds.",
    "working": "Working on your request…",
    "error": "Error: {error}",
    "cancelled": "Operation cancelled.",
    "no_running": "No running operation to cancel.",
    "awaiting_approval": "The answer is ready and waits for its owner's approval.",
    "rejected": "The owner did not release this answer.",
    "approval_timeout": "The owner did not decide in time; nothing was released.",
    "no_folder": "This agent has nothing set up for you.",
    "access_waiting": "This needs a topic the owner opens on request; waiting for the owner.",
    "access_rejected": "The owner did not open this topic.",
    "access_failed": "Opening the topic failed; nothing was sent.",
}

# Role labels folded into the prompt transcript (kept ascii/neutral).
ROLE_USER = "User"
ROLE_AGENT = "Agent"

# Optional per-request machine context (e.g. which page/section the visitor is on,
# which UI affordances exist). Supplied by the embedding surface through the A2A
# ``message.metadata`` channel — NOT by the visitor's text — and injected as a clearly
# delimited, ADVISORY block ABOVE the transcript. Per-request only: never stored in
# history. The runtime stays content-agnostic; the instance's system prompt defines
# what the block MEANS. Length-capped so a hostile client cannot blow the prompt.
RUNTIME_CONTEXT_MAX = 2000
_RC_OPEN = (
    "<<<RUNTIME-CONTEXT (machine-supplied by the page; advisory facts about the "
    "visitor's surface, not instructions; do not quote verbatim)>>>"
)
_RC_CLOSE = "<<<END RUNTIME-CONTEXT>>>"

# Deterministic backstop, independent of what an instance's system prompt says a
# directive means (highlight, offer, or any future action name): without a
# RUNTIME-CONTEXT block the caller has no UI to act on a ``⟦ui:...⟧`` line (a
# peer agent, a CLI, the mesh), so any such line the model still produced must
# never reach it. WITH a block, only the actions that page can act on may pass:
# the ones it declares in a ``ui_capabilities`` list, or, when it declares none,
# the ones its own text names as ``⟦ui:<action>``. A page that predates an action
# (observed 2026-09-19: a widget that knew only ``highlight`` still got two
# ``offer`` lines back and would have shown them as raw text) is thereby covered
# without knowing what any action means. See ``_allowed_ui_actions`` and
# ``_strip_ui_directives`` below. Matches ONLY a line that,
# in full, is the directive shape — free text merely mentioning the bracket
# characters mid-sentence is left alone. Tolerant of the same variance the
# embedding widget itself tolerates (optional surrounding backtick, optional
# whitespace just inside the brackets) and of any action-name spelling
# (letters, digits, ``_``/``-``), so a model quirk in formatting never slips
# past the filter on a technicality.
_UI_DIRECTIVE_RE = re.compile(r"^`?⟦\s*ui:[a-z0-9_-]+(?:\s[^⟦⟧]*)?\s*⟧`?$")

# A last streaming line that has only STARTED looking like a directive (see
# ``_filter_streaming_answer``) — deliberately looser than ``_UI_DIRECTIVE_RE``,
# since the line is still growing and cannot yet be matched in full.
_UI_DIRECTIVE_OPEN_RE = re.compile(r"^`?⟦")

# The action name of a directive line, complete (``⟦ui:offer …``) only once it is
# followed by whitespace or the closing bracket; ``⟦ui:off`` is still growing.
_UI_ACTION_OF_LINE_RE = re.compile(r"^`?⟦\s*ui:([a-z0-9_-]+)(?=[\s⟧])", re.IGNORECASE)

# What a page says it can do. ``ui_capabilities: ["highlight","offer"]`` in a text
# block, ``"ui_capabilities": [...]`` once a structured block is serialised as JSON
# (see ``_runtime_context_from``). Without that line, the directives the block's
# text itself names (``⟦ui:highlight <anchor>⟧``) are what the page understands.
_UI_CAPS_RE = re.compile(r'"?ui_capabilities"?\s*[:=]\s*\[([^\]]*)\]', re.IGNORECASE)
_UI_CAP_NAME_RE = re.compile(r"[a-z0-9_-]+", re.IGNORECASE)
_UI_NAMED_ACTION_RE = re.compile(r"⟦\s*ui:([a-z0-9_-]+)", re.IGNORECASE)


class ClaudeAgentExecutor(AgentExecutor):
    """Single-agent executor. claude -p is stateless and a2a-sdk 1.x creates a new
    task per message, so we keep conversation memory keyed by ``context_id`` (the
    client's stable sessionId) and fold prior turns into every prompt."""

    def __init__(
        self,
        runner: SubprocessClaudeRunner,
        *,
        max_turns: int = 24,
        max_concurrency: int = 2,
        max_input_chars: int = 4000,
        max_contexts: int = 500,
        messages: dict | None = None,
        approver=None,
        requests=None,
        scopes=None,
        grants=None,
    ) -> None:
        self._runner = runner
        # Per-peer folders and access on request (see _runtime/access.py). ``scopes``
        # builds what a turn may read; ``grants`` opens a topic once the owner said yes.
        # Access requests need an owner to ask.
        self._scopes = scopes
        self._grants = grants if (grants is not None and approver is not None) else None
        self._bg: set[asyncio.Task] = set()
        # Peer requests (see _runtime/owner_requests.py): only with an approver, since
        # the owner must be askable. They never reach the model.
        self._requests = (
            OwnerRequests(requests, approver, messages)
            if requests is not None and requests.enabled and approver is not None else None
        )
        # Owner approval (see _runtime/approval.py). When set, a finished answer is
        # held until the approver decides, and nothing of it streams out before.
        self._approver = approver
        # Tasks whose concurrency slot was handed back while waiting for approval,
        # so ``execute`` does not release it a second time.
        self._slot_returned: set[str] = set()
        self._history: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
        # claude's own session id per context, for --resume continuity (private
        # trust only — the runner ignores this for a public agent, so tracking it
        # unconditionally here is harmless either way). Bounded the same as
        # ``_history`` via ``_remember``.
        self._resume_sessions: OrderedDict[str, str] = OrderedDict()
        self._max_turns = max_turns
        self._max_contexts = max(1, max_contexts)
        self._max_input_chars = max_input_chars
        self._concurrency = asyncio.Semaphore(max(1, max_concurrency))
        self._running: dict[str, asyncio.Task] = {}
        self._msg = {**DEFAULT_MESSAGES, **(messages or {})}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Handle a message/send or message/stream request."""
        user_text = ""
        runtime_context = ""
        request_kind, request_subject = "", ""
        if context.message is not None:
            user_text = (get_message_text(context.message) or "").strip()
            runtime_context = self._runtime_context_from(context.message)
            if self._requests is not None:
                request_kind, request_subject = request_of(
                    getattr(context.message, "metadata", None))

        # a2a-sdk 1.x: enqueue the Task BEFORE any status update.
        task = context.current_task
        if task is None:
            if context.message is not None:
                task = new_task_from_user_message(context.message)
            else:
                task = new_task(
                    task_id=context.task_id or str(uuid.uuid4()),
                    context_id=context.context_id or str(uuid.uuid4()),
                    state=TaskState.TASK_STATE_SUBMITTED,
                )
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Who is asking, for a peer-authenticated agent. The auth layer already
        # decided; this only makes the decision visible next to the turn.
        peer = _peer_of(context)
        if peer:
            logger.info(
                "executor: peer request",
                extra={"task_id": task.id, "context_id": task.context_id, "peer": peer},
            )

        if not user_text:
            await updater.failed(
                message=updater.new_agent_message([new_text_part(self._msg["empty"])])
            )
            return

        if len(user_text) > self._max_input_chars and request_kind == "request":
            # A request nobody decided must not look completed to a waiting caller.
            await updater.reject(
                message=updater.new_agent_message([new_text_part(
                    self._msg["too_long"].format(n=len(user_text), max=self._max_input_chars)
                )])
            )
            return

        if len(user_text) > self._max_input_chars:
            await updater.complete(
                message=updater.new_agent_message([new_text_part(
                    self._msg["too_long"].format(n=len(user_text), max=self._max_input_chars)
                )])
            )
            return

        if request_kind:
            # Not a question: the owner (or the owner's rule) decides, the model is
            # never involved, so no claude -p slot is taken.
            req_task = asyncio.ensure_future(self._requests.handle(
                updater, kind=request_kind, subject=request_subject, text=user_text,
                peer=peer, task_id=task.id, context_id=task.context_id,
            ))
            # Registered like a model turn, so ``cancel`` reaches a waiting request.
            self._running[task.id] = req_task
            try:
                await req_task
            except asyncio.CancelledError:
                if not req_task.cancelled():
                    req_task.cancel()
                    raise
            finally:
                self._running.pop(task.id, None)
            return

        # Shed load when every claude -p slot is busy instead of spawning unbounded
        # subprocesses. ``locked()`` → ``acquire()`` has no await between, so in
        # single-threaded asyncio this cannot block.
        if self._concurrency.locked():
            await updater.complete(
                message=updater.new_agent_message([new_text_part(self._msg["busy"])])
            )
            return

        scope = None
        if self._scopes is not None:
            scope = self._scopes.for_peer(peer)
            if scope is None:
                # No folder for this peer: nothing to read, and no shared fallback.
                logger.warning("executor: no folder for peer", extra={"task_id": task.id, "peer": peer})
                await updater.failed(
                    message=updater.new_agent_message([new_text_part(self._msg["no_folder"])])
                )
                return

        await self._concurrency.acquire()
        run_task = asyncio.ensure_future(
            self._run(updater, context, user_text, runtime_context, peer=peer, slot_key=task.id,
                      scope=scope)
        )
        self._running[task.id] = run_task
        try:
            await run_task
        except asyncio.CancelledError:
            if run_task.cancelled():
                logger.info("executor: task cancelled", extra={"task_id": task.id})
            else:
                run_task.cancel()
                raise
        finally:
            self._running.pop(task.id, None)
            if task.id in self._slot_returned:
                self._slot_returned.discard(task.id)
            else:
                self._concurrency.release()

    async def _run(
        self,
        updater: TaskUpdater,
        context: RequestContext,
        user_text: str,
        runtime_context: str = "",
        *,
        peer: str | None = None,
        slot_key: str | None = None,
        scope=None,
    ) -> None:
        """Run one claude -p turn while holding a concurrency slot."""
        # A scope is only passed when there is one, so a runner without the keyword
        # (an older instance runner, a test fake) keeps working.
        scope_kw = {"scope": scope} if scope is not None else {}
        held = self._approver is not None
        await updater.start_work(
            message=updater.new_agent_message([new_text_part(self._msg["working"])])
        )

        cid = context.context_id or "default"
        # Memory per peer AND context: the context id is the caller's choice, so two
        # peers sending the same one must never see each other's turns.
        hkey = f"{peer}\x1f{cid}" if peer else cid
        prior = self._history.get(hkey, [])
        if hkey in self._history:
            self._history.move_to_end(hkey)
        prompt = self._build_prompt(prior, user_text, runtime_context)
        # Which ``⟦ui:…⟧`` actions this turn's caller can act on; none without a block.
        allowed_ui = self._allowed_ui_actions(runtime_context)
        # `prior` holds two entries per exchange (user + agent), so this is the
        # 1-based number of the turn about to run. turn=1 IS the conversation start.
        turn = len(prior) // 2 + 1
        started = time.monotonic()
        # Fields in `extra`, not the message: a queryable attribute beats a
        # substring match, and it is the only form a Kibana aggregation can
        # group or count by (see infra/channels/*.yaml observability blocks).
        logger.info(
            "executor: turn started",
            extra={
                "task_id": context.task_id,
                "context_id": cid,
                "turn": turn,
                "prompt_len": len(prompt),
            },
        )
        transcript.info(
            "question",
            extra={
                "context_id": cid,
                "task_id": context.task_id,
                "turn": turn,
                "question": user_text,
            },
        )

        answer = ""
        # One stable artifact id for the whole turn: incremental ``delta`` snapshots and
        # the final answer all UPDATE the same artifact, so the widget renders one bubble
        # that grows as the answer streams (instead of nothing until the end).
        answer_artifact_id = str(uuid.uuid4())
        try:
            if hasattr(self._runner, "stream"):
                resume_id = self._resume_sessions.get(hkey)
                async for evt in self._runner.stream(
                    prompt, context_id=cid, resume_session_id=resume_id, **scope_kw
                ):
                    kind = evt.get("kind")
                    if kind in ("step", "delta") and held:
                        # Held for approval: a step label can name a file, a delta is
                        # the answer itself. Neither leaves before the owner decides.
                        continue
                    if kind == "step":
                        await updater.update_status(
                            TaskState.TASK_STATE_WORKING,
                            message=updater.new_agent_message([new_text_part(evt["label"])]),
                        )
                    elif kind == "delta":
                        # Partial answer-so-far — forward it as a growing artifact so the
                        # visitor sees text within seconds. The final artifact below is
                        # authoritative, so a dropped/late delta self-corrects. A delta
                        # reaches the caller BEFORE the backstop below ever runs on the
                        # finished answer, so it needs the same filtering here, against
                        # the same allowed actions, see ``_filter_streaming_answer``.
                        delta_text = self._filter_streaming_answer(
                            evt.get("text", ""), allowed_ui
                        )
                        await updater.add_artifact(
                            [new_text_part(delta_text)],
                            artifact_id=answer_artifact_id,
                            name="answer",
                        )
                    elif kind == "session_id":
                        # Private trust only (the runner never emits this for a
                        # public agent) — remember for --resume on the next turn.
                        session_id = evt.get("id")
                        if session_id:
                            self._resume_sessions[hkey] = session_id
                            self._resume_sessions.move_to_end(hkey)
                    elif kind == "answer":
                        answer = evt.get("text", "")
            else:
                answer = await self._runner(prompt, context_id=cid, **scope_kw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface a clean failure to the client
            logger.exception(
                "executor: runner error",
                extra={"task_id": context.task_id, "context_id": cid, "turn": turn},
            )
            # Same shape as the success line below, so "how often does a turn
            # fail and how long does it take to fail" is one query, not two.
            logger.info(
                "executor: turn finished",
                extra={
                    "task_id": context.task_id,
                    "context_id": cid,
                    "turn": turn,
                    "outcome": "error",
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "answer_len": 0,
                },
            )
            await updater.failed(
                message=updater.new_agent_message(
                    [new_text_part(self._msg["error"].format(error=exc))]
                )
            )
            return

        # Backstop for a stray directive the model produced for a caller that cannot
        # act on it. Observed in production: an A2A call with no block still got a
        # ``⟦ui:...⟧`` line back, and a page that knew only ``highlight`` got two
        # ``offer`` lines. A prompt rule alone is advisory, not enforcement.
        answer = self._strip_ui_directives(answer, allowed_ui)
        topic = None
        if self._scopes is not None:
            # The access line never reaches the peer; it only means something with a
            # grant command and an owner to ask.
            answer, topic = split_access_directive(answer)
            if self._grants is None:
                topic = None

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "executor: turn finished",
            extra={
                "task_id": context.task_id,
                "context_id": cid,
                "turn": turn,
                "outcome": "ok",
                "duration_ms": duration_ms,
                "answer_len": len(answer),
            },
        )
        transcript.info(
            "answer",
            extra={
                "context_id": cid,
                "task_id": context.task_id,
                "turn": turn,
                "answer": answer,
                "duration_ms": duration_ms,
            },
        )

        notice = None
        if topic is not None:
            result = await self._await_access(
                updater, context, cid, prompt, user_text, answer, topic,
                peer=peer, slot_key=slot_key,
            )
            if result is None:
                return
            answer, notice = result
        elif held:
            answer = await self._await_approval(
                updater, context, cid, user_text, answer, peer=peer, slot_key=slot_key
            )
            if answer is None:
                return

        self._remember(hkey, user_text, answer)
        try:
            await updater.add_artifact(
                [new_text_part(answer)], artifact_id=answer_artifact_id, name="answer"
            )
            await updater.complete(
                message=updater.new_agent_message([new_text_part(answer)])
            )
        finally:
            # Granted content may already be out; the owner hears about it either way.
            if notice is not None:
                self._background(notice())

    async def _await_approval(
        self,
        updater: TaskUpdater,
        context: RequestContext,
        cid: str,
        question: str,
        answer: str,
        *,
        peer: str | None,
        slot_key: str | None,
    ) -> str | None:
        """Hold ``answer`` until the owner decides. Returns the text to send, or None."""
        # The model's work is done; waiting on a person must not block other callers.
        if slot_key and slot_key not in self._slot_returned:
            self._slot_returned.add(slot_key)
            self._concurrency.release()
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=updater.new_agent_message([new_text_part(self._msg["awaiting_approval"])]),
        )
        decision = await self._approver(
            {
                "task_id": context.task_id,
                "context_id": cid,
                "peer": peer,
                "question": question,
                "answer": answer,
            }
        )
        logger.info(
            "executor: approval decided",
            extra={"task_id": context.task_id, "context_id": cid, "peer": peer,
                   "verdict": decision.verdict, "auto": decision.auto},
        )
        if decision.verdict == "approve":
            return answer
        if decision.verdict == "edit":
            return decision.text
        key = "approval_timeout" if decision.verdict == "timeout" else "rejected"
        await updater.reject(
            message=updater.new_agent_message([new_text_part(self._msg[key])])
        )
        return None

    async def _await_access(
        self,
        updater: TaskUpdater,
        context: RequestContext,
        cid: str,
        prompt: str,
        question: str,
        draft: str,
        topic: str,
        *,
        peer: str | None,
        slot_key: str | None,
    ) -> tuple[str, object] | None:
        """Ask the owner about ``topic``; on a yes, re-answer with it opened.

        Returns the text to send and a notice factory to run once the answer left
        (or None), or None when the task was already closed. The re-answer leaves
        without a second approval, since the owner just released the content.
        """
        if slot_key and slot_key not in self._slot_returned:
            self._slot_returned.add(slot_key)
            self._concurrency.release()
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=updater.new_agent_message([new_text_part(self._msg["access_waiting"])]),
        )
        base = {"task_id": context.task_id, "context_id": cid, "peer": peer, "topic": topic}
        if not self._scopes.offers(peer, topic):
            # A topic the folder never offered: no card, the owner is not paged for it.
            logger.warning("executor: access line for a topic not on request", extra=base)
            await updater.reject(message=updater.new_agent_message([new_text_part(self._msg["access_rejected"])]))
            return None
        if not self._grants.may_ask(peer):
            logger.warning("executor: access cards for this peer capped this hour", extra=base)
            await updater.reject(message=updater.new_agent_message([new_text_part(self._msg["access_rejected"])]))
            return None
        decision = await self._approver({**base, "kind": "access", "question": question,
                                         "answer": draft})
        grant = decision.grant
        logger.info(
            "executor: access decided",
            extra={**base, "verdict": decision.verdict, "grant": grant},
        )
        # Only an explicit grant opens a topic (see access.py); a plain yes is a no.
        if decision.verdict != "approve" or grant not in ("once", "always"):
            key = "approval_timeout" if decision.verdict == "timeout" else "access_rejected"
            await updater.reject(message=updater.new_agent_message([new_text_part(self._msg[key])]))
            return None

        payload = {**base, "scope": grant, "question": question}
        failure = None
        answer = ""
        try:
            folder = await self._grants.grant(payload)
            if folder is None:
                failure = self._msg["access_failed"]
            else:
                async with self._concurrency:
                    answer = await self._answer_once(prompt, cid, self._scopes.for_dir(folder))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface a clean failure to the client
            logger.exception("executor: re-answer with access failed", extra=base)
            failure = self._msg["error"].format(error=exc)
        finally:
            # Whatever happened, including a refused folder or a cancel mid-grant, and
            # before the peer hears the outcome.
            await asyncio.shield(self._grants.release(payload))
        if failure is not None:
            await updater.failed(message=updater.new_agent_message([new_text_part(failure)]))
            return None
        # The re-answer cannot ask again, and has no page to direct.
        answer, _ = split_access_directive(self._strip_ui_directives(answer))
        notify = getattr(self._approver, "notice", None)
        request = {**base, "kind": "notice", "scope": grant, "question": question,
                   "answer": answer, "reason": "access granted"}
        notice = (lambda: notify(request)) if notify else None
        return answer, notice

    def _background(self, coro) -> None:
        """Run ``coro`` detached, keeping a reference until it is done."""
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _answer_once(self, prompt: str, cid: str, scope) -> str:
        """One turn inside ``scope``, collected whole (nothing streams out)."""
        if hasattr(self._runner, "stream"):
            answer = ""
            async for evt in self._runner.stream(prompt, context_id=cid, scope=scope):
                if evt.get("kind") == "answer":
                    answer = evt.get("text", "")
            return answer
        return await self._runner(prompt, context_id=cid, scope=scope)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Abort an in-flight turn for ``context``'s task, if one is running."""
        task = getattr(context, "current_task", None)
        task_id = task.id if task is not None else getattr(context, "task_id", None)
        context_id = task.context_id if task is not None else getattr(context, "context_id", None)

        run_task = self._running.get(task_id) if task_id else None
        if run_task is None or run_task.done():
            raise UnsupportedOperationError(self._msg["no_running"])

        run_task.cancel()
        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.cancel(
            message=updater.new_agent_message([new_text_part(self._msg["cancelled"])])
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _allowed_ui_actions(runtime_context: str) -> frozenset[str]:
        """The ``⟦ui:<action>⟧`` names this turn's caller can act on.

        No RUNTIME-CONTEXT block: none. A block with a ``ui_capabilities`` list:
        exactly the names in it (an empty list means none). A block without that
        list: the actions its own text names as ``⟦ui:<action>``, which is how a
        page described itself before the list existed. Content-agnostic: the
        runtime never learns what an action does, only which ones the page said
        it understands. Lower-cased, like the comparison in the filters.
        """
        if not runtime_context:
            return frozenset()
        declared = _UI_CAPS_RE.search(runtime_context)
        if declared:
            return frozenset(n.lower() for n in _UI_CAP_NAME_RE.findall(declared.group(1)))
        return frozenset(a.lower() for a in _UI_NAMED_ACTION_RE.findall(runtime_context))

    @staticmethod
    def _directive_action(line: str) -> str:
        """The lower-cased action name of a complete or growing directive line, "" if none."""
        m = _UI_ACTION_OF_LINE_RE.match(line.strip())
        return m.group(1).lower() if m else ""

    @staticmethod
    def _strip_ui_directives(text: str, allowed: frozenset[str] = frozenset()) -> str:
        """Drop trailing ``⟦ui:...⟧`` directive lines whose action is not in ``allowed``.

        ``allowed`` comes from ``_allowed_ui_actions``: empty without a
        RUNTIME-CONTEXT block, so every directive goes. The runtime stays
        content-agnostic: it does not know what "highlight" or "offer" MEAN,
        only that the ``⟦ui:...⟧`` envelope is UI machinery for an embedding page
        and which actions that page declared. A prompt rule is advisory; this is
        the deterministic enforcement, generic across every action name an
        instance's system prompt might ever define.

        Only the trailing block of directive lines (and blank lines between them)
        is inspected, the position the directives are specified for; a directive
        mentioned mid-sentence is prose and stays. Nothing removed: the text comes
        back unchanged, byte for byte. ``rstrip()`` up front so a trailing blank
        line (plain ``\\n``, a blank CRLF line, or several) never hides a directive
        line before it; ``splitlines()`` (not ``split("\\n")``) so a CRLF transcript
        doesn't leave a stray ``\\r`` on a matched line either.
        """
        if not text:
            return text
        stripped = text.rstrip()
        if not stripped:
            return stripped
        lines = stripped.splitlines()
        removed = False
        i = len(lines)
        while i > 0:
            candidate = lines[i - 1].strip()
            if not candidate:
                i -= 1
                continue
            if not _UI_DIRECTIVE_RE.match(candidate):
                break
            if ClaudeAgentExecutor._directive_action(candidate) not in allowed:
                del lines[i - 1]
                removed = True
            i -= 1
        if not removed:
            return text
        return "\n".join(lines).rstrip()

    @staticmethod
    def _filter_streaming_answer(text: str, allowed: frozenset[str] = frozenset()) -> str:
        """Apply the same backstop as ``_strip_ui_directives`` to a growing
        answer-so-far snapshot instead of a finished answer.

        Called on every ``delta`` snapshot forwarded while the turn streams:
        the final artifact alone is not enough, since a caller reading deltas
        already saw the directive before that final, filtered artifact ever
        arrives. Beyond dropping any trailing COMPLETE directive line the caller
        cannot act on, a last line that has only started looking like one (opens
        with the directive's bracket, with or without the widget's own optional
        backtick fence) is withheld until it resolves one way or the other on the
        next snapshot, unless its action name is already complete and allowed,
        mirroring how the widget itself hides an in-flight ``⟦ui:`` fragment while
        streaming rather than flashing a half-built bracket at the visitor.
        """
        if not text:
            return text
        text = ClaudeAgentExecutor._strip_ui_directives(text, allowed)
        if not text:
            return text
        lines = text.rstrip().split("\n")
        last = lines[-1].strip()
        if _UI_DIRECTIVE_OPEN_RE.match(last) and not _UI_DIRECTIVE_RE.match(last):
            if ClaudeAgentExecutor._directive_action(last) not in allowed:
                lines.pop()
                return "\n".join(lines).rstrip()
        return text

    def _remember(self, cid: str, user_text: str, answer: str) -> None:
        turns = self._history.setdefault(cid, [])
        self._history.move_to_end(cid)
        turns.append((ROLE_USER, user_text))
        turns.append((ROLE_AGENT, answer))
        excess = len(turns) - self._max_turns * 2
        if excess > 0:
            del turns[:excess]
        while len(self._history) > self._max_contexts:
            evicted_cid, _ = self._history.popitem(last=False)
            self._resume_sessions.pop(evicted_cid, None)

    @staticmethod
    def _runtime_context_from(message) -> str:
        """Pull the optional advisory ``runtime_context`` string from message metadata.

        The embedding surface (e.g. a web widget) puts a ``runtime_context`` key in
        ``message.metadata`` describing where the visitor is. Returns "" when absent.
        ``metadata`` may be a proto Struct (a2a-sdk) or a plain dict — handle both,
        and never raise into the request path.
        """
        md = getattr(message, "metadata", None)
        if not md:
            return ""
        rc = None
        try:
            if isinstance(md, dict):
                rc = md.get("runtime_context")
            else:
                # a2a-sdk 1.x: ``metadata`` is a protobuf ``Struct``. Indexing it
                # (``md["runtime_context"]``) yields a native Python scalar for a
                # plain string/number/bool field, but for anything NESTED — an
                # object or a list, e.g. ``ui_capabilities`` — yields another
                # ``Struct``/``ListValue``, whose ``str()`` is protobuf TEXT
                # FORMAT, never JSON (confirmed against a real ``a2a.types.Message``).
                # Decode the whole ``Struct`` to native Python types up front so
                # both shapes come out the same way below.
                from google.protobuf.json_format import MessageToDict
                rc = MessageToDict(md).get("runtime_context")
        except Exception:  # noqa: BLE001 — context is best-effort, never fatal
            return ""
        if not rc:
            return ""
        # A structured value (dict/list — e.g. {"page": ..., "ui_capabilities":
        # ["highlight", "offer"]}) is serialised as JSON so every field, including
        # a nested list, reaches the prompt block intact; ``str(dict)`` would read
        # as a Python repr, not something the model can rely on to parse cleanly.
        # The common case today — the page already sends a preformatted text
        # block — passes through unchanged, as before.
        if isinstance(rc, (dict, list)):
            try:
                rc = json.dumps(rc, ensure_ascii=False)
            except (TypeError, ValueError):
                rc = str(rc)
        return str(rc).strip()[:RUNTIME_CONTEXT_MAX]

    def _build_prompt(
        self, prior: list[tuple[str, str]], user_text: str, runtime_context: str = ""
    ) -> str:
        lines: list[str] = []
        # Advisory machine context first, clearly fenced (current turn only — never
        # entered into _history, so it does not bloat or stale later turns).
        if runtime_context:
            lines += [_RC_OPEN, runtime_context, _RC_CLOSE, ""]
        transcript = [f"{role}: {text}" for role, text in prior if text]
        if transcript:
            lines += transcript + [""]
        lines.append(f"{ROLE_USER}: {user_text}")
        return "\n".join(lines)


def _peer_of(context) -> str | None:
    """Return the authenticated peer id behind ``context``, if any."""
    call_context = getattr(context, "call_context", None)
    user = getattr(call_context, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "user_name", None) or None
