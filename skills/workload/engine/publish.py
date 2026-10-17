"""publish: put the rendered page where a browser reaches it, and prove both halves.

A page in `.bridge/` is a file somebody has to know about. A page on a web
server is a page that gets looked at, and that difference is the whole reason
this module exists. It also introduces two ways to be wrong that the terminal
never had.

**The destination usually belongs to something already.** A served directory is
rarely empty: a puller rsyncs it back on every commit, another system writes its
own views there. Publishing into such a directory works, and then one of two
things happens without a word: the next sync deletes this page, or this page
overwrites theirs. So the destination is *proved* ours before a byte moves, and
the proof is a marker file inside it. That is the same shape the rest of this
skill uses for the units it owns, for the same reason: a directory cannot be
recognised by its name, only by something in it that says who wrote it.

**Delivered and reachable are two facts, and one word for both would hide the
gap between them.** Bytes landing on a disk and a browser receiving them fail
independently: a file in the wrong directory lands perfectly and is never
served, and a server pointed at a different root serves something else with a
cheerful 200. So this module never says "published". It says delivered, proved
by reading the bytes back off the machine, and separately reachable, proved by
fetching the URL and comparing what came out. Where no URL was given, reachable
stays unknown rather than false: nobody asked, and false would be a claim.

**A page is often not one file.** A stylesheet, a second view, a data file the
page links to: they are delivered beside it, byte for byte, and each one is
proved the same way. They never share the page's verdict, because "the page
arrived and its stylesheet did not" is a third situation, and one boolean
cannot say which of the three happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine import errors, exec as exec_mod, model
from engine.backends.base import (CHUNK_BYTES, RenderedFile, _chunks, write_file_step,
                                  write_file_steps)

#: The file that says this directory is ours. Read before every publish and
#: rewritten on every publish, so it cannot rot into a claim about a producer
#: that has not run in a year.
MARKER = ".workload-view"

#: What the marker names. A directory carrying somebody else's producer is a
#: refusal, never an overwrite.
PRODUCER = "workload-view"

#: The file the page is written as. A directory index, so the URL is a
#: directory and stays stable if the page is ever split.
PAGE_NAME = "index.html"

#: The content travels inside an argv, the way every other file this skill puts
#: on a machine does, but no longer as ONE argv: `write_file_steps` splits it
#: on line boundaries into parts of CHUNK_BYTES, one command line each. What
#: can still reach the transport too big is a single line longer than a part,
#: which becomes a part of its own. A multiplexed ssh session refused about
#: 256 KiB (measured 2026-08-27), so the limit sits below that, with room for
#: the quoting and the here-document around it.
#:
#: PER PART, not per file. Until 2026-09-18 this counted the whole file against
#: 512 KiB, a limit the split had already removed: a 556143 byte page whose
#: longest line was 13 KB was refused for four days, and /workloads/ showed
#: numbers from 14.09. as the present.
MAX_BYTES = 192 * 1024

#: How many foreign entries a refusal lists. Enough to recognise the directory,
#: not so many that the message becomes a listing.
_NAMED_ENTRIES = 6


@dataclass(frozen=True)
class Destination:
    """What the machine says about the target directory. Never what we assume."""

    exists: bool = False
    entries: tuple = ()
    #: The producer the marker names, "" where there is no marker. Never None:
    #: absent and unreadable are the same answer to this question.
    marker: str = ""


@dataclass(frozen=True)
class Attachment:
    """One file that travels with the page, byte for byte.

    `name` is what it is called in the destination and is always a bare file
    name: it comes from the basename of the path a human typed, so an
    attachment cannot address a directory of its own and cannot climb out of
    the one that was proved ours.
    """

    name: str
    content: str


@dataclass(frozen=True)
class Delivery:
    """What became of ONE delivered file.

    The page has one of these and so does every attachment. Delivery is a
    question per file: a page that landed beside a stylesheet that did not is
    a different situation from both landing and from neither, and a single
    boolean over the set cannot tell a reader which of the three they have.
    """

    name: str
    delivered: bool = False
    evidence: str = ""


@dataclass(frozen=True)
class _Planned:
    """One file, its write step and the read-back that proves it arrived.

    Built once, in `_plan`, together with the marker that claims the same set.
    Nothing else assembles these three from the same inputs a second time,
    which is what keeps the claim, the write and the proof from disagreeing.
    """

    name: str
    content: str
    #: The write, in as MANY parts as the transport takes. One command line per
    #: part: a multiplexed ssh session refuses a single request past about
    #: 256 KiB, and the page passed that on 2026-08-27. Nothing here proves the
    #: parts arrived; the read-back below does, and a half delivered file fails
    #: that comparison exactly like a corrupted one.
    writes: tuple
    readback: object


@dataclass(frozen=True)
class Outcome:
    """Two facts, kept apart on purpose."""

    action: str = "publish"
    #: The bytes of the PAGE are on the machine, proved by reading them back.
    delivered: bool = False
    #: The server hands them out. None where no URL was given: unknown, not false.
    reachable: object = None
    evidence: str = ""
    url: str = ""
    steps: tuple = ()
    #: One `Delivery` per file that travelled with the page, in the order they
    #: were asked for. Empty where none was.
    attachments: tuple = ()
    #: What was in the directory before this run and is not delivered by it.
    #: Nothing here removes a file, so these are older than this publish and
    #: are still being served. See `marker_body`.
    leftovers: tuple = ()

    @property
    def ok(self) -> bool:
        """The PAGE, delivered, and reachable wherever that was asked.

        Deliberately says nothing about the attachments. The page is the
        subject of the publish and an attachment is its baggage; a stylesheet
        that failed must not turn a delivered, reachable page into a run that
        reads as having delivered nothing.
        """
        return self.delivered and self.reachable is not False

    @property
    def complete(self) -> bool:
        """Everything that was asked for, page and attachments alike.

        The other half of `ok`, and the one an exit code is built on: a run
        that was asked for three files and delivered two did not do what it
        was asked, however healthy the page is.
        """
        return self.ok and all(item.delivered for item in self.attachments)


def marker_body(names) -> str:
    """What goes into the marker. Short, and addressed to whoever finds it.

    `names` is every file this publish delivers, and it has NO DEFAULT on
    purpose. The marker is this directory's one statement about what is in it;
    a second caller free to pass its own list, or to leave the list out, is
    exactly the drift a marker exists to prevent. There is one caller, `_plan`,
    and it builds this list and the write steps out of the same tuple, so the
    claim and the delivery have nothing to disagree about.

    The note used to say that every file here is overwritten on the next
    publish. It is not true and never was: the delivery path holds no `rm` and
    no `rsync --delete`, so only the marker and the files named below are
    rewritten. A file that landed here once and has since dropped out of the
    output simply STAYS, and a web server goes on serving it exactly as if it
    were current. So the note says that instead, and says what follows from it.
    """
    listed = "".join(f"  - {name}\n" for name in names)
    return (
        f"producer: {PRODUCER}\n"
        "written-by: the workload skill of the Bridge\n"
        f"delivers:\n{listed}"
        "note: the files listed above are rewritten on every publish, and\n"
        "      NOTHING here is ever removed. A file an earlier publish put\n"
        "      here and this one no longer delivers stays where it is, and the\n"
        "      server goes on handing it out as though it were current. Read\n"
        "      this list as what is current and treat anything else in this\n"
        "      directory as a leftover to be deleted by hand. Put nothing here\n"
        "      yourself, and if another program owns this directory, point the\n"
        "      publish at a subdirectory of its own instead.\n"
    )


def expand(dest: str, home) -> str:
    """A tilde is resolved against the machine's OWN home, or refused.

    Every path this skill sends travels inside a quoted shell word, which is
    what makes the quoting safe and what makes `~` a directory name. Shell
    expansion is therefore not available here even in principle, and the home
    that replaces it is probed off the machine like the uid is, never assumed
    from the account running this command.
    """
    if not dest.startswith("~"):
        return dest
    if not dest.startswith("~/") and dest != "~":
        raise errors.DestinationNotResolvable(
            f"{dest} names another user's home. Nothing here can resolve it "
            "without guessing a path on somebody else's account; give the "
            "absolute directory instead.", path=dest)
    if not home:
        raise errors.DestinationNotResolvable(
            f"{dest} begins with ~ and the home directory of that machine was "
            "not probed. Pass it, or give an absolute path: a tilde sent as it "
            "stands creates a directory literally called ~ and every later "
            "check agrees the files are fine.", path=dest)
    return str(home).rstrip("/") if dest == "~" else f"{str(home).rstrip('/')}{dest[1:]}"


def _joined(dest: str, name: str) -> str:
    return f"{dest.rstrip('/')}/{name}"


def load_attachments(paths) -> tuple:
    """Read the named files off THIS machine, and refuse what cannot travel.

    Every refusal here is knowable without asking the destination anything, so
    all of them happen before the first byte moves and before a machine is even
    contacted. A file that is refused after the marker has been written leaves
    a half-published directory somebody has to reason about.

    Two of them are about the transport rather than the file. Content travels
    as a quoted here-document inside one command line, which carries text and
    cannot carry a file that ends anywhere but on a newline: the transport
    would silently add the byte, and the read-back would then report a
    difference the machine never caused, pointing the reader at the wrong end
    of the wire.
    """
    from pathlib import Path

    out = []
    for raw in paths or ():
        path = Path(str(raw)).expanduser()
        if not path.is_file():
            raise errors.ConfigError(
                f"{raw} is not a file, so there is nothing to attach. An "
                "attachment is one existing file; a directory has to be named "
                "file by file, because a publish that walked one would deliver "
                "whatever happened to be in it that day.",
                code="attachment-unreadable", path=str(raw))
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            raise errors.ConfigError(
                f"{raw} could not be read as UTF-8 text: {err}. Every file this "
                "skill puts on a machine travels as text inside one command "
                "line, so an image or an archive has to go by another route.",
                code="attachment-unreadable", path=str(raw)) from err
        if not content.endswith("\n"):
            raise errors.Refused(
                f"{raw} does not end with a newline (an empty file does not "
                "either). It travels as a quoted here-document, which cannot "
                "express a file that ends anywhere else: the transport would "
                "add the byte itself and the read-back would then report a "
                "difference the machine never caused. Add the newline, or "
                "deliver this file by another route.",
                code="attachment-not-transportable", path=str(raw))
        out.append(Attachment(name=path.name, content=content))
    return tuple(out)


def deliveries(page: str, page_name: str, attachments) -> tuple:
    """Every file this publish puts in the directory, page first.

    One list, built once. The marker's claim, the write steps and the
    read-backs are all derived from THIS tuple, so none of them can name a set
    another one does not. Page first because the page is the subject: if a
    later write fails, the thing somebody opened the URL for is already there.
    """
    out = [(page_name, page)]
    out.extend((item.name, item.content) for item in attachments or ())
    seen = set()
    for name, _ in out:
        if not name or "\n" in name or "/" in name:
            raise errors.Refused(
                f"{name!r} is not a file name this publish can deliver: it has "
                "to be a bare name inside the directory that was proved ours, "
                "because that proof covers one directory and nothing under or "
                "above it.", code="attachment-name-invalid", name=name)
        if name == MARKER:
            raise errors.Refused(
                f"{name} is this skill's own claim on the directory. Delivering "
                "a file under that name would overwrite the marker with "
                "something that does not name a producer, and the next publish "
                "would refuse the directory as a stranger's.",
                code="attachment-name-collision", name=name)
        if name in seen:
            raise errors.Refused(
                f"two files would be delivered as {name}. The second would "
                "overwrite the first, both would read back equal to what was "
                "sent, and the report would show two attachments delivered "
                "where the directory holds one.",
                code="attachment-name-collision", name=name)
        seen.add(name)
    return tuple(out)


def inspect(host, dest: str, *, runner, timeout_sec) -> Destination:
    """Ask the machine what is in the directory and who claims it."""
    listing = model.Step(
        argv=("/bin/sh", "-c", f"ls -A {exec_mod.sh_quote(dest)}"),
        purpose=f"list {dest}",
        expect_rc=(),
    )
    done = runner(listing, host, timeout_sec=timeout_sec)
    if done.rc != 0:
        # Missing is the common case on a first publish and is not an error.
        return Destination(exists=False)
    entries = tuple(line.strip() for line in (done.stdout or "").splitlines() if line.strip())

    marker = ""
    if MARKER in entries:
        read = model.Step(
            argv=("/bin/sh", "-c",
                  f"cat {exec_mod.sh_quote(_joined(dest, MARKER))} 2>/dev/null"),
            purpose=f"read {MARKER}",
            expect_rc=(),
        )
        got = runner(read, host, timeout_sec=timeout_sec)
        if got.rc == 0:
            for line in (got.stdout or "").splitlines():
                if line.startswith("producer:"):
                    marker = line.split(":", 1)[1].strip()
                    break
    return Destination(exists=True, entries=entries, marker=marker)


def guard(obs: Destination, dest: str) -> None:
    """Refuse anything but an empty, absent, or already-ours directory.

    Raises before a single byte moves. A guard that fires after the write has
    not guarded anything.

    A file THIS skill delivered is never a stranger's, and that falls out of
    the marker rather than out of a list of names: the marker is what says the
    directory is ours, and once it does, everything in it came from here.
    """
    if not obs.exists:
        return
    foreign = tuple(e for e in obs.entries if e != MARKER)
    if not foreign:
        return
    if obs.marker == PRODUCER:
        return
    if obs.marker:
        raise errors.DestinationNotOurs(
            f"{dest} carries a marker naming {obs.marker!r}, not {PRODUCER!r}. "
            "Publishing here would overwrite another program's output.",
            path=dest, marker=obs.marker)
    named = ", ".join(foreign[:_NAMED_ENTRIES])
    more = f" and {len(foreign) - _NAMED_ENTRIES} more" if len(foreign) > _NAMED_ENTRIES else ""
    raise errors.DestinationNotOurs(
        f"{dest} holds files nothing here wrote ({named}{more}) and carries no "
        f"{MARKER}. Publish into a subdirectory of its own instead: whoever owns "
        "this one will either delete the page at its next sync or have its own "
        "output overwritten.",
        path=dest, entries=named)


def _readback_step(target: str):
    return model.Step(
        argv=("/bin/sh", "-c", f"cat {exec_mod.sh_quote(target)} 2>/dev/null"),
        purpose=f"read {target} back off the machine",
        expect_rc=(),
    )


def _plan(dest: str, files) -> tuple:
    """The claim, and one write-and-read-back per delivered file.

    `files` is the tuple `deliveries` built. The marker is written from the
    names in it, so the directory's own statement about its content is not a
    second opinion about what was delivered: it is the same tuple.
    """
    claim = write_file_step(RenderedFile(path=_joined(dest, MARKER), mode=0o644,
                                         content=marker_body([n for n, _ in files])))
    planned = tuple(
        _Planned(name=name, content=content,
                 writes=write_file_steps(RenderedFile(path=_joined(dest, name),
                                                      mode=0o644, content=content)),
                 readback=_readback_step(_joined(dest, name)))
        for name, content in files)
    return claim, planned


def _flatten(claim, planned) -> tuple:
    """The plan as one list of steps, in the order the real run takes them.

    Built from the same `_plan` the run executes, so a dry run and a real run
    cannot show different work for the same arguments.
    """
    steps = [claim]
    for item in planned:
        steps.extend(item.writes)
        steps.append(item.readback)
    return tuple(steps)


def steps_for(page: str, dest: str, *, page_name: str = PAGE_NAME,
              attachments=()) -> tuple:
    """Every step this publish would take, built once.

    The marker goes first. If a page write then fails, the directory is
    claimed and empty, which the next run handles; the other order leaves an
    unclaimed page that every later run refuses as a stranger's.
    """
    return _flatten(*_plan(dest, deliveries(page, page_name, attachments)))


def _refuse_if_too_large(subject: str, content: str) -> bytes:
    """The one size gate, reached by the page and by every attachment alike.

    The limit is a property of the TRANSPORT and not of the page, so it counts
    per PART: the same split `write_file_steps` makes, each part in a command
    line of its own. Only a line longer than a part can fail it.
    """
    encoded = content.encode("utf-8")
    body = content if content.endswith("\n") else content + "\n"
    largest = max(len(part.encode("utf-8")) for part in _chunks(body, CHUNK_BYTES))
    if largest > MAX_BYTES:
        raise errors.PageTooLarge(
            f"{subject} carries a single line of about {largest} bytes and the "
            f"limit is {MAX_BYTES}. A file travels in parts split on line "
            "boundaries, never inside a line, and one part this large is cut "
            "off by the connection with an error naming neither. Break the "
            "line or deliver it by another route.",
            size=largest, limit=MAX_BYTES, subject=subject)
    return encoded


def _verdict(item: _Planned, back, dest: str) -> Delivery:
    """What the machine handed back, compared with what was sent.

    Never the write's own return code: a truncated write returns 0 and the
    file on disk is half a page.
    """
    if back.rc != 0:
        return Delivery(name=item.name, delivered=False,
                        evidence=f"{item.name} could not be read back from "
                                 f"{dest}: rc={back.rc}")
    if (back.stdout or "") != item.content:
        return Delivery(name=item.name, delivered=False,
                        evidence=f"the bytes read back for {item.name} differ "
                                 f"from what was sent ({len(back.stdout or '')} "
                                 f"vs {len(item.content)} characters)")
    return Delivery(name=item.name, delivered=True,
                    evidence=f"{item.name}: bytes read back equal")


def _leftovers(obs: Destination, files) -> tuple:
    """What is in the directory that this publish does not deliver.

    Read off the listing taken BEFORE anything was written, which is the only
    moment at which the answer is about the previous state. Nothing here
    removes a file, so every one of these goes on being served; naming them is
    the whole practical consequence of the marker's corrected note.
    """
    delivered = {name for name, _ in files}
    return tuple(e for e in obs.entries if e != MARKER and e not in delivered)


def _fetch(url, *, timeout_sec=30):
    """The default reader, and the one seam the other cases replace.

    An answer that is not 200 is an ANSWER and comes back as one: this raised
    instead, so the branch reporting an unreachable page could not run in the
    only implementation that ships. No answer at all is a different thing and
    stays an exception, which the exit map already calls 4.
    """
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as answer:  # noqa: S310
            return answer.status, answer.read()
    except urllib.error.HTTPError as err:
        return err.code, (err.read() or b"")
    except (urllib.error.URLError, OSError) as err:
        raise errors.Unreachable(f"{url} did not answer at all: {err}", url=url) from err


def _attachment_note(attached) -> str:
    """One clause about the baggage, for a caller that reads only `evidence`."""
    if not attached:
        return ""
    good = [item for item in attached if item.delivered]
    note = f"; {len(good)} of {len(attached)} attached file(s) delivered"
    failed = [item for item in attached if not item.delivered]
    if failed:
        note += " (" + "; ".join(item.evidence for item in failed) + ")"
    return note


def publish(page: str, host, *, dest: str, page_name: str = PAGE_NAME,
            attachments=(), url=None, fetch=None, runner=None, home=None,
            timeout_sec: int = 60, dry_run: bool = True) -> Outcome:
    """Deliver the page and its attachments, then prove each of them.

    `dry_run` defaults to true on purpose.
    """
    dest = expand(dest, home)
    files = deliveries(page, page_name, attachments)
    # Every size is settled before a machine is contacted: all of them are
    # knowable here, and a refusal after the marker has been written leaves a
    # half-published directory behind.
    encoded = _refuse_if_too_large("the page", page)
    for name, content in files[1:]:
        _refuse_if_too_large(f"the attachment {name}", content)

    runner = runner or exec_mod.step_runner
    obs = inspect(host, dest, runner=runner, timeout_sec=timeout_sec)
    guard(obs, dest)
    left = _leftovers(obs, files)
    claim, planned = _plan(dest, files)
    steps = _flatten(claim, planned)

    if dry_run:
        return Outcome(action="publish", delivered=False, reachable=None, steps=steps,
                       url=url or "", leftovers=left,
                       evidence=f"dry run: {len(steps)} step(s) prepared for {dest}, "
                                f"which would write the marker and {len(files)} "
                                "file(s); nothing was written")

    runner(claim, host, timeout_sec=timeout_sec)
    results = []
    for item in planned:
        for part in item.writes:
            runner(part, host, timeout_sec=timeout_sec)
        back = runner(item.readback, host, timeout_sec=timeout_sec)
        results.append(_verdict(item, back, dest))

    page_result, attached = results[0], tuple(results[1:])
    if not page_result.delivered:
        # The attachments still travel and are still reported: which of them
        # arrived is exactly what somebody needs to know before running this
        # again, and dropping them here would leave the directory in a state
        # the report does not describe.
        return Outcome(action="publish", delivered=False, reachable=None, steps=steps,
                       url=url or "", attachments=attached, leftovers=left,
                       evidence=page_result.evidence + _attachment_note(attached))

    evidence = (f"delivered to {host.slug}:{_joined(dest, page_name)}, "
                "bytes read back equal") + _attachment_note(attached)
    if not url:
        # Nobody asked whether a server hands it out, so nobody may say.
        return Outcome(action="publish", delivered=True, reachable=None, steps=steps,
                       attachments=attached, leftovers=left,
                       evidence=evidence + "; no URL was given, so whether a server "
                                           "serves it was not asked")

    status, body = (fetch or _fetch)(url, timeout_sec=timeout_sec)
    if status != 200:
        return Outcome(action="publish", delivered=True, reachable=False, steps=steps,
                       url=url, attachments=attached, leftovers=left,
                       evidence=evidence + f"; {url} answered {status}")
    if body != encoded:
        return Outcome(action="publish", delivered=True, reachable=False, steps=steps,
                       url=url, attachments=attached, leftovers=left,
                       evidence=evidence + f"; {url} answered 200 but served "
                                           f"{len(body)} other bytes, so the server "
                                           "is not serving this directory")
    return Outcome(action="publish", delivered=True, reachable=True, steps=steps, url=url,
                   attachments=attached, leftovers=left,
                   evidence=evidence + f"; {url} served the same bytes")
