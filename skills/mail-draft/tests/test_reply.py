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

ORIGINAL = ("OK\n1\norig-1@example.org\nPat Example <pat@example.org>\nPlans\nFriday, 23 October 2026\n"
            "INBOX\nWork\nShall we meet on Friday?\nPat")
OK_REPLY = "OK|to=pat@example.org|cc=|bcc=|attachments=0|closed=no|from=alex@example.com"
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
        self.assertEqual((orig.mailbox, orig.account), ("INBOX", "Work"))
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
        self.assertLess(handler.index("if not my replyInFront(wid) then return false"),
                        handler.index('keystroke "v" using command down'))
        self.assertIn("frontmost is true", s)

    def test_reply_script_cannot_send(self):
        from engine.clients.apple_mail import FIND
        for script in (self.script(), FIND):
            self.assertNotRegex(script.lower(), r"\bsend\b")


class ReplyHandoff(BridgeCase):
    def handoff(self, saved: str, reply_answer=OK_REPLY, attach: bool = False, before: str = "0",
                body: str = BODY, excerpt: str = "Shall we meet on Friday?", verify=None, set_to=False,
                dedupe="0", **kw):
        from engine.clients import apple_mail
        kw.setdefault("to", ["pat@example.org"])
        kw.update(subject="Re: Plans", body=body, reply=True)
        if attach:
            kw["attachments"] = [str(self.root / "cv.pdf")]
        d = self.build(**kw)
        orig = apple_mail.Original("orig-1@example.org", "Pat Example <pat@example.org>", "Plans",
                                   "Friday", excerpt, 1, mailbox="INBOX", account="Work")
        fake = FakeMail(reply=reply_answer, verify=verify or [before, "1\n" + saved], dedupe=dedupe)
        with mock.patch("engine.clients.subprocess.run", side_effect=fake):
            result = apple_mail.reply_handoff(d, Path(self._tmp) / "h", orig, show=True, set_to=set_to)
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
        self.assertEqual(argv[-3:], ["keep", "INBOX", "Work"], "Mail's own recipients, the known mailbox")
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
                                    reply_answer=OK_REPLY.replace("attachments=0", "attachments=1"))
        self.assertFalse(result.ok)
        self.assertIn("cv.pdf", result.detail)

    def test_attachment_in_saved_reply_is_ok(self):
        _, _, result = self.handoff(self.complete(("cv.pdf",)), attach=True,
                                    reply_answer=OK_REPLY.replace("attachments=0", "attachments=1"))
        self.assertTrue(result.ok, result.detail)

    def test_window_not_in_front_pastes_nothing_and_says_so(self):
        d, fake, result = self.handoff(self.complete(), reply_answer="ERR|focus|closed=yes|saved=no")
        self.assertFalse(result.ok)
        self.assertIn("not in front", result.detail)
        self.assertIn("nothing was saved", result.detail)
        self.assertEqual(len(fake.ran("verify")), 1, "no read-back of a reply that was never saved")

    def test_reply_not_saved_is_not_ok(self):
        from engine.clients import apple_mail
        d = self.build(to=["pat@example.org"], subject="Re: Plans", body=BODY, reply=True)
        orig = apple_mail.Original("orig-1@example.org", "pat@example.org", "Plans", "", "Shall we", 1)
        fake = FakeMail(reply=OK_REPLY, verify=["0", "0"])
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
        saved = saved_draft(f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nAlex Example\n\n> Shall we meet on Friday?\n")
        fake = FakeMail(find=ORIGINAL, reply=OK_REPLY, verify=["0", "1\n" + saved])
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


class ReplyReadBack(BridgeCase):
    """The read-back looks for the text and the footer ABOVE the quote and for
    the quote BELOW it: in a thread the quote already holds the sender's name
    and signature, and a greeting can read like the original's first line."""

    def gaps(self, saved: str, body: str = BODY, excerpt: str = "Shall we meet on Friday?"):
        from engine.clients import apple_mail
        d = self.build(to=["pat@example.org"], subject="Re: Plans", body=body, reply=True)
        orig = apple_mail.Original("orig-1@example.org", "pat@example.org", "Plans", "", excerpt, 1)
        with mock.patch("engine.clients.subprocess.run",
                        side_effect=FakeMail(verify="1\n" + saved)):
            found = apple_mail.inspect("Re: Plans")
        return apple_mail.reply_gaps(d, orig, found[1])

    def test_footer_only_in_the_quote_is_missing(self):
        saved = saved_draft(f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nOn Friday, Pat wrote:\n"
                            "> Shall we meet on Friday?\n> Alex Example · Example Studio\n")
        self.assertIn("the footer", self.gaps(saved))

    def test_greeting_like_the_excerpt_is_no_quote(self):
        saved = saved_draft(f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nAlex Example · Example Studio\n")
        self.assertIn("the quote of the original", self.gaps(saved, excerpt="Hello,"))

    def test_half_pasted_body_is_missing_text(self):
        body = BODY + "\n\nPlease bring the signed contract along, we can go through it.\n\nSee you then."
        # Cut off before the last paragraph: the first and the last line of the
        # draft (greeting, closing) are there, only the end of the text is not.
        saved = saved_draft(f"Hello,\n\n{BODY}\n\nPlease bring the signed contract along, we can go through it.\n\n"
                            "Best,\nAlex\n\nAlex Example · Example Studio\n\nOn Friday, Pat wrote:\n> Shall we meet on Friday?\n")
        self.assertIn("the text", self.gaps(saved, body=body))

    def test_list_marker_is_not_needed(self):
        body = "- Friday works for me, ten o'clock at the office."
        saved = saved_draft("", html=("<div>Hello,</div><ul><li>Friday works for me, ten o'clock at the office.</li></ul>"
                                      "<div>Best,</div><div>Alex</div><div>Alex Example · Example Studio</div>"
                                      '<div>On Friday, Pat wrote:</div><blockquote type="cite">Shall we meet on Friday?</blockquote>'))
        self.assertEqual(self.gaps(saved, body=body), [])

    def test_html_quote_is_split_at_the_blockquote(self):
        html = (f"<div>Hello,</div><div>{BODY}</div><div>Best,</div><div>Alex</div>"
                "<div>Alex Example · Example Studio</div><div>On Friday, Pat wrote:</div>"
                '<blockquote type="cite"><div>Shall we meet on Friday?</div></blockquote>')
        self.assertEqual(self.gaps(saved_draft("", html=html)), [])

    def test_body_text_inside_the_quote_only_is_missing(self):
        html = ('<div>Alex Example · Example Studio</div><div>On Friday, Pat wrote:</div>'
                f'<blockquote type="cite"><div>Hello, {BODY} Best, Alex</div>'
                "<div>Shall we meet on Friday?</div></blockquote>")
        self.assertIn("the text", self.gaps(saved_draft("", html=html)))


class ReplyRecipients(BridgeCase):
    """--to replaces whom Mail answers, --cc and --bcc add to it, and both are
    read back: the report must not name recipients the draft does not have."""

    def handoff(self, reply_answer, saved_to="Sam <sam@example.net>", saved_cc="boss@example.net"):
        case = ReplyHandoff(methodName="handoff")
        case.root, case._tmp = self.root, self._tmp
        text = f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nAlex Example · Example Studio\n\nOn Friday, Pat wrote:\n> Shall we meet on Friday?\n"
        return case.handoff(saved_draft(text, to=saved_to, cc=saved_cc), reply_answer=reply_answer,
                            to=["sam@example.net"], cc=["boss@example.net"], set_to=True)

    def test_script_applies_to_cc_and_bcc(self):
        from engine.clients.apple_mail import REPLY
        for name in ("to.txt", "cc.txt", "bcc.txt"):
            self.assertIn(f'"/{name}"', REPLY)
        self.assertIn("delete every to recipient", REPLY)
        for kind in ("to", "cc", "bcc"):
            self.assertIn(f"make new {kind} recipient", REPLY)

    def test_given_to_reaches_the_reply(self):
        _, fake, result = self.handoff("OK|to=sam@example.net|cc=boss@example.net|bcc=|attachments=0|closed=no|from=alex@example.com")
        self.assertTrue(result.ok, result.detail)
        argv, _ = fake.ran("reply")[0]
        self.assertIn("set", argv)
        to = (Path(self._tmp) / "h" / "to.txt").read_text()
        self.assertEqual(to, "sam@example.net")

    def test_mail_keeping_its_own_to_is_not_ok(self):
        _, _, result = self.handoff("OK|to=pat@example.org|cc=boss@example.net|bcc=|attachments=0|closed=no|from=alex@example.com")
        self.assertFalse(result.ok)
        self.assertIn("To holds ['pat@example.org']", result.detail)

    def test_saved_to_that_differs_is_not_ok(self):
        _, _, result = self.handoff("OK|to=sam@example.net|cc=boss@example.net|bcc=|attachments=0|closed=no|from=alex@example.com",
                                    saved_to="pat@example.org")
        self.assertFalse(result.ok)
        self.assertIn("saved To", result.detail)

    def test_cc_lost_in_the_reply_is_not_ok(self):
        _, _, result = self.handoff("OK|to=sam@example.net|cc=|bcc=|attachments=0|closed=no|from=alex@example.com")
        self.assertFalse(result.ok)
        self.assertIn("cc lacks boss@example.net", result.detail)

    def test_cc_lost_in_the_saved_draft_is_not_ok(self):
        _, _, result = self.handoff("OK|to=sam@example.net|cc=boss@example.net|bcc=|attachments=0|closed=no|from=alex@example.com",
                                    saved_cc="")
        self.assertFalse(result.ok)
        self.assertIn("cc boss@example.net", result.detail)


class ReplyFailures(BridgeCase):
    """A reply that fails says what is left behind, never a traceback or half a draft."""

    def handoff(self, reply_answer, **kw):
        case = ReplyHandoff(methodName="handoff")
        case.root, case._tmp = self.root, self._tmp
        text = f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nAlex Example · Example Studio\n\nOn Friday, Pat wrote:\n> Shall we meet on Friday?\n"
        return case.handoff(saved_draft(text), reply_answer=reply_answer, **kw)

    def test_every_error_takes_the_way_out(self):
        from engine.clients.apple_mail import REPLY
        tail = REPLY[REPLY.index("    on error errMsg number errNum"):]
        self.assertIn('return my giveUp(wid, "error "', tail.split("end try")[0])

    def test_give_up_closes_this_reply_window(self):
        from engine.clients.apple_mail import REPLY
        handler = REPLY[REPLY.index("on giveUp"):REPLY.index("end giveUp")]
        self.assertIn("close (every window whose id is wid) saving no", handler)
        self.assertIn("my restoreClip()", handler)

    def test_front_window_is_told_by_id(self):
        from engine.clients.apple_mail import REPLY
        handler = REPLY[REPLY.index("on replyInFront"):REPLY.index("end replyInFront")]
        self.assertIn("return fid is wid", handler)

    def test_script_error_is_explained(self):
        _, fake, result = self.handoff("ERR|error -1719: System Events got an error: not allowed assistive access.|closed=yes|saved=no")
        self.assertFalse(result.ok)
        self.assertIn("nothing was saved", result.detail)
        self.assertIn("Accessibility", result.detail)
        self.assertEqual(len(fake.ran("verify")), 1)

    def test_error_after_save_says_a_copy_is_in_drafts(self):
        _, _, result = self.handoff("ERR|error -1728: boom|closed=yes|saved=yes")
        self.assertIn("WAS saved", result.detail)

    def test_timeout_is_a_message_not_a_traceback(self):
        import subprocess
        _, _, result = self.handoff(subprocess.TimeoutExpired("osascript", 180))
        self.assertFalse(result.ok)
        self.assertIn("may still be open", result.detail)

    def test_nonzero_exit_is_not_ok(self):
        _, _, result = self.handoff((1, "", "execution error: Mail got an error"))
        self.assertFalse(result.ok)
        self.assertIn("Mail got an error", result.detail)

    def test_two_copies_from_this_run_are_deduped(self):
        text = f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nAlex Example · Example Studio\n\nOn Friday, Pat wrote:\n> Shall we meet on Friday?\n"
        saved = saved_draft(text)
        _, fake, result = self.handoff(OK_REPLY, verify=["0", "2\n" + saved, "1\n" + saved], dedupe="1")
        self.assertTrue(result.ok, result.detail)
        self.assertIn("removed 1 duplicate", result.detail)
        self.assertEqual(len(fake.ran("dedupe")), 1)

    def test_find_timeout_is_a_config_error(self):
        import subprocess
        from engine.clients import apple_mail
        from engine.config import ConfigError
        fake = FakeMail(find=subprocess.TimeoutExpired("osascript", 120))
        with mock.patch("engine.clients.subprocess.run", side_effect=fake):
            with self.assertRaisesRegex(ConfigError, "did not answer.*nothing was created"):
                apple_mail.find_original("Plans")

    def test_no_osascript_is_a_reason(self):
        from engine.clients import apple_mail
        from engine.config import ConfigError
        with mock.patch("engine.clients.subprocess.run", side_effect=FileNotFoundError("osascript")):
            with self.assertRaisesRegex(ConfigError, "osascript is not available"):
                apple_mail.find_original("Plans")


class ReplyClientChoice(BridgeCase):
    def cli(self, *argv, fake=None):
        return ReplyCli.cli(self, *argv, fake=fake)

    def test_platform_default_eml_is_refused_before_mail_is_asked(self):
        with mock.patch("engine.draft.default_client", return_value="eml"):
            code, out, run = self.cli("compose", "--reply-to", "Plans", "--body", BODY)
        self.assertEqual(code, 2)
        self.assertIn("client eml", out)
        run.assert_not_called()

    def test_given_to_is_set_and_missing_to_is_kept(self):
        saved = saved_draft(f"Hello,\n\n{BODY}\n\nBest,\nAlex\n\nAlex Example\n\nOn Friday, Pat wrote:\n> Shall we meet on Friday?\n",
                            to="sam@example.net")
        fake = FakeMail(find=ORIGINAL, reply=OK_REPLY.replace("pat@example.org", "sam@example.net"),
                        verify=["0", "1\n" + saved])
        code, out, _ = self.cli("compose", "--reply-to", "Plans", "--to", "sam@example.net", "--body", BODY,
                                "--client", "apple-mail", fake=fake)
        self.assertEqual(code, 0, out)
        self.assertEqual(fake.ran("reply")[0][0][-3], "set")
