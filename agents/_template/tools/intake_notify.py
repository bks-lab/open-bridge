"""Fixed-recipient intake + best-effort owner-notify — the CORE scaffold.

Copy this into ``agents/<name>/tools/`` and override :func:`send` with your own
transport (MS Graph / SMTP / Signal / …). The runtime invokes it by absolute path:

    allowed_tools: "Read,Glob,Grep,Bash(python3 ${tools_dir}/intake_notify.py:*)"

and the agent calls it as::

    python3 <abs>/intake_notify.py --summary "…" [--detail "…"] [--field k=v …]

SAFETY CONTRACT (formalized in docs/representative-agent.md §4; locked by
agents/tests/test_intake_notify.py):

  1. No recipient argument. The recipient is read ONLY from ``AGENT_NOTIFY_TO`` —
     there is no --to/--recipient flag and no path from any CLI arg, agent
     instruction, or visitor-supplied field to the recipient. A prompt-injected
     visitor cannot redirect output.
  2. Capture is durable and FIRST. The request is appended to an owner-only
     (0600) local log before any notify attempt; the tool exits 0 even if the
     capture write fails (printing a fixed string, never the exception).
  3. Notify is best-effort and NEVER raises — a notify failure can never crash
     the agent turn.
  4. Unconfigured is LOUD, not silent — it stays capture-only and writes a WARN
     audit line naming the missing knob.
  5. The audit log is PII-free — outcome + a curated cause only; the visitor's
     text and the recipient address never appear in it.
  6. No autonomous outward action — this captures and notifies the OWNER; it
     never books, replies, or acts on a third party's behalf.
  7. CORE ships the pattern, not the transport — :func:`send` raises by default;
     the provider, its secret (from a vault at runtime, never env/argv), and the
     owner address live only in the USER instance.

Env (all optional; absent → safe capture-only):
  AGENT_NOTIFY_TO    Fixed recipient(s), comma-separated. The ONLY recipient source.
  AGENT_CAPTURE_DIR  Durable-capture directory (default ~/.local/state/bridge-agent).
  AGENT_NOTIFY_LOG   PII-free audit log path (default <capture-dir>/notify.log).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _capture_dir() -> Path:
    return Path(os.getenv("AGENT_CAPTURE_DIR", "~/.local/state/bridge-agent")).expanduser()


def _recipients() -> list[str]:
    """The ONE source of recipient. No CLI/agent/visitor path reaches this."""
    return [a.strip() for a in os.getenv("AGENT_NOTIFY_TO", "").split(",") if a.strip()]


def configured() -> bool:
    """True iff a notify can even be attempted. An instance that adds transport
    knobs (host, token-ref, …) ANDs them in via its own override; the base needs
    only a fixed recipient."""
    return bool(_recipients())


def capture(record: dict) -> None:
    """Durable, owner-only, append-only — the GUARANTEED path, runs before notify.

    On failure prints a FIXED string (never the exception, which could stringify
    the record and leak visitor text to stderr)."""
    try:
        d = _capture_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "intake.jsonl"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        try:
            f.chmod(0o600)
        except OSError:
            pass
    except Exception:
        print("capture failed", file=sys.stderr)  # fixed string, NEVER the exception


def send(subject: str, body: str) -> None:
    """THE SEAM. Deliver ``body`` to the fixed recipient over the instance's transport.

    MUST raise on failure (:func:`notify` is the layer that swallows). CORE ships
    no transport, so this raises — an instance override reads the recipient from
    :func:`_recipients` (NEVER a parameter) and sends via MS Graph / SMTP / Signal / …
    """
    raise NotImplementedError("override send() in your instance copy of this tool")


def log_notify(level: str, source: str, reason: str) -> None:
    """One PII-free line: '<ISO-UTC> <LEVEL> <source>: <reason>'. Best-effort.

    ``reason`` MUST be curated (outcome + safe cause) — never visitor subject/body."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        p = Path(os.getenv("AGENT_NOTIFY_LOG", str(_capture_dir() / "notify.log"))).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} {level} {source}: {reason}\n")
    except OSError:
        pass


def notify(subject: str, body: str, *, source: str) -> bool:
    """Best-effort choke point. Returns True iff delivered; NEVER raises.

    Unconfigured → capture-only + WARN. A send() failure → WARN + curated cause."""
    if not configured():
        log_notify("WARN", source, "not configured (AGENT_NOTIFY_TO unset) — captured, not sent")
        return False
    try:
        send(subject, body)
    except NotImplementedError:
        log_notify("WARN", source, "send() seam not implemented — captured, not sent")
        return False
    except Exception as exc:
        # curated cause ONLY — the type name, never str(exc) which could echo visitor text
        log_notify("WARN", source, f"send failed — {type(exc).__name__}")
        return False
    log_notify("INFO", source, "sent")
    return True


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Capture a request for the agent's owner and notify them. Sends nothing autonomously.",
    )
    ap.add_argument("--summary", required=True, help="one-line subject of the request")
    ap.add_argument("--detail", default="", help="optional longer body, in the visitor's words")
    ap.add_argument(
        "--field", action="append", default=[], metavar="KEY=VALUE",
        help="structured payload, repeatable (e.g. contact=…, topic=…). "
             "NONE of these is ever a recipient.",
    )
    ap.add_argument("--source", default="intake", help="audit tag for this caller")
    # There is deliberately NO --to / --recipient. Fixed-recipient is enforced by
    # ABSENCE — the strongest guarantee. See test_intake_notify.test_no_recipient_flag_exists.
    args = ap.parse_args(argv)

    fields: dict[str, str] = {}
    for kv in args.field:
        key, _, value = kv.partition("=")
        fields[key.strip()] = value.strip()

    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": args.summary,
        "detail": args.detail,
        "fields": fields,
    }
    capture(record)  # (1) durable, guaranteed, FIRST

    extra = "\n".join(f"{k}: {v}" for k, v in fields.items())
    body = args.detail + (("\n" + extra) if extra else "")
    sent = notify(args.summary, body, source=args.source)  # (2) best-effort, never raises

    # visitor-facing text keyed HONESTLY on the bool — only claim "forwarded" if it left
    print("Request recorded and forwarded to the owner." if sent
          else "Request recorded for the owner.")
    return 0  # ALWAYS 0 — the turn never fails here


def main() -> None:
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
