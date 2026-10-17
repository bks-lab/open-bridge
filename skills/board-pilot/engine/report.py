"""The outward seam: the engine says out loud what it already writes to the board.

WHY THIS IS A SECOND SINK AND NOT A SECOND RENDERER
---------------------------------------------------
The engine reports through exactly one method (`Engine._emit`), and all eight
state-machine call sites land there: armed, stage pass, retry, rewind, reject,
park, gate, and the gate on the idempotency path. Everything here hangs off that
one seam, so an outward channel sees the WHOLE run or nothing, never the half a
stage script could see (`armed`, `park` and `gate` are authored by the engine and
no stage ever observes them; `duration_s`, `criteria_ref` and `evidence_dir` are
the parent process's observations).

Every value a sink prints comes from `record.row_fields`, the same function the
sticky board comment renders from. ONE source, two renderings, so the comment and
the channel cannot contradict each other. What that source refuses to expose is
the point of it: `result.notes` (argv + stderr of a crashed subprocess, so it can
reprint a secret), `item.body` (written by strangers on a public repo) and
`result.tokens` (hardcoded 0 on both real paths, so it would report a cost nobody
measured). Everything that does go out is scrubbed unconditionally. The record's
`scan: off` knob is about the sticky, which sits behind a fail-closed PR gate; an
outward wire has no such backstop.

TWO SHAPES, ONE PORT
--------------------
A channel and an end-of-run summary are the same event stream with two send
times, so they are the same port with two flush policies:

  * `mode: stream` sends per event, as it happens;
  * `mode: digest` collects and sends when it itself sees one of its `flush_on`
    events.

The engine knows neither. It calls `emit` at all eight points and stops thinking
about it. That is the same division the Recorder already demonstrates, where `armed`
opens a new sticky and every other event edits the existing one without the
caller ever hearing about the distinction.

THE DIGEST SPOOLS TO DISK, AND THAT IS NOT AN OPTIMISATION
----------------------------------------------------------
One process is exactly one tick; the launchd timer is the loop. A collector held
in memory loses every row of every tick that did not itself reach the gate, which
is all of them but the last. So the spool is a file under `state_dir`, beside
`prev.json`, `budget.json`, `attempts.json` and `locks/`.

WHAT IS NOT IN THIS MODULE, ON PURPOSE
--------------------------------------
No channel name, no address, no recipient, no threshold. board-pilot is
`scope: core` and ships into the repo it drives. A target declares a `type` and
the NAME of an environment variable; the address lives in the environment, and
the instance knowledge lives in the project YAML.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .card import build_card
from .record import clean_cell, iso_now, row_fields

# A tick must never hang on a wire. Whatever the sink does, it does it inside this
# many seconds or it raises, and a raise here is caught by `emit_guarded`, which
# is what keeps a slow channel from becoming a stalled pipeline.
_SEND_TIMEOUT_S = 10

# The spool file name is derived from the item id, which comes off the board. It is
# never used as a path component raw.
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _slug(value: str) -> str:
    return _UNSAFE.sub("_", str(value or "item"))[:120] or "item"


def _head(item, project: str) -> str:
    """Who this message is about. The sticky does not need this: it hangs on the
    issue, so its anchor IS its attribution. A free-standing message has none."""
    ref = f"#{item.issue_number}" if getattr(item, "issue_number", None) else getattr(item, "id", "?")
    return " · ".join(p for p in (project, ref) if p)


def _line(fields: dict) -> str:
    """The six values as one row. Same order and same separator as the sticky's
    table, so a reader who has seen one recognises the other on sight."""
    return "| " + " | ".join(fields[k] for k in ("when", "stage", "kind", "criteria", "took", "outcome")) + " |"


# === transports: the wire, and nothing else ================================


class FileTransport:
    """Appends to a local file. No network, no credential, useful as a rehearsal
    target for a channel that is not wired yet."""

    def __init__(self, path, armed=True):
        self.path = Path(path).expanduser()
        # A file target has no arming gate: it opens no socket and reaches nobody.
        # The attribute exists so every transport answers the same question.
        self.armed = armed

    def send(self, text: str, card=None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(text.rstrip("\n") + "\n")
            if card is not None:
                # The rehearsal artefact: the exact payload a webhook would post,
                # one line, so a run can be inspected without anything being sent.
                fh.write(json.dumps(card, ensure_ascii=False) + "\n")


class WebhookTransport:
    """POSTs `{"text": …}` to the address held by an environment VARIABLE.

    The variable name is config; the address is not. Nothing is read at
    construction: the engine builds its sinks during `__init__`, next to the board
    preflights, and a sink that resolved a secret there would fail engine start on
    a box where the variable is merely not exported yet.
    """

    def __init__(self, url_env: str, timeout: int = _SEND_TIMEOUT_S, armed: bool = False,
                 out=None):
        self.url_env = url_env
        self.timeout = timeout
        # DISARMED by default, and the default is the point: a target that is merely
        # declared, or a caller that forgot the flag, rehearses. Sending is something
        # somebody asks for once, per run, on the command line.
        self.armed = armed
        # The dry-run dump goes to STDERR because stdout is the launchd ledger — one
        # line of JSON per tick — and a multi-line card would make it ungreppable.
        self._out = out

    def send(self, text: str, card=None) -> None:
        import urllib.request  # lazy: import cost only on a real send
        from urllib.error import HTTPError, URLError

        payload = card if card is not None else {"text": text}
        if not self.armed:
            # Print the PAYLOAD and the NAME of the variable. Never the address: what
            # lands on this stream lands in a log, and on stage possibly on a wall.
            print(
                f"board-pilot: report dry-run (${self.url_env} not read, nothing sent): "
                + json.dumps(payload, ensure_ascii=False),
                file=self._out or sys.stderr,
            )
            return

        url = os.environ.get(self.url_env)
        if not url:
            raise RuntimeError(
                f"${self.url_env} is not set. The report target names the variable, "
                f"the environment holds the address, and this environment does not"
            )
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            # Resolved through the module, not bound at import: a test that replaces
            # `urllib.request.urlopen` must actually reach this call, or the arming
            # gate is measured against a function nothing uses.
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 300:
                    raise RuntimeError(f"report webhook answered HTTP {resp.status}")
        except HTTPError as e:
            raise RuntimeError(f"report webhook answered HTTP {e.code}") from e
        except URLError as e:
            # Never let the reason carry the URL onward: it lands in the ledger, and the
            # ledger is a comment on a PUBLIC issue. `e.reason` is not a fixed shape: for
            # an SSL or proxy failure it routinely carries the full request URL, and the
            # URL is the credential here, because the webhook address IS the secret.
            # So only the CLASS of the failure travels, never its text. The class is what
            # an operator acts on ("unreachable" versus "refused"); the text only ever
            # repeated what we already knew, plus the one thing that must not leave.
            kind = type(e.reason).__name__ if e.reason is not None else "unknown"
            raise RuntimeError("report webhook unreachable: " + kind) from e


class ExternalSink:
    """A sink the CONFIG named, wrapped so `events:` means what it means everywhere.

    The wrapper is not ceremony. Without it, `events:` would be a knob that works
    for a webhook and a file and silently does nothing for exactly one target type,
    which is the same class of bug as an ignored key. The inner object is whatever
    the instance's factory returned; this engine knows nothing about it beyond the
    one method it calls.

    `name` is carried so the guarded emit can name it in the ledger. A sink that
    fails anonymously tells the operator that "a report failed" and nothing else.
    """

    def __init__(self, name: str, inner, events):
        self.name = name
        self.inner = inner
        self.events = tuple(events)

    def emit(self, event, item, *, stage=None, result=None, **fields) -> None:
        if event not in self.events:
            return
        self.inner.emit(event, item, stage=stage, result=result, **fields)


def _build_external(target):
    """Call the factory and check the one thing this engine needs from the result."""
    from .config import resolve_sink_factory

    where = f"report.targets[{target.name}]"
    factory = resolve_sink_factory(target.factory, where)
    sink = factory(**dict(target.options or {}))
    if not hasattr(sink, "emit") or not callable(sink.emit):
        raise ValueError(
            f"{where}.factory: {target.factory!r} returned {type(sink).__name__}, which has no "
            f"callable `emit`. A sink without `emit` would swallow the whole run in silence"
        )
    return ExternalSink(target.name, sink, target.events)


def _build_module_transport(target, armed=False):
    """A transport the CONFIG names, keeping this engine's own card.

    The difference from `type: python` is which half is replaced. A python sink
    takes over the whole rendering and gets the raw event; a module transport
    takes over only delivery, so `_Base` still builds the line and the adaptive
    card and hands both over. That matters whenever the destination wants
    exactly the card a webhook would get but reached some other way: a channel
    that threads replies under one post, for instance, where the transport has
    to remember the first message id but the card is unchanged.

    Rebuilding the card inside an instance sink would fork the renderer, and a
    forked renderer drifts on the first label somebody edits.

    `armed` is passed on rather than enforced here: only the transport knows
    what a rehearsal means for its destination, and a gate applied twice in two
    places is a gate nobody can reason about.
    """
    from .config import resolve_sink_factory

    where = f"report.targets[{target.name}]"
    factory = resolve_sink_factory(target.factory, where)
    transport = factory(armed=armed, **dict(target.options or {}))
    if not hasattr(transport, "send") or not callable(transport.send):
        raise ValueError(
            f"{where}.factory: {target.factory!r} returned {type(transport).__name__}, which has no "
            f"callable `send`. A transport without `send` would swallow every message in silence"
        )
    return transport


def _transport_for(target, armed=False):
    if target.type == "webhook":
        return WebhookTransport(target.url_env, armed=armed)
    if target.type == "file":
        return FileTransport(target.path)
    if target.type == "module":
        return _build_module_transport(target, armed=armed)
    raise ValueError(f"report target {target.name!r}: unknown type {target.type!r}")


_TRANSPORTS = {"webhook": _transport_for, "file": _transport_for, "module": _transport_for}


# === the two shapes ========================================================


class _Base:
    """Shared plumbing: the event filter, and the one line renderer.

    `events` is this target's OWN filter, never the record's. A sink wired to
    `RecordConfig.enabled`/`.events` goes quiet the day somebody switches the
    sticky off, which puts two unrelated decisions on one switch.
    """

    def __init__(self, *, name, transport, events, status_field="Status",
                 pipeline_field="Pipeline", project="", chain=(), card=None, now=None):
        self.name = name
        self.transport = transport
        self.events = tuple(events)
        self.status_field = status_field
        self.pipeline_field = pipeline_field
        self.project = project
        # The engine's own stage chain, handed down from the config it runs. The card
        # counts with it, so the count has exactly one source and no label carries it.
        self.chain = tuple(chain or ())
        self.card = card
        self._now = now

    def _fields(self, event, item, stage, result, fields) -> dict:
        """The six values, from the SAME function the sticky renders from.

        Not a private derivation that happens to agree today: `row_fields` is
        imported and called, so a change to the source moves both renderings, and a
        test can measure that by moving the source.
        """
        return row_fields(
            event, item, stage, result, fields,
            when=iso_now(self._now),
            status_field=self.status_field,
            pipeline_field=self.pipeline_field,
            # ALWAYS redact. `record.scan` is a knob about the board comment,
            # which sits behind a fail-closed PR gate; an outward wire has no
            # backstop behind it at all.
            scan="redact",
        )

    def _render(self, event, item, stage, result, fields) -> str:
        return _line(self._fields(event, item, stage, result, fields))

    def _incident(self, item) -> str:
        """The band, in order: what the config SAYS, what the environment HOLDS, the
        item itself.

        The middle step is the one that matters in practice: the id is minted by
        whatever raised the alarm, and the engine is spawned with it in its
        environment. Written into the YAML instead, the FIRST incident would appear
        on every later run's cards, correctly rendered and wrong. An unset variable
        falls through to the item reference rather than printing the variable name
        or the word None, both of which look like a value on a projector.
        """
        if self.card.incident:
            return self.card.incident
        if self.card.incident_env:
            value = os.environ.get(self.card.incident_env, "").strip()
            if value:
                return value
        return _head(item, "")

    def _card(self, event, item, stage, row, values=None) -> dict | None:
        """The second rendering of the SAME row. None when no `card:` is declared —
        which is the whole no-config story: the transport is then called with one
        argument, exactly as before this existed."""
        if self.card is None:
            return None
        return build_card(
            event,
            incident=self._incident(item),
            # The title is board text a human (or anyone with write access) typed,
            # so it is scrubbed and flattened like every other rendered value,
            # always redacted for the same reason as `_fields` above. An empty
            # title stays empty rather than becoming clean_cell's dash.
            title=clean_cell(title, scan="redact") if (title := getattr(item, "title", "") or "") else "",
            chain=self.chain,
            current=getattr(stage, "id", None),
            fields=row,
            labels=self.card.labels,
            url=getattr(item, "url", "") or "",
            sender=self.card.sender,
            item_ref=_head(item, ""),
            links=self.card.links,
            words=self.card.words,
            # Stage ids in the viewer's language, for the journey line only.
            # Kept apart from `words` on purpose: see card.journey.
            names=self.card.stage_names,
            # The event's OWN extra fields, the only thing a link may interpolate
            # from. `pr` exists on a gate and nowhere else, which is exactly why a
            # link with no value is dropped instead of rendered empty.
            values=values or {},
        )

    def _deliver(self, text, card) -> None:
        """One argument when there is no card, two when there is.

        A wire written before cards existed keeps working: it is never handed an
        argument it has no parameter for.
        """
        if card is None:
            self.transport.send(text)
        else:
            self.transport.send(text, card=card)


class StreamReporter(_Base):
    """One message per event, while the run is running."""

    def emit(self, event, item, *, stage=None, result=None, **fields) -> None:
        if event not in self.events:
            return
        row = self._fields(event, item, stage, result, fields)
        self._deliver(f"{_head(item, self.project)} {_line(row)}",
                      self._card(event, item, stage, row, values=fields))


class DigestReporter(_Base):
    """Collects the run and sends ONE message when it sees a `flush_on` event.

    The spool is per target and per item, under `state_dir`, because a tick is a
    process. On a send failure the spool is deliberately NOT cleared: nothing went
    out, so the next flush event re-sends the whole run rather than reporting a
    truncated one.
    """

    def __init__(self, *, flush_on, state_dir, **kw):
        super().__init__(**kw)
        self.flush_on = tuple(flush_on)
        self.spool_dir = Path(state_dir) / "report" / _slug(self.name)

    def spool_path(self, item) -> Path:
        return self.spool_dir / f"{_slug(getattr(item, 'id', ''))}.log"

    def emit(self, event, item, *, stage=None, result=None, **fields) -> None:
        if event not in self.events:
            return
        spool = self.spool_path(item)
        spool.parent.mkdir(parents=True, exist_ok=True)
        row = self._fields(event, item, stage, result, fields)
        if event == "armed":
            # THE RUN STARTS HERE, so the collector starts here too. Clearing only on
            # flush covers the run that ends; it does not cover the run that stops —
            # a human dragging the card to Done, a box rebooting mid-chain — and a
            # tick is a process, so that spool survives on disk. The next run for the
            # same item would then open its summary with a stranger's rows, dated
            # whenever the abandoned run happened to die. `w` truncates; the ARM row
            # itself is the first line of the new run.
            spool.write_text(_line(row) + "\n", encoding="utf-8")
        else:
            with spool.open("a", encoding="utf-8") as fh:
                fh.write(_line(row) + "\n")
        if event not in self.flush_on:
            return
        rows = [ln for ln in spool.read_text(encoding="utf-8").splitlines() if ln.strip()]
        head = _head(item, self.project)
        count = f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"
        self._deliver("\n".join([f"{head} · {count}", *rows]),
                      self._card(event, item, stage, row, values=fields))
        spool.unlink(missing_ok=True)          # only after the send actually returned


_SHAPES = {"stream": StreamReporter, "digest": DigestReporter}


def build_reporters(targets, *, state_dir, status_field="Status", pipeline_field="Pipeline",
                    project="", chain=(), armed=False, transports=None, now=None) -> list:
    """Build one reporter per ENABLED target. No targets → an empty list.

    That empty list is the whole no-config story: `Engine._emit` iterates it, an
    empty iteration calls nothing, and a project that never declared `report:`
    behaves byte for byte as it did before this module existed, with no warning to
    read and no switch to find.

    `transports` maps a target type to a factory, so a test drives the seam with a
    double and this module never opens a socket on its own account.

    `armed` is FALSE unless a caller says otherwise, and the default is what makes
    the gate real: the engine builds its own sinks in `__init__` and knows nothing
    about command lines, so every path that is not the CLI's explicit `--report-send`
    rehearses. `chain` is the engine's stage list; the card counts with it.
    """
    factories = transports or _TRANSPORTS
    built = []
    for t in targets or ():
        if not t.enabled:
            continue
        if t.type == "python":
            # The one target type whose sink this engine did not write. It has no
            # transport and no renderer: the instance's own object IS both, and the
            # only thing carried over from here is the `events:` filter, so the key
            # means the same for every type.
            built.append(_build_external(t))
            continue

        factory = factories.get(t.type)
        if factory is None:
            raise ValueError(f"report target {t.name!r}: no transport for type {t.type!r}")
        kw = {
            "name": t.name,
            "transport": factory(t, armed),
            "events": t.events,
            "status_field": status_field,
            "pipeline_field": pipeline_field,
            "project": project,
            "chain": chain,
            "card": t.card,
            "now": now,
        }
        if t.mode == "digest":
            kw.update(flush_on=t.flush_on, state_dir=state_dir)
        built.append(_SHAPES[t.mode](**kw))
    return built
