"""Regression tests for the Bridge-Agent A2A executor (``_runtime.executor``).

Generic runtime code — an instance's own system prompt decides what the
RUNTIME-CONTEXT block MEANS (which UI actions exist, what an anchor is). These
tests lock three runtime-side contracts that hold for every instance:

1. A structured value inside ``message.metadata.runtime_context`` (e.g. a
   nested ``ui_capabilities`` list) must survive the trip into the prompt
   block intact — as valid JSON, not a protobuf text-format dump. The
   existing plain-string shape (today's widget) must keep passing through
   unchanged. Exercised against a REAL ``a2a.types.Message`` (a2a-sdk 1.x:
   ``metadata`` is a protobuf ``Struct``, so a nested field comes back as
   another ``Struct``/``ListValue``, not a plain ``dict``/``list`` — a
   fixture built from a plain Python dict would not catch that).
2. A ``⟦ui:...⟧`` directive line the model still produced despite there being
   no RUNTIME-CONTEXT block must never reach the caller — in the finished
   answer, in the completed status message, AND in every streamed ``delta``
   snapshot along the way (a caller reading deltas sees them before the
   final, filtered artifact ever arrives). A prompt rule alone is advisory,
   not enforcement; this is the deterministic backstop, and its wiring
   inside ``execute()``/``_run()`` is exercised end to end here, not just the
   static helpers in isolation.
3. With a RUNTIME-CONTEXT block present, a directive line passes untouched
   all the way through when the page declared its action (``ui_capabilities``)
   or, without a declaration, named it in its own text; any other directive is
   removed exactly as in 2. The backstop only removes what has no page left to
   act on it (see the section on a block without a declaration further down).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from a2a.helpers import new_text_message
from a2a.server.events import EventQueue
from a2a.types import Role, TaskState
from google.protobuf.json_format import ParseDict

from _runtime.executor import ClaudeAgentExecutor


def _message(runtime_context=None):
    """A real ``a2a.types.Message`` (protobuf), with ``runtime_context`` set via
    ``ParseDict`` the same way a real a2a-sdk 1.x server would populate metadata.
    ``None`` means no ``metadata`` written at all (the empty-Struct default)."""
    msg = new_text_message(text="Frage?", role=Role.ROLE_USER)
    if runtime_context is not None:
        ParseDict({"runtime_context": runtime_context}, msg.metadata)
    return msg


# ---------------------------------------------------------------------------
# _runtime_context_from — structured metadata must pass through intact
# ---------------------------------------------------------------------------


def test_runtime_context_plain_string_passes_through_unchanged():
    rc = "Seite: /de, im Blickfeld: projects, Anker: [example-entry]"
    assert ClaudeAgentExecutor._runtime_context_from(_message(rc)) == rc


def test_runtime_context_dict_with_ui_capabilities_is_preserved_as_json():
    rc = {
        "page": "/de",
        "section": "projects",
        "ui_capabilities": ["highlight", "offer"],
    }
    out = ClaudeAgentExecutor._runtime_context_from(_message(rc))
    # Round-trips: every field, including the nested ui_capabilities list,
    # survives as valid JSON — a real a2a-sdk 1.x metadata Struct returns a
    # nested protobuf Struct/ListValue for this, whose str() is protobuf text
    # format, not JSON, so this only passes once that shape is decoded first.
    assert json.loads(out) == rc


def test_runtime_context_list_value_is_preserved_as_json():
    rc = ["highlight", "offer"]
    out = ClaudeAgentExecutor._runtime_context_from(_message(rc))
    assert json.loads(out) == rc


def test_runtime_context_missing_metadata_is_empty():
    assert ClaudeAgentExecutor._runtime_context_from(_message(None)) == ""
    assert ClaudeAgentExecutor._runtime_context_from(_message("")) == ""
    assert ClaudeAgentExecutor._runtime_context_from(SimpleNamespace(metadata=None)) == ""


# ---------------------------------------------------------------------------
# _strip_ui_directives — the deterministic backstop, static helper
# ---------------------------------------------------------------------------


def test_strip_ui_directives_removes_trailing_directive_when_no_block():
    answer = "The agent built a pipeline.\n⟦ui:highlight example-entry⟧"
    assert (
        ClaudeAgentExecutor._strip_ui_directives(answer)
        == "The agent built a pipeline."
    )


def test_strip_ui_directives_removes_highlight_and_offer_lines_together():
    answer = (
        "This example fits well here.\n"
        "⟦ui:highlight example-entry⟧\n"
        "⟦ui:offer Show me the example⟧\n"
        "⟦ui:offer Book a slot⟧"
    )
    assert (
        ClaudeAgentExecutor._strip_ui_directives(answer)
        == "This example fits well here."
    )


def test_strip_ui_directives_leaves_plain_answer_untouched():
    answer = "The agent is currently working on quality engineering."
    assert ClaudeAgentExecutor._strip_ui_directives(answer) == answer


def test_strip_ui_directives_ignores_bracket_text_mid_answer():
    # Only a line that IS a directive (start to end) is stripped — free text
    # that merely mentions the bracket characters mid-sentence stays untouched.
    answer = "The marker looks like this: ⟦ui:highlight x⟧ and is explained."
    assert ClaudeAgentExecutor._strip_ui_directives(answer) == answer


def test_strip_ui_directives_is_noop_on_empty_string():
    assert ClaudeAgentExecutor._strip_ui_directives("") == ""


def test_strip_ui_directives_handles_trailing_newline_and_blank_lines():
    assert (
        ClaudeAgentExecutor._strip_ui_directives("The answer.\n⟦ui:highlight a⟧\n")
        == "The answer."
    )
    assert (
        ClaudeAgentExecutor._strip_ui_directives("The answer.\n⟦ui:highlight a⟧\n\n")
        == "The answer."
    )


def test_strip_ui_directives_handles_crlf_line_endings():
    assert (
        ClaudeAgentExecutor._strip_ui_directives("The answer.\r\n⟦ui:highlight a⟧\r\n")
        == "The answer."
    )


def test_strip_ui_directives_handles_backtick_wrapped_directive():
    assert (
        ClaudeAgentExecutor._strip_ui_directives("The answer.\n`⟦ui:highlight a⟧`")
        == "The answer."
    )


def test_strip_ui_directives_handles_inner_whitespace_in_brackets():
    assert (
        ClaudeAgentExecutor._strip_ui_directives("The answer.\n⟦ ui:highlight a ⟧")
        == "The answer."
    )


def test_strip_ui_directives_on_answer_that_is_only_a_directive_is_empty():
    # A degenerate case, not a happy path: the caller gets an empty string, not
    # a crash — the system prompt instructs the model to never reply with only
    # a directive, this just locks the runtime's own behaviour if it ever does.
    assert ClaudeAgentExecutor._strip_ui_directives("⟦ui:highlight a⟧") == ""


# ---------------------------------------------------------------------------
# execute()/_run() — the wiring, not just the static helpers
# ---------------------------------------------------------------------------


class _RecordingQueue(EventQueue):
    """Minimal in-memory stand-in — the real ``EventQueue`` is an async
    pub/sub bridge to a live SSE connection; here we just want every event
    ``execute()`` enqueued, in order."""

    def __init__(self):
        self.events: list = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


class _FakeStreamingRunner:
    """A ``SubprocessClaudeRunner`` stand-in with a ``stream()`` generator —
    the code path ``_run()`` actually takes in production (the runner always
    has ``stream()``, per its own module docstring)."""

    def __init__(self, events: list[dict]):
        self._events = events

    async def stream(self, prompt, *, context_id=None, resume_session_id=None):
        for evt in self._events:
            yield evt


def _artifact_texts(event) -> list[str] | None:
    artifact = getattr(event, "artifact", None)
    if artifact is None:
        return None
    return [part.text for part in artifact.parts]


async def _execute(runtime_context) -> list:
    events = [
        {"kind": "delta", "text": "Partial answer so far."},
        {
            "kind": "delta",
            "text": "Partial answer so far.\n⟦ui:highlight example-entry⟧",
        },
        {
            "kind": "answer",
            "text": (
                "Partial answer so far.\n"
                "⟦ui:highlight example-entry⟧\n"
                "⟦ui:offer Show me the example⟧"
            ),
        },
    ]
    executor = ClaudeAgentExecutor(_FakeStreamingRunner(events))
    message = _message(runtime_context)
    context = SimpleNamespace(
        message=message,
        current_task=None,
        context_id="ctx-1",
        task_id="task-1",
    )
    queue = _RecordingQueue()
    await executor.execute(context, queue)
    return queue.events


def test_execute_without_runtime_context_strips_ui_directives_everywhere():
    events = asyncio.run(_execute(None))
    artifact_events = [e for e in events if _artifact_texts(e) is not None]
    assert artifact_events, "expected at least one artifact event"
    for event in artifact_events:
        for text in _artifact_texts(event):
            assert "⟦ui:" not in text, f"stray directive reached a caller with no block: {text!r}"

    completed = [
        e
        for e in events
        if hasattr(e, "status") and e.status.state == TaskState.TASK_STATE_COMPLETED
    ]
    assert completed, "expected a completed status event"
    final_text = completed[-1].status.message.parts[0].text
    assert "⟦ui:" not in final_text
    assert final_text == "Partial answer so far."


def test_execute_with_runtime_context_keeps_ui_directives_intact():
    runtime_context = {"page": "/de", "ui_capabilities": ["highlight", "offer"]}
    events = asyncio.run(_execute(runtime_context))

    completed = [
        e
        for e in events
        if hasattr(e, "status") and e.status.state == TaskState.TASK_STATE_COMPLETED
    ]
    assert completed, "expected a completed status event"
    final_text = completed[-1].status.message.parts[0].text
    assert "⟦ui:highlight example-entry⟧" in final_text
    assert "⟦ui:offer Show me the example⟧" in final_text

    # The final artifact carries the same, unfiltered text.
    artifact_events = [e for e in events if _artifact_texts(e) is not None]
    assert any(
        "⟦ui:offer Show me the example⟧" in text
        for event in artifact_events
        for text in _artifact_texts(event)
    )


# ---------------------------------------------------------------------------
# A block WITHOUT a declaration of what the page can do. Observed 2026-09-19
# on one instance: the widget live at that time sends a RUNTIME-CONTEXT that
# names only ``⟦ui:highlight <anchor>⟧`` and no ``ui_capabilities`` line, and
# strips only highlight lines itself. The model still appended two
# ``⟦ui:offer …⟧`` lines in 3 of 3 runs, which that widget would have shown as
# raw text. A block is therefore not a licence for every directive: only the
# actions the page declared (``ui_capabilities``), or, without a declaration,
# the ones its own text names, may pass. Everything else is removed here, in
# the finished answer and in every streamed snapshot.
# ---------------------------------------------------------------------------

_OLD_WIDGET_RC = (
    "You are embedded on the owner's profile page (path /en/, UI language en). "
    "You can guide this page: scrolling to and briefly highlighting one section "
    "via ⟦ui:highlight <anchor>⟧.\n"
    "No specific section is in the visitor's view right now.\n"
    "Single-entry anchors (use one when the answer points at a specific entry): "
    "example-entry."
)
_NEW_WIDGET_RC = (
    "You are embedded on the owner's profile page (path /en/, UI language en). "
    "You can guide this page: scrolling to and briefly highlighting one section "
    "via ⟦ui:highlight <anchor>⟧.\n"
    'ui_capabilities: ["highlight","offer"]\n'
    "You may also propose up to two short next steps as buttons: append at most two "
    "lines ⟦ui:offer <button text>⟧ after the highlight line."
)


def test_allowed_ui_actions_without_block_is_empty():
    assert ClaudeAgentExecutor._allowed_ui_actions("") == frozenset()


def test_allowed_ui_actions_follow_the_declared_capabilities():
    assert ClaudeAgentExecutor._allowed_ui_actions(_NEW_WIDGET_RC) == {"highlight", "offer"}
    only_highlight = 'Page /en\nui_capabilities: ["highlight"]\nmention of ⟦ui:offer x⟧ in prose'
    # The declaration wins over any directive the prose happens to mention.
    assert ClaudeAgentExecutor._allowed_ui_actions(only_highlight) == {"highlight"}
    assert ClaudeAgentExecutor._allowed_ui_actions("Page /en\nui_capabilities: []") == frozenset()


def test_allowed_ui_actions_from_a_json_block():
    rc = json.dumps({"page": "/en", "ui_capabilities": ["highlight", "offer"]})
    assert ClaudeAgentExecutor._allowed_ui_actions(rc) == {"highlight", "offer"}
    rc = json.dumps({"page": "/en", "ui_capabilities": ["highlight"]})
    assert ClaudeAgentExecutor._allowed_ui_actions(rc) == {"highlight"}


def test_allowed_ui_actions_without_declaration_are_the_ones_the_page_names():
    assert ClaudeAgentExecutor._allowed_ui_actions(_OLD_WIDGET_RC) == {"highlight"}
    assert ClaudeAgentExecutor._allowed_ui_actions("Page: /en, anchors: [example-entry]") == frozenset()


def test_strip_keeps_allowed_and_drops_undeclared_directives():
    answer = (
        "This example fits well here.\n"
        "⟦ui:highlight example-entry⟧\n"
        "⟦ui:offer Show me the example⟧\n"
        "⟦ui:offer Book a slot⟧"
    )
    assert ClaudeAgentExecutor._strip_ui_directives(answer, frozenset({"highlight"})) == (
        "This example fits well here.\n⟦ui:highlight example-entry⟧"
    )
    # Everything declared: the answer passes byte for byte.
    assert ClaudeAgentExecutor._strip_ui_directives(answer, frozenset({"highlight", "offer"})) == answer


def test_strip_drops_undeclared_offer_even_before_an_allowed_highlight():
    answer = "Text.\n⟦ui:offer Show me more⟧\n⟦ui:highlight example-entry⟧"
    assert ClaudeAgentExecutor._strip_ui_directives(answer, frozenset({"highlight"})) == (
        "Text.\n⟦ui:highlight example-entry⟧"
    )


def test_streaming_withholds_an_in_flight_undeclared_directive():
    allowed = frozenset({"highlight"})
    snap = "Text.\n⟦ui:highlight example-entry⟧\n⟦ui:off"
    assert ClaudeAgentExecutor._filter_streaming_answer(snap, allowed) == (
        "Text.\n⟦ui:highlight example-entry⟧"
    )
    snap = "Text.\n⟦ui:highlight example-entry⟧\n⟦ui:offer More on the migra"
    assert ClaudeAgentExecutor._filter_streaming_answer(snap, allowed) == (
        "Text.\n⟦ui:highlight example-entry⟧"
    )
    # A complete, allowed directive is not an in-flight fragment.
    snap = "Text.\n⟦ui:highlight example-entry⟧"
    assert ClaudeAgentExecutor._filter_streaming_answer(snap, allowed) == snap


async def _execute_with(runtime_context, events) -> list:
    executor = ClaudeAgentExecutor(_FakeStreamingRunner(events))
    context = SimpleNamespace(
        message=_message(runtime_context),
        current_task=None,
        context_id="ctx-1",
        task_id="task-1",
    )
    queue = _RecordingQueue()
    await executor.execute(context, queue)
    return queue.events


_OFFER_EVENTS = [
    {"kind": "delta", "text": "The owner validated data migrations."},
    {"kind": "delta", "text": "The owner validated data migrations.\n⟦ui:highlight example-entry⟧\n⟦ui:offer More on migr"},
    {
        "kind": "delta",
        "text": (
            "The owner validated data migrations.\n⟦ui:highlight example-entry⟧\n"
            "⟦ui:offer More on migration checks⟧"
        ),
    },
    {
        "kind": "answer",
        "text": (
            "The owner validated data migrations.\n"
            "⟦ui:highlight example-entry⟧\n"
            "⟦ui:offer More on migration checks⟧\n"
            "⟦ui:offer Book a call⟧"
        ),
    },
]


def _completed_text(events) -> str:
    completed = [
        e for e in events
        if hasattr(e, "status") and e.status.state == TaskState.TASK_STATE_COMPLETED
    ]
    assert completed, "expected a completed status event"
    return completed[-1].status.message.parts[0].text


def test_execute_with_old_widget_block_keeps_highlight_and_drops_offers_everywhere():
    events = asyncio.run(_execute_with(_OLD_WIDGET_RC, _OFFER_EVENTS))
    for event in events:
        for text in _artifact_texts(event) or []:
            assert "⟦ui:offer" not in text, f"undeclared offer reached the old widget: {text!r}"
    final = _completed_text(events)
    assert "⟦ui:offer" not in final
    assert final == "The owner validated data migrations.\n⟦ui:highlight example-entry⟧"


def test_execute_with_highlight_only_declaration_drops_offers():
    rc = {"page": "/en", "ui_capabilities": ["highlight"]}
    events = asyncio.run(_execute_with(rc, _OFFER_EVENTS))
    for event in events:
        for text in _artifact_texts(event) or []:
            assert "⟦ui:offer" not in text
    assert _completed_text(events).endswith("⟦ui:highlight example-entry⟧")


def test_execute_with_new_widget_block_keeps_offers():
    events = asyncio.run(_execute_with(_NEW_WIDGET_RC, _OFFER_EVENTS))
    final = _completed_text(events)
    assert "⟦ui:offer More on migration checks⟧" in final
    assert "⟦ui:offer Book a call⟧" in final


def test_streaming_withholds_an_in_flight_directive_behind_a_trailing_newline():
    # The in-flight check looks at the last non-blank line, as before the rewrite.
    snap = "Text.\n⟦ui:off\n"
    assert ClaudeAgentExecutor._filter_streaming_answer(snap) == "Text."


def test_shed_load_when_concurrency_slots_busy_emits_failed_not_completed():
    # When all concurrency slots are taken, a shed task must NOT end as COMPLETED
    # with the busy text (which callers mistake for an answer) (#640).
    async def _test():
        runner = _FakeStreamingRunner([{"kind": "answer", "text": "Real answer."}])
        executor = ClaudeAgentExecutor(
            runner, max_concurrency=1, busy_retry_after_s=7.5
        )
        # Satiate the sole concurrency slot
        await executor._concurrency.acquire()

        context = SimpleNamespace(
            message=_message("Hello"),
            current_task=None,
            context_id="ctx-busy",
            task_id="task-busy",
        )
        queue = _RecordingQueue()
        await executor.execute(context, queue)

        # Release the lock for cleanup
        executor._concurrency.release()

        assert queue.events, "expected status update event for shed task"
        event = queue.events[-1]
        assert event.status.state == TaskState.TASK_STATE_FAILED
        assert event.status.state != TaskState.TASK_STATE_COMPLETED
        msg = event.status.message
        assert msg.parts[0].text == executor._msg["busy"]
        assert dict(msg.metadata) == {"reason": "busy", "retry_after_s": 7.5}

    asyncio.run(_test())


def test_slot_wait_timeout_recovers_if_slot_frees():
    # With slot_wait_timeout_s > 0, an incoming task waits and proceeds if a slot frees (#640).
    async def _test():
        runner = _FakeStreamingRunner([{"kind": "answer", "text": "Answer after wait."}])
        executor = ClaudeAgentExecutor(
            runner, max_concurrency=1, slot_wait_timeout_s=1.0
        )
        await executor._concurrency.acquire()

        async def _delayed_release():
            await asyncio.sleep(0.05)
            executor._concurrency.release()

        asyncio.create_task(_delayed_release())

        context = SimpleNamespace(
            message=_message("Question"),
            current_task=None,
            context_id="ctx-wait",
            task_id="task-wait",
        )
        queue = _RecordingQueue()
        await executor.execute(context, queue)

        completed = [e for e in queue.events if getattr(e, "status", None) and e.status.state == TaskState.TASK_STATE_COMPLETED]
        assert completed, "expected task to complete once slot freed"

    asyncio.run(_test())


def test_slot_wait_timeout_sheds_as_failed_if_slot_never_frees():
    # If no slot frees within slot_wait_timeout_s, it sheds as FAILED (#640).
    async def _test():
        runner = _FakeStreamingRunner([{"kind": "answer", "text": "Never reached."}])
        executor = ClaudeAgentExecutor(
            runner, max_concurrency=1, slot_wait_timeout_s=0.05, busy_retry_after_s=3.0
        )
        await executor._concurrency.acquire()

        context = SimpleNamespace(
            message=_message("Question"),
            current_task=None,
            context_id="ctx-shed-timeout",
            task_id="task-shed-timeout",
        )
        queue = _RecordingQueue()
        await executor.execute(context, queue)

        executor._concurrency.release()

        assert queue.events, "expected status update event"
        event = queue.events[-1]
        assert event.status.state == TaskState.TASK_STATE_FAILED
        assert dict(event.status.message.metadata) == {"reason": "busy", "retry_after_s": 3.0}

    asyncio.run(_test())

