"""The IMAP client: a draft stored on the mail server, chosen per sender and machine.

No test reaches a server. `FakeServer` stands in for imaplib: it keeps the
folders and messages of one account, and every connection a test opens talks to
the same server, so a read-back from a fresh connection sees what an earlier one
stored, exactly as a real account would.
"""

from __future__ import annotations

import contextlib
import imaplib
import io
import re
from email import message_from_bytes, policy
from pathlib import Path
from unittest import mock

from tests.support import BridgeCase

ACCOUNT = """\
mail:
  imap_accounts:
    - address: alex@example.com
      host: imap.example.com
      password_ref: keychain://mail-drafts-imap/alex@example.com
      use_on: [{use_on}]
"""


class FakeServer:
    """One IMAP account. Folders map a name to a list of raw messages."""

    def __init__(self, folders=None, password="right", flags=None):
        self.folders = folders if folders is not None else {"INBOX": [], "[Mail]/Drafts": []}
        self.flags = flags if flags is not None else {"[Mail]/Drafts": "\\Drafts"}
        self.password = password
        self.appended: list[tuple[str, str]] = []   # (mailbox as sent, flags)
        self.logins: list[tuple[str, str]] = []
        self.connections = 0
        self.drop_appends = False                    # a server that answers OK and keeps nothing

    def connect(self, host, port):
        self.connections += 1
        return FakeConnection(self, host, port)


class FakeConnection:
    def __init__(self, server, host, port):
        self.server, self.host, self.port = server, host, port
        self.selected = None

    @staticmethod
    def _name(mailbox: str) -> str:
        return mailbox[1:-1] if mailbox.startswith('"') and mailbox.endswith('"') else mailbox

    def login(self, user, password):
        self.server.logins.append((user, password))
        if password != self.server.password:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"logged in"]

    def list(self, *args):
        lines = []
        for name in self.server.folders:
            flag = self.server.flags.get(name, "")
            lines.append(f'({flag} \\HasNoChildren) "/" "{name}"'.replace("( ", "(").encode())
        return "OK", lines

    def append(self, mailbox, flags, date_time, message):
        name = self._name(mailbox)
        self.server.appended.append((mailbox, flags))
        if name not in self.server.folders:
            return "NO", [b"[TRYCREATE] no such folder"]
        if not self.server.drop_appends:
            self.server.folders[name].append(bytes(message))
        return "OK", [b"[APPENDUID 1 7] (Success)"]

    def select(self, mailbox, readonly=False):
        name = self._name(mailbox)
        if name not in self.server.folders:
            return "NO", [b"no such folder"]
        self.selected = name
        return "OK", [str(len(self.server.folders[name])).encode()]

    def search(self, charset, *criteria):
        assert criteria[:2] == ("HEADER", "Message-ID"), criteria
        wanted = criteria[2].strip('"')
        hits = [str(i + 1) for i, raw in enumerate(self.server.folders[self.selected])
                if message_from_bytes(raw, policy=policy.default)["Message-ID"] == wanted]
        return "OK", [" ".join(hits).encode()]

    def fetch(self, num, what):
        raw = self.server.folders[self.selected][int(num) - 1]
        return "OK", [(f"{num} (RFC822 {{{len(raw)}}}".encode(), raw), b")"]

    def logout(self):
        return "BYE", [b"bye"]


class Selection(BridgeCase):
    """Which drafts go to IMAP: the sender's account, on the machines it names."""

    def setUp(self):
        super().setUp()
        self.cv = str(self.root / "cv.pdf")

    def account(self, use_on="always-on"):
        self.write("bridge-config.yaml", ACCOUNT.format(use_on=use_on))

    def draft(self, machine="always-on", **kw):
        kw.setdefault("to", ["acme/anna"])
        kw.setdefault("attachments", [self.cv])
        with mock.patch("engine.clients.imap.machine_names", return_value={machine}):
            return self.build(**kw)

    def test_sender_with_an_account_goes_to_imap_on_a_named_machine(self):
        self.account()
        d = self.draft()
        self.assertEqual(d.client, "imap")
        self.assertTrue(any("imap" in x and "always-on" in x for x in d.decisions), d.decisions)

    def test_other_machine_keeps_the_client_it_had(self):
        self.account()
        self.assertNotEqual(self.draft(machine="laptop").client, "imap")

    def test_other_sender_keeps_the_client_it_had(self):
        self.account()
        d = self.draft(to=["sam"], attachments=[])   # the family profile, no sender address
        self.assertNotEqual(d.client, "imap")

    def test_all_means_every_machine(self):
        self.account(use_on="all")
        self.assertEqual(self.draft(machine="anywhere").client, "imap")

    def test_an_account_without_use_on_is_only_used_when_asked(self):
        self.write("bridge-config.yaml", ACCOUNT.replace("      use_on: [{use_on}]\n", ""))
        self.assertNotEqual(self.draft().client, "imap")
        self.assertEqual(self.draft(client="imap").client, "imap")

    def test_the_command_line_wins_over_the_machine(self):
        self.account()
        self.assertEqual(self.draft(client="eml").client, "eml")

    def test_a_reply_is_never_routed(self):
        self.account()
        self.assertNotEqual(self.draft(reply=True).client, "imap")

    def test_the_machine_beats_the_profile(self):
        self.account()
        self.write("workflow/mail-profiles/application.yaml",
                   (self.root / "workflow/mail-profiles/application.yaml").read_text(encoding="utf-8")
                   + "client: outlook\n")
        self.assertEqual(self.draft().client, "imap")

    def test_imap_without_an_account_for_the_sender_is_an_error(self):
        d = self.draft(client="imap")
        self.assertTrue(any("imap_accounts" in e and "alex@example.com" in e for e in d.errors), d.errors)

    def test_a_raw_password_is_refused_and_never_repeated(self):
        self.write("bridge-config.yaml", ACCOUNT.format(use_on="always-on").replace(
            "keychain://mail-drafts-imap/alex@example.com", "hunter2hunter2"))
        d = self.draft()
        self.assertTrue(any("password_ref" in e for e in d.errors), d.errors)
        self.assertFalse(any("hunter2" in e for e in d.errors + d.warnings + d.decisions))


class MachineNames(BridgeCase):
    """This machine is known by its host names and by the infra/remotes entry that names them."""

    def names(self, hostname="Box-2.local", local="Box-2", env=None):
        from engine.clients import imap
        return imap.machine_names(self.root, hostname=hostname, local_hostname=local, env=env or {})

    def test_host_names_in_lower_case(self):
        self.assertTrue({"box-2"} <= self.names())

    def test_a_remote_whose_hostname_matches_adds_its_id(self):
        self.write("infra/remotes/always-on.yaml", "hostname: Box-2\n")
        self.write("infra/remotes/other.yaml", "hostname: Elsewhere\n")
        self.write("infra/remotes/_template.yaml", "hostname: Box-2\n")
        names = self.names()
        self.assertIn("always-on", names)
        self.assertNotIn("other", names)
        self.assertNotIn("_template", names)

    def test_bridge_machine_names_it_outright(self):
        self.assertIn("studio", self.names(env={"BRIDGE_MACHINE": "Studio"}))


class Handoff(BridgeCase):
    """Store, then read back from a fresh connection: a draft is a draft when the folder shows it."""

    def setUp(self):
        super().setUp()
        self.write("bridge-config.yaml", ACCOUNT.format(use_on="all"))
        self.server = FakeServer()

    def handoff(self, password="right", **kw):
        from engine.clients import imap
        d = self.build(to=["acme/anna"], attachments=[str(self.root / "cv.pdf")], **kw)
        self.assertEqual(d.errors, [])
        return d, imap.handoff(d, self.root / ".handoff", cfg=self.cfg(),
                               connect=self.server.connect, password=password)

    def stored(self):
        return [message_from_bytes(raw, policy=policy.default) for raw in self.server.folders["[Mail]/Drafts"]]

    def test_the_draft_lands_in_the_folder_the_server_marks_drafts(self):
        d, result = self.handoff()
        self.assertTrue(result.ok, result.detail)
        self.assertTrue(result.verified)
        [msg] = self.stored()
        self.assertEqual(msg["Subject"], d.subject)
        self.assertIn("alex@example.com", msg["From"])
        self.assertEqual([p.get_filename() for p in msg.iter_attachments()], ["cv.pdf"])
        mailbox, flags = self.server.appended[0]
        self.assertEqual(mailbox, '"[Mail]/Drafts"')
        self.assertIn("\\Draft", flags)
        self.assertIn("[Mail]/Drafts", result.detail)
        self.assertIn("1 attachment", result.detail)

    def test_the_read_back_uses_a_fresh_connection(self):
        self.handoff()
        self.assertGreaterEqual(self.server.connections, 2)

    def test_a_configured_folder_wins(self):
        self.server.folders["Entwurf"] = []
        self.write("bridge-config.yaml", ACCOUNT.format(use_on="all") + "      drafts_folder: Entwurf\n")
        _, result = self.handoff()
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(len(self.server.folders["Entwurf"]), 1)

    def test_no_drafts_folder_is_a_reason_not_a_guess(self):
        self.server.flags = {}
        _, result = self.handoff()
        self.assertFalse(result.ok)
        self.assertIn("drafts_folder", result.detail)
        self.assertEqual(self.server.appended, [])

    def test_a_refused_login_is_named_and_the_password_is_not(self):
        _, result = self.handoff(password="wrong-secret-value")
        self.assertFalse(result.ok)
        self.assertIn("imap.example.com", result.detail)
        self.assertIn("refused", result.detail)
        self.assertNotIn("wrong-secret-value", result.detail)

    def test_a_server_that_keeps_nothing_is_not_a_draft(self):
        self.server.drop_appends = True
        _, result = self.handoff()
        self.assertFalse(result.ok)
        self.assertIs(result.verified, False)

    def test_an_unreachable_server_is_a_reason(self):
        def refuse(host, port):
            raise OSError("connection refused")
        from engine.clients import imap
        d = self.build(to=["acme/anna"], attachments=[str(self.root / "cv.pdf")])
        result = imap.handoff(d, self.root / ".handoff", cfg=self.cfg(), connect=refuse, password="right")
        self.assertFalse(result.ok)
        self.assertIn("imap.example.com", result.detail)

    def test_without_the_secrets_skill_the_reference_cannot_resolve(self):
        from engine.clients import imap
        d = self.build(to=["acme/anna"], attachments=[str(self.root / "cv.pdf")])
        result = imap.handoff(d, self.root / ".handoff", cfg=self.cfg(), connect=self.server.connect)
        self.assertFalse(result.ok)
        self.assertIn("secrets", result.detail)
        self.assertEqual(self.server.logins, [])

    def test_there_is_no_way_to_send(self):
        source = (Path(__file__).resolve().parents[1] / "engine" / "clients" / "imap.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"smtplib|SMTP|\.send\(|sendmail", source))


class Cli(BridgeCase):
    def test_compose_hands_an_imap_draft_over_and_reports_the_folder(self):
        self.write("bridge-config.yaml", ACCOUNT.format(use_on="all"))
        server = FakeServer()
        from engine import cli
        from engine.clients import imap
        real = imap.handoff

        def handoff(d, workdir, show=True, **kw):
            return real(d, workdir, show=show, cfg=kw["cfg"], connect=server.connect, password="right")

        out = io.StringIO()
        with mock.patch("engine.clients.imap.handoff", side_effect=handoff), contextlib.redirect_stdout(out):
            code = cli.main(["compose", "--to", "acme/anna", "--subject", "Hello", "--body", "Text.",
                             "--attach", str(self.root / "cv.pdf")])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("imap:", out.getvalue())
        self.assertIn("in the Drafts folder", out.getvalue())
        self.assertEqual(len(server.folders["[Mail]/Drafts"]), 1)

    def test_a_reply_through_imap_is_refused_by_name(self):
        from engine import cli
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["compose", "--reply-to", "anything", "--body", "Text.", "--client", "imap"])
        self.assertEqual(code, 2)
        self.assertIn("imap", err.getvalue())

    def test_validate_names_a_broken_account(self):
        self.write("bridge-config.yaml", "mail:\n  imap_accounts:\n    - address: alex@example.com\n"
                                         "      password_ref: plain-value\n")
        from engine import validate
        problems = " ".join(validate.run(self.root))
        self.assertIn("host", problems)
        self.assertIn("password_ref", problems)
        self.assertNotIn("plain-value", problems)
