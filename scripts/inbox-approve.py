#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Owner approval through the inbox: an agent's held answer waits where everything else waits.

agents/_runtime/approval.py keeps a finished answer until its owner released it
and leaves HOW the owner is asked to a command. This is that command, for a
Bridge with an inbox. Declare it in an agent's agent.yaml:

    approval:
      command: ["python3", "/path/to/bridge/scripts/inbox-approve.py", "--sync"]
      timeout_sec: 3600

It reads the request from stdin, files it as an inbox item (kind draft, gate
only-you, urgency now: an answer leaving to someone else is the owner's call),
and waits until a person decided on that item:

    python3 scripts/inbox.py approve <id>                 -> {"decision": "approve"}
    python3 scripts/inbox.py approve <id> --text "..."    -> {"decision": "edit", "text": "..."}
    python3 scripts/inbox.py reject <id>   (or drop)      -> {"decision": "reject"}
    nobody decided before timeout_sec                     -> {"decision": "timeout"}, item dropped

--sync pushes the new item and, while waiting, fetches and takes only this
item's folder from the upstream, for an owner who decides on another machine.
It never rebases or stashes the working tree. Every request is its own item:
a second answer in the same task never meets the first answer's yes, and a
decided item is closed at once. The runtime fails closed on anything
else, so a crash here means the answer is not sent. Model: docs/inbox.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_inbox():
    spec = importlib.util.spec_from_file_location("inbox", Path(__file__).with_name("inbox.py"))
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("cannot load scripts/inbox.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("inbox", module)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _git(root: Path, *args: str, timeout: float) -> int:
    if timeout <= 0:
        return 1
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return 1


def decision_of(item) -> dict | None:
    for event in reversed(item.events):
        if event.verb == "approve":
            text = event.data.get("text")
            return {"decision": "edit", "text": text} if text else {"decision": "approve"}
        if event.verb in ("reject", "drop", "close"):
            return {"decision": "reject"}
    return None


def _clip(text: str, limit: int) -> str:
    """At most ``limit`` characters, cut between words: a question cut inside a word
    reads as a typo in the briefing (07.11.2026)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[:limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (head or text[:limit]) + "…"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="inbox-approve.py", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--poll", type=float, default=5.0, help="seconds between looks at the inbox")
    ap.add_argument("--sync", action="store_true", help="push the item, fetch the owner's decision")
    ap.add_argument("--by", default="agent-approval")
    args = ap.parse_args(argv)

    try:
        request = json.loads(sys.stdin.read())
        answer = str(request["answer"])
    except (ValueError, KeyError, TypeError) as exc:
        print(f"inbox-approve: unreadable request ({exc})", file=sys.stderr)
        return 2
    timeout = float(request.get("timeout_sec") or 3600)
    # Everything, git included, runs inside the owner's time. The runtime kills
    # this process shortly after it; the timeout path must still get to write
    # its drop, so it keeps a few seconds back for that.
    deadline = time.monotonic() + max(0.0, timeout - 5.0 if timeout > 10 else timeout)
    left = lambda: deadline - time.monotonic()  # noqa: E731
    peer = str(request.get("peer") or "a peer")

    inbox = _load_inbox()
    box = inbox.Inbox(args.root / "work" / "inbox", actor=args.by)
    # One item per request, never a dedup key: a second answer in the same task
    # must never meet the first answer's yes.
    item_id = box.add(
        source=f"agent-approval/{peer}", kind="draft", gate="only-you", urgency="now",
        summary=f"Answer to {peer} waits for your release: {_clip(str(request.get('question') or ''), 80)}",
        detail=f"Question:\n{request.get('question') or ''}\n\nDrafted answer:\n{answer}",
    )
    item_path = f"work/inbox/{item_id}"
    inbox_py = Path(__file__).with_name("inbox.py")

    def sync():
        if args.sync and left() > 0:
            try:
                subprocess.run([sys.executable, str(inbox_py), "--root", str(args.root), "--by", args.by, "sync"],
                               capture_output=True, timeout=max(1.0, min(60.0, left())))
            except subprocess.TimeoutExpired:
                pass

    sync()
    while left() > 0:
        if args.sync:
            # Fetch and take only THIS item's events from the upstream: the rest
            # of the working tree, a person's checkout, is never rebased or stashed.
            if _git(args.root, "fetch", "--quiet", timeout=min(30.0, left())) == 0:
                _git(args.root, "checkout", "@{u}", "--", item_path, timeout=min(10.0, left()))
        decided = decision_of(box.get(item_id))
        if decided:
            if decided["decision"] != "reject":
                box.close(item_id, note="answer released to the agent")
            sync()
            print(json.dumps(decided, ensure_ascii=False))
            return 0
        time.sleep(max(0.0, min(args.poll, left())))
    box.event(item_id, "drop", text="nobody released the answer in time")
    print(json.dumps({"decision": "timeout"}))
    sys.stdout.flush()
    sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
