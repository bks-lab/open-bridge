"""A reply draft in Apple Mail: find the original, answer it, keep the quote.

Hermetic: every osascript call is answered by tests.support.FakeMail, so no
Mail runs and no draft is created. What these tests pin down are the traps a
real reply ran into: `make new attachment` in a reply deleted the inserted
text together with the quote, a paste into whatever window was in front, and a
report that said "draft created" for a reply missing half of itself.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from unittest import mock

from tests.support import BridgeCase, FakeMail, saved_draft

ORIGINAL = "OK\n1\norig-1@example.org\nPat Example <pat@example.org>\nPlans\nFriday, 23 October 2026\nShall we meet on Friday?\nPat"
BODY = "Friday works for me, ten o'clock at the office."


class ReplyRef(BridgeCase):
    def test_message_id_and_subject_are_told_apart(self):
        from engine.clients.apple_mail import parse_reply_ref
        self.assertEqual(parse_reply_ref("<orig-1@example.org>"), ("id", "orig-1@example.org"))
        self.assertEqual(parse_reply_ref("orig-1@example.org"), ("id", "orig-1@example.org"))
        self.assertEqual(parse_reply_ref("Quarterly plans"), ("subject", "Quarterly plans"))

    def test_reply_subject_is_not_doubled(self):
        from engine.clients.apple_mail import reply_subject
        self.assertEqual(reply_subject("Plans"), "Re: Plans")
        self.assertEqual(reply_subject("Re: Plans"), "Re: Plans")
        self.assertEqual(reply_subject("AW: Plans"), "AW: Plans")


class FindOriginal(BridgeCase):
    def test_found_message_brings_sender_subject_and_excerpt(self):
        from engine.clients import apple_mail
        fake = FakeMail(find=ORIGINAL)
        with mock.patch("engine.clients.subprocess.run", side_effect=fake):
            orig = apple_mail.find_original("<orig-1@example.org>")
        self.assertEqual(orig.message_id, "orig-1@example.org")
        self.assertEqual(orig.address, "pat@example.org")
        self.assertEqual(orig.subject, "Plans")
        self.assertIn("Shall we meet", orig.excerpt)
        argv, _ = fake.ran("find")[0]
        self.assertEqual(argv[-2:], ["id", "orig-1@example.org"])

    def test_not_found_is_an_error_that_says_so(self):
        from engine.clients import apple_mail
        from engine.config import ConfigError
        with mock.patch("engine.clients.subprocess.run", side_effect=FakeMail(find="OK\n0")):
            with self.assertRaisesRegex(ConfigError, "no message in Mail matches"):
                apple_mail.find_original("Nothing like this")

    def test_several_matches_name_the_one_used(self):
        from engine.clients import apple_mail
        with mock.patch("engine.clients.subprocess.run",
                        side_effect=FakeMail(find=ORIGINAL.replace("OK\n1\n", "OK\n3\n"))):
            orig = apple_mail.find_original("Plans")
        self.assertEqual(orig.matches, 3)
        self.assertIn("newest of 3", orig.describe())


class ReplyScript(BridgeCase):
    """Static guards on the AppleScript: each line is a reply that went wrong."""

    def script(self):
        from engine.clients.apple_mail import REPLY
        return REPLY

    def test_no_make_new_attachment_in_a_reply(self):
        """`make new attachment ... after the last paragraph` deleted the
        inserted text and the quote of a reply; files go in by clipboard."""
        self.assertNotIn("make new attachment", self.script())
        self.assertIn("set the clipboard to (POSIX file", self.script())

    def test_content_is_never_replaced(self):
        """Setting the content of a reply replaces the quote with the body."""
        self.assertNotRegex(self.script(), r"set (html )?content of r\b")

    def test_every_paste_checks_the_front_window_first(self):
        s = self.script()
        self.assertEqual(s.count('keystroke "v" using command down'), 1, "one paste, inside pasteIfFront")
        handler = s[s.index("on pasteIfFront"):s.index("end pasteIfFront")]
        self.assertLess(handler.index("if not my replyInFront(s) then return false"),
                        handler.index('keystroke "v" using command down'))
        self.assertIn("frontmost is true", s)

    def test_reply_script_cannot_send(self):
        from engine.clients.apple_mail import FIND
        for script in (self.script(), FIND):
            self.assertNotRegex(script.lower(), r"\bsend\b")


class ReplyHandoff(BridgeCase):
    def handoff(self, saved: str, reply_answer: str = "OK|to=1|attachments=0|closed=no|from=alex@example.com",
                attach: bool = False, before: str = "0"):
        from engine.clients import apple_mail
        kw = {"to": ["pat@example.org"], "subject": "Re: Plans", "body": BODY, "reply": True}
        if attach:
            kw["attachments"] = [str(self.root / "cv.pdf")]
        d = self.build(**kw)
        orig = apple_mail.Original("orig-1@example.org", "Pat Example <pat@example.org>", "Plans",
                                   "Friday", "Shall we meet on Friday?", 1)
        fake = FakeMail(reply=reply_answer, verify=[before, "1\n" + saved])
        with mock.patch("engine.clients.subprocess.run", side_effect=fake):
            result = apple_mail.reply_handoff(d, Path(self._tmp) / "h", orig, show=True)
        return d, fake, result

    def complete(self, attachments=()):
        text = f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nAlex Example · Example Studio\n\nOn Friday, Pat wrote:\n> Shall we meet on Friday?\n"
        return saved_draft(text, attachments=attachments)

    def test_complete_reply_is_verified(self):
        d, fake, result = self.handoff(self.complete())
        self.assertTrue(result.ok, result.detail)
        self.assertTrue(result.verified)
        argv, script = fake.ran("reply")[0]
        self.assertIn("orig-1@example.org", argv)
        self.assertNotIn(BODY, " ".join(argv) + script)        # body travels as a file

    def test_reply_gets_no_dark_rules(self):
        self.handoff(self.complete())
        sent = (Path(self._tmp) / "h" / "body.html").read_text()
        self.assertNotIn("prefers-color-scheme", sent)

    def test_missing_quote_is_not_ok(self):
        saved = saved_draft(f"Hello,\n\n{BODY}\n\nAlex Example · Example Studio\n")
        _, _, result = self.handoff(saved)
        self.assertFalse(result.ok)
        self.assertIn("quote", result.detail)

    def test_missing_body_is_not_ok(self):
        saved = saved_draft("Alex Example\n\n> Shall we meet on Friday?\n")
        _, _, result = self.handoff(saved)
        self.assertFalse(result.ok)
        self.assertIn("text", result.detail)

    def test_missing_footer_is_not_ok(self):
        saved = saved_draft(f"Hello,\n\n{BODY}\n\n> Shall we meet on Friday?\n")
        _, _, result = self.handoff(saved)
        self.assertFalse(result.ok)
        self.assertIn("footer", result.detail)

    def test_missing_attachment_is_not_ok(self):
        _, _, result = self.handoff(self.complete(), attach=True,
                                    reply_answer="OK|to=1|attachments=1|closed=no|from=alex@example.com")
        self.assertFalse(result.ok)
        self.assertIn("cv.pdf", result.detail)

    def test_attachment_in_saved_reply_is_ok(self):
        _, _, result = self.handoff(self.complete(("cv.pdf",)), attach=True,
                                    reply_answer="OK|to=1|attachments=1|closed=no|from=alex@example.com")
        self.assertTrue(result.ok, result.detail)

    def test_window_not_in_front_pastes_nothing_and_says_so(self):
        d, fake, result = self.handoff(self.complete(), reply_answer="ERR|focus|closed=yes")
        self.assertFalse(result.ok)
        self.assertIn("not in front", result.detail)
        self.assertIn("nothing was saved", result.detail)
        self.assertEqual(len(fake.ran("verify")), 1, "no read-back of a reply that was never saved")

    def test_reply_not_saved_is_not_ok(self):
        from engine.clients import apple_mail
        d = self.build(to=["pat@example.org"], subject="Re: Plans", body=BODY, reply=True)
        orig = apple_mail.Original("orig-1@example.org", "pat@example.org", "Plans", "", "Shall we", 1)
        fake = FakeMail(reply="OK|to=1|attachments=0|closed=no|from=alex@example.com", verify=["0", "0"])
        with mock.patch("engine.clients.subprocess.run", side_effect=fake):
            result = apple_mail.reply_handoff(d, Path(self._tmp) / "h", orig)
        self.assertFalse(result.ok)
        self.assertFalse(result.verified)


class ReplyDraftWords(BridgeCase):
    def test_reply_keeps_the_subject_and_drops_the_masthead(self):
        d = self.build(to=["acme/ben"], subject="Re: Plans", body=BODY, reply=True,
                       attachments=[str(self.root / "cv.pdf")])
        self.assertEqual(d.subject, "Re: Plans")         # not "Application: Re: Plans"
        self.assertEqual(d.shell["title"], "")


class ReplyCli(BridgeCase):
    def cli(self, *argv, fake=None):
        from engine import cli
        out = io.StringIO()
        with mock.patch("engine.clients.subprocess.run", side_effect=fake or FakeMail()) as run, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue(), run

    def test_outlook_reply_is_refused_before_anything_runs(self):
        code, out, run = self.cli("compose", "--reply-to", "Plans", "--body", BODY, "--client", "outlook")
        self.assertEqual(code, 2)
        self.assertIn("not supported", out)
        run.assert_not_called()

    def test_eml_reply_is_refused(self):
        code, out, run = self.cli("compose", "--reply-to", "Plans", "--body", BODY, "--client", "eml")
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_profile_that_picks_outlook_is_refused_too(self):
        self.write("workflow/mail-profiles/everyday.yaml",
                   (self.root / "workflow/mail-profiles/everyday.yaml").read_text() + "client: outlook\n")
        code, out, _ = self.cli("compose", "--reply-to", "Plans", "--body", BODY,
                                fake=FakeMail(find=ORIGINAL))
        self.assertEqual(code, 2)
        self.assertIn("not supported", out)

    def test_reply_defaults_to_the_original_sender_and_subject(self):
        saved = saved_draft(f"Hello Pat,\n\n{BODY}\n\nAlex Example\n\n> Shall we meet on Friday?\n")
        fake = FakeMail(find=ORIGINAL, reply="OK|to=1|attachments=0|closed=no|from=alex@example.com",
                        verify=["0", "1\n" + saved])
        code, out, _ = self.cli("compose", "--reply-to", "<orig-1@example.org>", "--body", BODY,
                                "--client", "apple-mail", fake=fake)
        self.assertEqual(code, 0, out)
        self.assertIn("pat@example.org", out)
        self.assertIn("Subject:  Re: Plans", out)
        self.assertIn("reply in the Drafts folder", out)
        self.assertEqual(len(fake.ran("create")), 0, "a reply never creates a fresh message")

    def test_missing_to_without_reply_is_an_error(self):
        code, out, _ = self.cli("compose", "--subject", "Hi", "--body", "x", "--client", "none")
        self.assertEqual(code, 2)
        self.assertIn("--to", out)
