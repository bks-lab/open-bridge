"""IMAP: the draft is stored in the account's Drafts folder on the mail server.

No mail program takes part. That matters on a machine nobody sits at: a script
that drives Apple Mail needs the person to allow it once, on that screen, and
the allowance belongs to the exact interpreter that asked, so an update of that
interpreter takes it away again without a word. A draft stored over IMAP needs
none of that, and because it lives on the server it shows up on every device
that has the account, ready to be read and sent from there.

Which drafts take this way is configuration, never a guess
(`bridge-config.yaml`, `mail.imap_accounts`): an account names the sender
address it holds drafts for and the machines (`use_on`) where drafts from that
address go to it. Everywhere else the client stays what it was.

The password is a reference (`keychain://...`, `1password://...`), resolved by
the secrets skill at the moment of the login and never printed, never written
into the bundle, never part of a message this module returns.

IMAP can store a message; it cannot send one. This module talks to no
outgoing mail server and has no code path to one.
"""

from __future__ import annotations

import base64
import hashlib
import imaplib
import importlib
import importlib.util
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from email import message_from_bytes, policy
from email.utils import getaddresses, parseaddr
from pathlib import Path

from . import Handoff

TIMEOUT = 30
#: Searches before a stored draft counts as missing: some servers index a
#: fresh message a moment after they answered OK.
READ_BACK_ATTEMPTS = 4
#: A reference names a store and an entry; a value has no scheme.
REFERENCE = re.compile(r"^[a-z][a-z0-9+.-]*://\S+$")
LIST_LINE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>.+)$')


# -- which drafts ------------------------------------------------------------

def sender_address(sender: str) -> str:
    return parseaddr(sender or "")[1].strip().lower()


def accounts(cfg) -> list:
    raw = cfg.get("imap_accounts") or []
    return raw if isinstance(raw, list) else []


def account_for(cfg, sender: str) -> dict | None:
    """The account that holds drafts for this sender address, if one does."""
    address = sender_address(sender)
    if not address:
        return None
    for account in accounts(cfg):
        if isinstance(account, dict) and str(account.get("address") or "").strip().lower() == address:
            return account
    return None


def account_problems(account: dict) -> list[str]:
    """What keeps this account from being used. Never repeats a value."""
    problems = []
    if not str(account.get("address") or "").strip():
        problems.append("address is missing (the sender this account holds drafts for)")
    if not str(account.get("host") or "").strip():
        problems.append("host is missing (the IMAP server, e.g. imap.example.org)")
    ref = str(account.get("password_ref") or "").strip()
    if not ref:
        problems.append("password_ref is missing (a reference such as keychain://<service>/<account>)")
    elif not REFERENCE.match(ref):
        problems.append("password_ref is not a reference: write keychain://<service>/<account> "
                        "(or another scheme from rules/secret-placement.md), never the password itself")
    port = account.get("port", 993)
    if not isinstance(port, int) or not 0 < port < 65536:
        problems.append("port must be a number (993 for IMAP over TLS)")
    use_on = account.get("use_on", [])
    if not isinstance(use_on, (list, str)):
        problems.append("use_on must be a list of machine names, or [all]")
    return problems


def _local_hostname() -> str:
    if sys.platform != "darwin":
        return ""
    try:
        done = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def machine_names(root: Path, *, hostname: str | None = None, local_hostname: str | None = None,
                  env=None) -> set[str]:
    """Every name this machine answers to, in lower case.

    $BRIDGE_MACHINE (comma separated), the host name, on macOS the local host
    name, and the id of each `infra/remotes/<id>.yaml` whose `hostname:` is one
    of those, so `use_on` can say the name the rest of the Bridge uses.
    """
    env = os.environ if env is None else env
    raw = str(env.get("BRIDGE_MACHINE") or "").split(",")
    raw.append(socket.gethostname() if hostname is None else hostname)
    raw.append(_local_hostname() if local_hostname is None else local_hostname)
    names = {_host(name) for name in raw} - {""}
    remotes = root / "infra" / "remotes"
    if remotes.is_dir():
        from ..config import ConfigError, load_yaml
        for path in sorted(remotes.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            try:
                data = load_yaml(path)
            except ConfigError:
                continue
            host = _host(str(data.get("hostname") or "")) if isinstance(data, dict) else ""
            if host and host in names:
                names.add(path.stem.lower())
    return names


def _host(name: str) -> str:
    """A host name to compare: lower case, `Box.local` and `Box` the same, nothing else shortened.

    Cutting every name at its first dot made `mini.corp.example` and `mini.local`
    one machine; only the mDNS suffix is the same machine by definition.
    """
    name = name.strip().lower().rstrip(".")
    return name[: -len(".local")] if name.endswith(".local") else name


def routed(cfg, sender: str, names: set[str] | None = None) -> tuple[dict, str] | None:
    """(account, why) when drafts from this sender go to IMAP on this machine."""
    account = account_for(cfg, sender)
    if account is None:
        return None
    use_on = account.get("use_on") or []
    use_on = [use_on] if isinstance(use_on, str) else use_on if isinstance(use_on, list) else []
    wanted = {str(u).strip().lower() for u in use_on if str(u).strip()}
    if not wanted:
        return None
    if wanted & {"all", "*"}:
        return account, "every machine"
    names = machine_names(cfg.root) if names is None else names
    hit = sorted(wanted & names)
    return (account, hit[0]) if hit else None


# -- the password ------------------------------------------------------------

def _password(root: Path, ref: str) -> str:
    """Resolve the reference through the secrets skill of this Bridge. Never print it."""
    from ..config import ConfigError
    engine_dir = root / "skills" / "secrets" / "engine"
    if not (engine_dir / "__init__.py").is_file():
        raise ConfigError("password_ref needs the secrets skill (skills/secrets) to resolve, "
                          f"and this Bridge has none at {engine_dir}")
    pkg = "_mail_draft_secrets_" + hashlib.sha256(str(engine_dir.resolve()).encode()).hexdigest()[:12]
    if pkg not in sys.modules:
        spec = importlib.util.spec_from_file_location(pkg, engine_dir / "__init__.py",
                                                      submodule_search_locations=[str(engine_dir)])
        if spec is None or spec.loader is None:
            raise ConfigError(f"the secrets skill at {engine_dir} cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[pkg] = module
        spec.loader.exec_module(module)
    resolve = importlib.import_module(f"{pkg}.resolve")
    errors = importlib.import_module(f"{pkg}.errors")
    try:
        return resolve.Resolver(resolve.Options(root=str(root))).require(ref).expose_text()
    except errors.SecretsError as err:
        raise ConfigError(f"password_ref {ref}: {err}") from None


# -- the server --------------------------------------------------------------

def _connect(host: str, port: int):
    # Without a context imaplib builds one that checks neither the certificate
    # nor the host name, and the login sends the password to whoever answers.
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)


def _quote(mailbox: str) -> str:
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _utf7(name: str) -> str:
    """A configured folder name as IMAP spells it (RFC 3501 modified UTF-7).

    A name in plain ASCII is taken as the server lists it and left alone, so a
    name copied from a LIST answer (`Entw&APw-rfe`) still works.
    """
    if all(0x20 <= ord(c) <= 0x7E for c in name):
        return name
    out, run = [], []

    def flush():
        if run:
            packed = base64.b64encode("".join(run).encode("utf-16-be")).decode("ascii")
            out.append("&" + packed.rstrip("=").replace("/", ",") + "-")
            run.clear()
    for c in name:
        if 0x20 <= ord(c) <= 0x7E:
            flush()
            out.append("&-" if c == "&" else c)
        else:
            run.append(c)
    flush()
    return "".join(out)


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] == '"':
        return name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return name


def _drafts_folder(conn) -> str:
    """The folder the server flags \\Drafts (RFC 6154), as the server spells it."""
    typ, lines = conn.list()
    if typ != "OK":
        return ""
    for line in lines or []:
        literal = None
        if isinstance(line, tuple) and len(line) == 2:
            # A name sent as a literal: (b'(\\Drafts) "/" {6}', b'Drafts').
            line, literal = line
        text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        m = LIST_LINE.match(text)
        if not m:
            continue
        flags = m.group("flags").lower().split()
        if "\\drafts" in flags and "\\noselect" not in flags:
            if literal is not None:
                return literal.decode("utf-8", "replace") if isinstance(literal, bytes) else str(literal)
            return _unquote(m.group("name"))
    return ""


def _logout(conn) -> None:
    try:
        conn.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def _read_back(connect, host, port, user, password, folder, message_id, sleep):
    """The stored message, fetched from a fresh connection, or None."""
    conn = connect(host, port)
    try:
        conn.login(user, password)
        numbers = []
        for attempt in range(READ_BACK_ATTEMPTS):
            if attempt:
                sleep(1.5)
            # Selecting again is what makes a server show what arrived meanwhile.
            typ, _ = conn.select(_quote(folder), readonly=True)
            if typ != "OK":
                return None
            typ, data = conn.search(None, "HEADER", "Message-ID", _quote(message_id))
            numbers = (data[0] or b"").split() if typ == "OK" and data else []
            if numbers:
                break
        if not numbers:
            return None
        typ, data = conn.fetch(numbers[-1].decode() if isinstance(numbers[-1], bytes) else numbers[-1], "(RFC822)")
        for part in data or []:
            if isinstance(part, tuple) and len(part) == 2:
                return message_from_bytes(part[1], policy=policy.default)
        return None
    finally:
        _logout(conn)


def handoff(d, workdir: Path, show: bool = True, *, cfg, connect=None, password: str | None = None,
            sleep=None) -> Handoff:
    """Store the draft and read it back. `show` has no meaning here: there is no window."""
    from .. import mime
    from ..config import ConfigError
    address = sender_address(d.sender)
    account = account_for(cfg, d.sender)
    if account is None:
        return Handoff(False, "imap", f"no mail.imap_accounts entry holds drafts for the sender "
                                      f"{address or '(none)'}; add one in bridge-config.yaml or use another --client")
    problems = account_problems(account)
    if problems:
        return Handoff(False, "imap", f"mail.imap_accounts {address}: " + "; ".join(problems))
    host = str(account["host"]).strip()
    port = int(account.get("port", 993))
    user = str(account.get("user") or account["address"]).strip()
    configured = str(account.get("drafts_folder") or "").strip()
    connect = connect or _connect
    sleep = sleep or time.sleep
    try:
        secret = password if password is not None else _password(cfg.root, str(account["password_ref"]).strip())
    except ConfigError as err:
        return Handoff(False, "imap", str(err))

    msg = mime.build(d)
    message_id = str(msg["Message-ID"])
    raw = bytes(msg)
    try:
        conn = connect(host, port)
    except (OSError, imaplib.IMAP4.error) as err:
        return Handoff(False, "imap", f"{host}:{port} is not reachable ({err}); nothing was stored")
    try:
        try:
            conn.login(user, secret)
        except imaplib.IMAP4.error as err:
            return Handoff(False, "imap", f"{host} refused the login for {user} ({_plain(err)}); "
                                          "check the password behind password_ref, nothing was stored")
        folder = _utf7(configured) if configured else _drafts_folder(conn)
        if not folder:
            return Handoff(False, "imap", f"{host} marks no folder as Drafts; set drafts_folder for "
                                          f"{address} in mail.imap_accounts, nothing was stored")
        typ, data = conn.append(_quote(folder), "(\\Draft \\Seen)", imaplib.Time2Internaldate(time.time()), raw)
        if typ != "OK":
            return Handoff(False, "imap", f"{host} did not store the draft in {folder}: {_plain(data)}")
    except UnicodeError:
        # imaplib sends every command as ASCII. The error would quote the
        # offending characters, and they may be part of the password.
        return Handoff(False, "imap", f"{host}: the login holds characters IMAP cannot carry here "
                                      "(only ASCII); nothing was stored")
    except (OSError, imaplib.IMAP4.error) as err:
        return Handoff(False, "imap", f"{host}: the connection failed while storing ({_plain(err)})")
    finally:
        _logout(conn)

    attached = [p.name for p in d.attachments if p.is_file()]
    notes = [f"{len(d.to)} recipient(s)", f"{len(attached)} attachment(s)", f"sender {address}",
             f"folder {configured or folder} on {host}"]
    try:
        stored = _read_back(connect, host, port, user, secret, folder, message_id, sleep)
    except (OSError, imaplib.IMAP4.error) as err:
        notes.append(f"stored, but the read-back failed ({_plain(err)})")
        return Handoff(True, "imap", ", ".join(notes), verified=None)
    if stored is None:
        notes.append("the server answered OK, but the folder does not show the draft; it may still "
                     "appear, so look in the folder before running again")
        return Handoff(False, "imap", ", ".join(notes), verified=False)
    gaps = _differences(d, stored, attached)
    if gaps:
        notes.append("read back with differences: " + "; ".join(gaps))
        return Handoff(False, "imap", ", ".join(notes), verified=False)
    return Handoff(True, "imap", ", ".join(notes), verified=True)


def _differences(d, stored, attached: list[str]) -> list[str]:
    gaps = []
    if " ".join(str(stored["Subject"] or "").split()) != " ".join(d.subject.split()):
        gaps.append("subject")
    if sender_address(str(stored["From"] or "")) != sender_address(d.sender):
        gaps.append("sender")
    to = {a.lower() for _, a in getaddresses([str(stored["To"] or "")])}
    if to != {r.address.lower() for r in d.to}:
        gaps.append("recipients")
    cc = {a.lower() for _, a in getaddresses([str(stored["Cc"] or "")]) if a}
    if cc != {r.address.lower() for r in d.cc}:
        gaps.append("cc")
    names = sorted(p.get_filename() or "" for p in stored.iter_attachments())
    if names != sorted(attached):
        gaps.append(f"attachments {len(names)} of {len(attached)}")
    return gaps


def _plain(value) -> str:
    """A server answer as text: `[b'...']` and `b'...'` read as what they say."""
    if isinstance(value, (list, tuple)):
        return " ".join(_plain(v) for v in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
