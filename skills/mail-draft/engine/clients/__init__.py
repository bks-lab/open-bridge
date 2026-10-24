"""Hand a built draft to a mail client. Every client creates a draft; none sends.

The contract every client keeps, each clause paid for by a mail that went wrong:

- The body travels as a FILE the AppleScript reads as UTF-8, never as an argv
  element. A long HTML body in argv made Outlook create nothing at all while
  the script reported success.
- Counts come back from the SAME tell block that created the message.
  Asking a draft afterwards is unreliable (attachments read as 0).
- Every property is read into a variable before it is concatenated; reading
  one inside an `&` expression fails with -1700.
- A draft is a draft only when the Drafts folder counts it from a fresh
  process. `verify()` does that and the result is reported, not assumed.
- Nothing calls `send`. There is no code path to it in this package.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Handoff:
    ok: bool
    client: str
    detail: str
    verified: bool | None = None   # None = not checkable for this client


def answer_fields(out: str) -> dict[str, str]:
    """`OK|key=value|key=value` as a dict."""
    fields: dict[str, str] = {}
    for part in out.split("|")[1:]:
        key, _, value = part.partition("=")
        fields[key] = value
    return fields


def osascript(script: str, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run AppleScript text with PATHS as arguments. Never message content.

    No osascript (not a Mac) is an answer with a reason, not a traceback.
    """
    try:
        return subprocess.run(["osascript", "-", *args], input=script, capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(["osascript"], 127, "",
                                           "osascript is not available here (Apple Mail needs macOS)")


def write_inputs(d, workdir: Path, html: str | None = None) -> dict[str, str]:
    """Body and recipient lists as files, so argv carries only paths."""
    workdir.mkdir(parents=True, exist_ok=True)
    files = {
        "html": workdir / "body.html",
        "text": workdir / "body.txt",
        "subject": workdir / "subject.txt",
        "to": workdir / "to.txt",
        "cc": workdir / "cc.txt",
        "bcc": workdir / "bcc.txt",
        "attachments": workdir / "attachments.txt",
        "sender": workdir / "sender.txt",
    }
    files["html"].write_text(d.html if html is None else html, encoding="utf-8")
    files["text"].write_text(d.text, encoding="utf-8")
    files["subject"].write_text(d.subject, encoding="utf-8")
    files["to"].write_text("\n".join(r.address for r in d.to), encoding="utf-8")
    files["cc"].write_text("\n".join(r.address for r in d.cc), encoding="utf-8")
    files["bcc"].write_text("\n".join(r.address for r in d.bcc), encoding="utf-8")
    files["attachments"].write_text("\n".join(str(p) for p in d.attachments if p.is_file()), encoding="utf-8")
    files["sender"].write_text(d.sender or "", encoding="utf-8")
    return {k: str(v) for k, v in files.items()}
