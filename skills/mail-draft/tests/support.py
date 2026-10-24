"""A throwaway copy of the fixture Bridge per test, so no test writes into the tree."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bridge"


class BridgeCase(unittest.TestCase):
    """setUp copies the fixture and points MAIL_DRAFT_ROOT at the copy."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="mail-draft-test-")
        self.root = Path(self._tmp) / "bridge"
        shutil.copytree(FIXTURE, self.root)
        (self.root / "skills").mkdir(exist_ok=True)
        self._old = os.environ.get("MAIL_DRAFT_ROOT")
        os.environ["MAIL_DRAFT_ROOT"] = str(self.root)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("MAIL_DRAFT_ROOT", None)
        else:
            os.environ["MAIL_DRAFT_ROOT"] = self._old
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def cfg(self):
        from engine.config import load
        return load(self.root)

    def build(self, **kw):
        from engine.draft import Request, build
        kw.setdefault("subject", "Hello")
        kw.setdefault("body", "Body text.")
        return build(Request(**kw), self.cfg())


class FakeMail:
    """A stand-in for `subprocess.run` under engine.clients that answers by WHICH
    script runs, so a test can script a whole conversation with Mail (find the
    original, create the reply, read Drafts back) without Mail.

    `answers` maps a script kind to its answers in order; the last one repeats.
    Kinds: find, reply, create, verify, dedupe. Every call is kept in `calls`
    as (kind, argv, script) so a test can check what travelled where.
    """

    def __init__(self, **answers):
        self.answers = {k: list(v) if isinstance(v, (list, tuple)) else [v] for k, v in answers.items()}
        self.calls: list[tuple[str, list, str]] = []

    @staticmethod
    def kind(script: str) -> str:
        for marker, kind in (("-- mail-draft:find", "find"), ("-- mail-draft:reply", "reply"),
                             ("make new outgoing message", "create"), ("delete m", "dedupe")):
            if marker in script:
                return kind
        return "verify"

    def __call__(self, cmd, **kw):
        import subprocess
        script = kw.get("input", "")
        kind = self.kind(script)
        self.calls.append((kind, list(cmd), script))
        queue = self.answers.get(kind) or [""]
        out = queue.pop(0) if len(queue) > 1 else queue[0]
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def ran(self, kind: str) -> list[tuple[list, str]]:
        return [(argv, script) for k, argv, script in self.calls if k == kind]


def saved_draft(text: str, html: str = "", attachments: tuple[str, ...] = (),
                sender: str = "alex@example.com", subject: str = "Re: Plans") -> str:
    """The `source` of a saved draft as Mail would hand it back."""
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"], msg["Subject"] = sender, subject
    msg["In-Reply-To"] = "<orig-1@example.org>"
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name in attachments:
        msg.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename=name)
    return msg.as_string()
