"""Apple Mail: a real draft with HTML, sender, recipients and attachments.

`html content` is broken only for READING (it returns an empty string). Setting
it on a new outgoing message works and keeps tables and inline styles as
written, and it is the only route on which the sender can be chosen. The
NSSharingService route that older scripts used turns HTML into rich text
(tables and borders fall apart) and always sends from the default account.

The message is created as a normal compose window and never activated, so Mail
does not take focus from whatever the person is typing in. With `--hide` the
window is closed after saving. An INVISIBLE outgoing message is not an option:
it outlives `save`, cannot be closed or deleted by script, and Mail keeps
re-saving it into Drafts until it quits.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import ConfigError
from . import Handoff, answer_fields, osascript, write_inputs

SCRIPT = r'''
on readFile(p)
    try
        return read (POSIX file p) as «class utf8»
    on error
        return ""
    end try
end readFile

on nonEmptyLines(t)
    set out to {}
    if t is "" then return out
    repeat with x in paragraphs of t
        set s to x as text
        if s is not "" then set end of out to s
    end repeat
    return out
end nonEmptyLines

on run argv
    set d to item 1 of argv
    set showIt to ((item 2 of argv) is "show")
    set theSubject to my readFile(d & "/subject.txt")
    set theHtml to my readFile(d & "/body.html")
    set theSender to my readFile(d & "/sender.txt")
    set toList to my nonEmptyLines(my readFile(d & "/to.txt"))
    set ccList to my nonEmptyLines(my readFile(d & "/cc.txt"))
    set bccList to my nonEmptyLines(my readFile(d & "/bcc.txt"))
    set attList to my nonEmptyLines(my readFile(d & "/attachments.txt"))
    set senderSet to "no"
    tell application "Mail"
        -- Windows that already carry this subject belong to the person; with
        -- one of those open, --hide leaves our window open instead of guessing.
        set preWindows to count of (every window whose name is theSubject)
        -- Always a real window. An invisible outgoing message survives `save`
        -- as an object nobody can close or delete, and Mail keeps re-saving it
        -- into Drafts until it quits (measured: a deleted test draft came back).
        set m to make new outgoing message with properties {subject:theSubject, visible:true}
        if theSender is not "" then
            try
                set sender of m to theSender
                set senderSet to "yes"
            end try
        end if
        tell m
            repeat with a in toList
                make new to recipient at end of to recipients with properties {address:(a as text)}
            end repeat
            repeat with a in ccList
                make new cc recipient at end of cc recipients with properties {address:(a as text)}
            end repeat
            repeat with a in bccList
                make new bcc recipient at end of bcc recipients with properties {address:(a as text)}
            end repeat
        end tell
        set html content of m to theHtml
        -- The HTML is applied asynchronously and replaces the content, and the
        -- attachments live IN the content. Added too early they vanish without
        -- an error, so wait for the HTML before attaching.
        delay 1.5
        set attached to 0
        repeat with p in attList
            try
                tell content of m to make new attachment with properties {file name:((POSIX file (p as text)) as alias)} at after the last paragraph
                set attached to attached + 1
            end try
        end repeat
        -- An attachment is still loading for a moment after it is added; a
        -- save before that stores the draft without it.
        delay 2
        save m
        delay 1
        set actualSender to ""
        try
            set actualSender to (sender of m) as text
        end try
        set closedIt to "no"
        if not showIt and preWindows is 0 then
            -- `--hide`: saved above, then the window closed WITHOUT saving
            -- again, which ends the object. A second save from the closing
            -- window stored the draft without its attachment (measured).
            try
                close (every window whose name is theSubject) saving no
                set closedIt to "yes"
            end try
        end if
    end tell
    set nTo to (count of toList) as string
    set nAtt to attached as string
    return "OK|sender=" & senderSet & "|to=" & nTo & "|attachments=" & nAtt & "|closed=" & closedIt & "|from=" & actualSender
end run
'''

VERIFY = r'''
on run argv
    set s to item 1 of argv
    tell application "Mail"
        set ms to (messages of drafts mailbox whose subject is s)
        set n to count of ms
        if n is 0 then return "0"
        -- The NEWEST with this subject: an older draft of the same name must
        -- not confirm a new one that failed.
        set best to item 1 of ms
        repeat with m in ms
            if (date received of m) > (date received of best) then set best to m
        end repeat
        set src to source of best
    end tell
    return (n as string) & linefeed & src
end run
'''


DEDUPE = r'''
on run argv
    set s to item 1 of argv
    set windowSeconds to (item 2 of argv) as integer
    set cutoff to (current date) - windowSeconds
    tell application "Mail"
        set ms to (messages of drafts mailbox whose subject is s)
        if (count of ms) < 2 then return "0"
        set best to item 1 of ms
        repeat with m in ms
            set dm to date received of m
            set db to date received of best
            if dm > db then set best to m
        end repeat
        set bestId to id of best
        set removed to 0
        repeat with m in ms
            set dm to date received of m
            set mid to id of m
            if mid is not bestId and dm ≥ cutoff then
                delete m
                set removed to removed + 1
            end if
        end repeat
    end tell
    return removed as string
end run
'''


def handoff(d, workdir: Path, show: bool = True) -> Handoff:
    started = time.monotonic()
    before = inspect(d.subject)
    before_count = before[0] if before else 0
    # Apple Mail converts the HTML under the current system appearance and keeps
    # the computed colours, so it gets the version without dark-mode rules.
    write_inputs(d, workdir, html=d.html_static)
    done = osascript(SCRIPT, [str(workdir), "show" if show else "hide"])
    out = (done.stdout or "").strip()
    if done.returncode != 0 or not out.startswith("OK"):
        return Handoff(False, "apple-mail", (done.stderr or out or "no answer").strip())
    fields = answer_fields(out)
    notes = [f"{fields.get('to')} recipient(s)"]
    actual = fields.get("from", "")
    if d.sender:
        # Mail accepts any sender without an error and keeps its default when no
        # account has that address, so only the value read back counts.
        if d.sender.lower() in actual.lower():
            notes.append(f"sender {actual}")
        else:
            notes.append(f"sender NOT {d.sender}: Mail kept {actual or 'its default'} "
                         f"(no account with that address); switch 'From' before sending")
    elif actual:
        notes.append(f"sender {actual} (Mail's default)")
    found = inspect(d.subject)
    if found is None:
        return Handoff(False, "apple-mail", ", ".join(notes) + ", Drafts not readable", verified=None)
    count, saved = found
    if count <= before_count:
        notes.append(f"Drafts holds {count} with this subject, as before ({before_count}): the new one was not saved")
        return Handoff(False, "apple-mail", ", ".join(notes), verified=False)
    count, saved = dedupe(d.subject, started, before_count, found, notes)
    expected = sorted(p.name for p in d.attachments if p.is_file())
    if sorted(saved["attachments"]) != expected:
        notes.append(f"attachments in the saved draft: {saved['attachments'] or 'none'}, "
                     f"expected {expected}; attach them by hand before sending")
        return Handoff(False, "apple-mail", ", ".join(notes), verified=True)
    if expected:
        notes.append(f"{len(expected)} attachment(s) in the saved draft")
    return Handoff(True, "apple-mail", ", ".join(notes), verified=True)


def dedupe(subject: str, started: float, before_count: int, found: tuple[int, dict],
           notes: list[str]) -> tuple[int, dict]:
    """Remove the extra copies Mail saved of THIS run's draft; keep the newest.

    Measured 2026-10-07 on an Exchange account: one run left two drafts five
    seconds apart (Mail's own autosave of the new window, then the explicit
    save), and Exchange kept both. In a reply the autosave can fire between two
    pastes, so the extra copy is a PARTIAL one that could be sent by mistake.
    Only copies with this subject created during this run are removed, never an
    older draft.
    """
    count, _ = found
    if count <= before_count + 1:
        return found
    window = int(time.monotonic() - started) + 5
    try:
        done = osascript(DEDUPE, [subject, str(window)], timeout=60)
    except subprocess.TimeoutExpired:
        notes.append(f"Drafts holds {count - before_count} new copies with this subject and Mail did not "
                     "answer the clean-up; delete all but the newest by hand")
        return found
    removed = (done.stdout or "").strip()
    if removed.isdigit() and int(removed):
        notes.append(f"removed {removed} duplicate(s) Mail saved during this run")
        return inspect(subject) or found
    notes.append(f"Drafts holds {count - before_count} new copies with this subject; "
                 "delete all but the newest by hand")
    return found


def inspect(subject: str) -> tuple[int, dict] | None:
    """Read the saved draft back from a fresh process: count, attachments, sender.

    The creating script's own counts are not evidence: it counted an attachment
    that the saved draft did not contain.
    """
    try:
        done = osascript(VERIFY, [subject], timeout=60)
    except subprocess.TimeoutExpired:
        return None
    raw = done.stdout or ""
    head, _, source = raw.partition("\n")
    try:
        count = int(head.strip())
    except ValueError:
        return None
    saved = {"attachments": [], "from": "", "to": "", "cc": "", "text": "", "html": ""}
    if source.strip():
        import email
        from email import policy
        msg = email.message_from_string(source, policy=policy.default)
        saved["from"] = str(msg.get("From", ""))
        saved["to"] = str(msg.get("To", ""))
        saved["cc"] = str(msg.get("Cc", ""))
        saved["attachments"] = [p.get_filename() for p in msg.walk() if p.get_filename()]
        for part in msg.walk():
            if part.get_filename() or part.is_multipart():
                continue
            kind = {"text/plain": "text", "text/html": "html"}.get(part.get_content_type())
            if kind:
                try:
                    saved[kind] += str(part.get_content())
                except (LookupError, ValueError):
                    pass
    return count, saved


def verify(subject: str) -> int | None:
    found = inspect(subject)
    return None if found is None else found[0]


# ----------------------------------------------------------------- replies --
#
# A reply is a different object from a new message, and two things that work
# on a new message break it (measured on real replies):
#
# - Setting `content` or `html content` replaces the WHOLE body, quote
#   included. So the text is pasted into the reply window instead.
# - `make new attachment ... at after the last paragraph of content` deleted
#   the pasted text together with the quote. So files go in the same way the
#   text does: onto the clipboard (`set the clipboard to (POSIX file ...)`)
#   and pasted.
#
# A paste lands wherever the keyboard focus is. Every paste therefore checks
# first that Mail is the frontmost app and its front window is this reply (by
# window id), and gives up (closing the reply unsaved) instead of pasting
# elsewhere; any runtime error takes the same way out. The saved draft is then
# read back from Drafts and checked for the text and footer above the quote,
# the quote below it, every attachment and the recipients, because the
# creating script cannot see what Mail really stored.

FIND = r'''
-- mail-draft:find
-- Read only: finds the message a reply answers and changes nothing.
on run argv
    set kind to item 1 of argv
    set val to item 2 of argv
    tell application "Mail"
        if kind is "id" then
            set hits to (messages of inbox whose message id is val)
            if (count of hits) is 0 then
                repeat with acc in accounts
                    repeat with mb in mailboxes of acc
                        try
                            set hits to (messages of mb whose message id is val)
                        end try
                        if (count of hits) > 0 then exit repeat
                    end repeat
                    if (count of hits) > 0 then exit repeat
                end repeat
            end if
        else
            set hits to (messages of inbox whose subject contains val)
        end if
        set n to count of hits
        if n is 0 then return "OK" & linefeed & "0"
        -- The NEWEST match: a subject seen in a thread answers its latest mail.
        set best to item 1 of hits
        repeat with m in hits
            set dm to date received of m
            set db to date received of best
            if dm > db then set best to m
        end repeat
        set mid to message id of best
        set who to sender of best
        set subj to subject of best
        set dr to (date received of best) as string
        -- Where it lives, so the reply script goes straight there instead of
        -- searching every mailbox a second time.
        set mbName to ""
        set accName to ""
        try
            set mbx to mailbox of best
            set mbName to name of mbx
            set accName to name of account of mbx
        end try
        set excerpt to ""
        try
            set excerpt to content of best
        end try
    end tell
    if (length of excerpt) > 400 then set excerpt to text 1 thru 400 of excerpt
    return "OK" & linefeed & (n as string) & linefeed & mid & linefeed & who & linefeed & subj & linefeed & dr & linefeed & mbName & linefeed & accName & linefeed & excerpt
end run
'''

REPLY = r'''
-- mail-draft:reply
use AppleScript version "2.4"
use framework "Foundation"
use framework "AppKit"
use scripting additions

property savedClip : missing value

on readFile(p)
    try
        return read (POSIX file p) as «class utf8»
    on error
        return ""
    end try
end readFile

on nonEmptyLines(t)
    set out to {}
    if t is "" then return out
    repeat with x in paragraphs of t
        set s to x as text
        if s is not "" then set end of out to s
    end repeat
    return out
end nonEmptyLines

on joined(xs)
    set AppleScript's text item delimiters to ","
    set t to xs as text
    set AppleScript's text item delimiters to ""
    return t
end joined

-- Mail is the frontmost app AND its front window is THIS reply, by window id.
-- A name is not enough: the person may have another window with this subject.
on replyInFront(wid)
    tell application "System Events"
        set frontName to name of first application process whose frontmost is true
    end tell
    if frontName is not "Mail" then return false
    tell application "Mail"
        if (count of windows) is 0 then return false
        set fid to id of front window
    end tell
    return fid is wid
end replyInFront

-- The only paste in this script, and it checks the focus first.
on pasteIfFront(wid)
    if not my replyInFront(wid) then return false
    tell application "System Events" to keystroke "v" using command down
    delay 1
    return true
end pasteIfFront

-- HTML for Mail, the text part as the fallback flavour.
on putHtml(h, t)
    set pb to current application's NSPasteboard's generalPasteboard()
    pb's clearContents()
    pb's setString:h forType:"public.html"
    pb's setString:t forType:(current application's NSPasteboardTypeString)
end putHtml

on restoreClip()
    if savedClip is not missing value then
        try
            set the clipboard to savedClip
        end try
    end if
end restoreClip

-- Nothing half done stays behind: THIS reply window (by id) is closed WITHOUT
-- saving, and the person's clipboard comes back. `saved` says whether a save
-- already happened, because then a copy sits in Drafts.
on giveUp(wid, why, savedIt)
    set closedIt to "no"
    if wid is not missing value then
        try
            tell application "Mail" to close (every window whose id is wid) saving no
            set closedIt to "yes"
        end try
    end if
    my restoreClip()
    return "ERR|" & why & "|closed=" & closedIt & "|saved=" & savedIt
end giveUp

on run argv
    set d to item 1 of argv
    set showIt to ((item 2 of argv) is "show")
    set mid to item 3 of argv
    set toAll to ((item 4 of argv) is "all")
    set setTo to ((item 5 of argv) is "set")
    set mbName to item 6 of argv
    set accName to item 7 of argv
    set wid to missing value
    set savedIt to "no"
    try
        set theSubject to my readFile(d & "/subject.txt")
        set theHtml to my readFile(d & "/body.html")
        set theText to my readFile(d & "/body.txt")
        set theSender to my readFile(d & "/sender.txt")
        set toList to my nonEmptyLines(my readFile(d & "/to.txt"))
        set ccList to my nonEmptyLines(my readFile(d & "/cc.txt"))
        set bccList to my nonEmptyLines(my readFile(d & "/bcc.txt"))
        set attList to my nonEmptyLines(my readFile(d & "/attachments.txt"))
        try
            set savedClip to the clipboard as text
        end try
        tell application "Mail"
            set hits to {}
            if mbName is not "" and accName is not "" then
                try
                    set hits to (messages of mailbox mbName of account accName whose message id is mid)
                end try
            end if
            if (count of hits) is 0 then set hits to (messages of inbox whose message id is mid)
            if (count of hits) is 0 then
                repeat with acc in accounts
                    repeat with mb in mailboxes of acc
                        try
                            set hits to (messages of mb whose message id is mid)
                        end try
                        if (count of hits) > 0 then exit repeat
                    end repeat
                    if (count of hits) > 0 then exit repeat
                end repeat
            end if
            if (count of hits) is 0 then return "ERR|gone|closed=no|saved=no"
            set orig to item 1 of hits
            set preIds to id of every window
            if toAll then
                set r to reply orig with opening window and reply to all
            else
                set r to reply orig with opening window
            end if
            delay 1
            -- The reply's own window: the one that was not there before.
            repeat with w in (every window)
                set wi to id of w
                if preIds does not contain wi then
                    set wid to wi
                    exit repeat
                end if
            end repeat
            if wid is missing value then return my giveUp(wid, "window", savedIt)
            set replySubject to subject of r
            if theSubject is not "" and theSubject is not replySubject then set subject of r to theSubject
            if theSender is not "" then
                try
                    set sender of r to theSender
                end try
            end if
            tell r
                -- --to replaces whom Mail chose to answer; --cc and --bcc add to it.
                if setTo then
                    delete every to recipient
                    repeat with a in toList
                        make new to recipient at end of to recipients with properties {address:(a as text)}
                    end repeat
                end if
                repeat with a in ccList
                    make new cc recipient at end of cc recipients with properties {address:(a as text)}
                end repeat
                repeat with a in bccList
                    make new bcc recipient at end of bcc recipients with properties {address:(a as text)}
                end repeat
            end tell
            activate
        end tell
        delay 1.5
        my putHtml(theHtml, theText)
        if not my pasteIfFront(wid) then return my giveUp(wid, "focus", savedIt)
        set attached to 0
        repeat with p in attList
            set the clipboard to (POSIX file (p as text))
            if not my pasteIfFront(wid) then return my giveUp(wid, "focus", savedIt)
            set attached to attached + 1
        end repeat
        -- An attachment is still loading for a moment after the paste.
        delay 2
        tell application "Mail"
            save r
            set savedIt to "yes"
            delay 1
            set gotTo to my joined(address of every to recipient of r)
            set gotCc to my joined(address of every cc recipient of r)
            set gotBcc to my joined(address of every bcc recipient of r)
            set actualSender to ""
            try
                set actualSender to (sender of r) as text
            end try
            set closedIt to "no"
            if not showIt then
                try
                    close (every window whose id is wid) saving no
                    set closedIt to "yes"
                end try
            end if
        end tell
        my restoreClip()
        return "OK|to=" & gotTo & "|cc=" & gotCc & "|bcc=" & gotBcc & "|attachments=" & (attached as string) & "|closed=" & closedIt & "|from=" & actualSender
    on error errMsg number errNum
        -- Any runtime error (a missing Accessibility permission for System
        -- Events is the common one) ends here, never in half a reply.
        return my giveUp(wid, "error " & errNum & ": " & errMsg, savedIt)
    end try
end run
'''

REPLY_PREFIX = re.compile(r"^\s*(re|aw|sv|antw)\s*:", re.I)
REPLY_TIMEOUT = 180


@dataclass
class Original:
    """The message a reply answers, as Mail described it."""

    message_id: str
    sender: str
    subject: str
    date: str
    excerpt: str
    matches: int = 1
    mailbox: str = ""
    account: str = ""

    @property
    def address(self) -> str:
        from email.utils import parseaddr
        return parseaddr(self.sender)[1] or self.sender

    def describe(self) -> str:
        more = f", the newest of {self.matches} matches" if self.matches > 1 else ""
        return f"{self.sender}, '{self.subject}', {self.date}{more}"


def parse_reply_ref(ref: str) -> tuple[str, str]:
    """`<id@host>` or `id@host` is a Message-ID, anything else a subject to match."""
    ref = ref.strip()
    if ref.startswith("<") and ref.endswith(">"):
        return "id", ref[1:-1]
    if "@" in ref and not any(c.isspace() for c in ref):
        return "id", ref
    return "subject", ref


def reply_subject(subject: str) -> str:
    return subject if REPLY_PREFIX.match(subject) else f"Re: {subject}"


def find_original(ref: str) -> Original:
    kind, value = parse_reply_ref(ref)
    try:
        done = osascript(FIND, [kind, value], timeout=120)
    except subprocess.TimeoutExpired:
        raise ConfigError("Mail did not answer the search for the original within 120 s; "
                          "nothing was created") from None
    out = (done.stdout or "").rstrip("\n")
    if done.returncode != 0 or not out.startswith("OK"):
        raise ConfigError(f"could not ask Mail for the original message: {(done.stderr or out or 'no answer').strip()}")
    lines = out.split("\n")
    count = int(lines[1]) if len(lines) > 1 and lines[1].strip().isdigit() else 0
    if count == 0 or len(lines) < 8:
        where = "in any mailbox" if kind == "id" else "in the inbox"
        raise ConfigError(f"no message in Mail matches {'Message-ID' if kind == 'id' else 'subject'} "
                          f"'{value}' {where}; nothing was created")
    return Original(lines[2], lines[3], lines[4], lines[5], "\n".join(lines[8:]), count,
                    mailbox=lines[6], account=lines[7])


def _norm(text: str) -> str:
    return " ".join(text.replace(">", " ").split()).lower()


ATTRIBUTION = re.compile(r"(wrote|schrieb|a écrit|escribió|scrisse|schreef)\s*:\s*$", re.I)
QUOTE_HTML = re.compile(r"<blockquote\b", re.I)


def _split_text(text: str) -> tuple[str, str]:
    """Plain text at the start of the quote: the first `>` line, or the
    attribution line right above it ("On ..., X wrote:")."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            j = i
            while j > 0 and not lines[j - 1].strip():
                j -= 1
            if j > 0 and ATTRIBUTION.search(lines[j - 1]):
                j -= 1
            return "\n".join(lines[:j]), "\n".join(lines[j:])
    return text, ""


def _html_text(fragment: str) -> str:
    import html as h
    fragment = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", fragment)
    return h.unescape(re.sub(r"<[^>]+>", " ", fragment))


def _split_html(html: str) -> tuple[str, str]:
    """HTML at the first <blockquote>; the attribution line above it belongs to the quote."""
    m = QUOTE_HTML.search(html)
    if not m:
        return _html_text(html), ""
    above = _html_text(html[:m.start()]).splitlines()
    while above and not above[-1].strip():
        above.pop()
    attribution = [above.pop()] if above and ATTRIBUTION.search(above[-1]) else []
    return "\n".join(above), "\n".join(attribution) + "\n" + _html_text(html[m.start():])


def split_at_quote(saved: dict) -> tuple[str, str]:
    """(what the person wrote, the quote), normalised, from both parts of the saved draft.

    The checks look for the text and the footer only ABOVE the quote and for
    the quote only below it: in a thread the quote already holds the sender's
    name and signature, and a greeting may read like the original's first line.
    """
    t_above, t_below = _split_text(saved.get("text") or "")
    h_above, h_below = _split_html(saved.get("html") or "")
    return _norm(t_above + " " + h_above), _norm(t_below + " " + h_below)


def _addresses(header: str) -> set[str]:
    from email.utils import getaddresses
    return {a.lower() for _, a in getaddresses([header]) if a}


def reply_gaps(d, original: Original, saved: dict, set_to: bool = False) -> list[str]:
    """What the saved reply lacks: its text, its footer, the quote, attachments, recipients."""
    above, below = split_at_quote(saved)
    gaps = []
    body = d.text.split("\n-- \n", 1)[0]
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    if lines:
        # First, last and every line of prose (three words or more): a paste cut
        # off half way loses the end. Table rows and links read differently in
        # Mail's text and HTML, and a list marker is no evidence either way.
        picked = [lines[0], lines[-1], *(x for x in lines if len(x.split()) >= 3
                                         and "|" not in x and "://" not in x)]
        probes = {_norm(re.sub(r"^[^\w]+", "", x)[:60]) for x in picked} - {""}
        if any(probe not in above for probe in probes):
            gaps.append("the text")
    name = str((d.footer_cfg or {}).get("name") or "")
    if name and _norm(name) not in above:
        gaps.append("the footer")
    excerpt = [x.strip() for x in original.excerpt.splitlines() if x.strip()]
    probe = _norm(max(excerpt, key=len)[:40]) if excerpt else ""
    if not below or (probe and probe not in below):
        gaps.append("the quote of the original")
    expected = sorted(p.name for p in d.attachments if p.is_file())
    missing = [n for n in expected if n not in (saved.get("attachments") or [])]
    if missing:
        gaps.append("attachment(s) " + ", ".join(missing))
    if set_to:
        want = {r.address.lower() for r in d.to}
        got = _addresses(saved.get("to") or "")
        if want != got:
            gaps.append(f"the recipients {sorted(want)} (saved To: {sorted(got) or 'none'})")
    lost_cc = sorted({r.address.lower() for r in d.cc} - _addresses(saved.get("cc") or ""))
    if lost_cc:
        gaps.append("cc " + ", ".join(lost_cc))
    return gaps


def _recipient_gaps(d, fields: dict, set_to: bool) -> list[str]:
    """Whom the reply object holds, read back by the script, against what was asked."""
    got = {k: {a.strip().lower() for a in fields.get(k, "").split(",") if a.strip()} for k in ("to", "cc", "bcc")}
    gaps = []
    if set_to and got["to"] != {r.address.lower() for r in d.to}:
        gaps.append(f"To holds {sorted(got['to']) or 'nobody'}, not {sorted(r.address for r in d.to)}")
    for kind, wanted in (("cc", d.cc), ("bcc", d.bcc)):
        lost = sorted({r.address.lower() for r in wanted} - got[kind])
        if lost:
            gaps.append(f"{kind} lacks {', '.join(lost)}")
    return gaps


ACCESS_HINT = re.compile(r"-1719|-25211|-1743|assistive|not allowed", re.I)


def reply_handoff(d, workdir: Path, original: Original, show: bool = True, reply_all: bool = False,
                  set_to: bool = False) -> Handoff:
    """Answer `original` in Apple Mail. `set_to`: --to was given, so it replaces
    whom Mail chose; otherwise Mail's own reply recipients stay."""
    started = time.monotonic()
    before = inspect(d.subject)
    before_count = before[0] if before else 0
    # Pasted, the HTML is converted under the current appearance just like a
    # new draft's content, so it is the copy without dark-mode rules.
    write_inputs(d, workdir, d.html_static)
    try:
        done = osascript(REPLY, [str(workdir), "show" if show else "hide", original.message_id,
                                 "all" if reply_all else "one", "set" if set_to else "keep",
                                 original.mailbox, original.account], timeout=REPLY_TIMEOUT)
    except subprocess.TimeoutExpired:
        return Handoff(False, "apple-mail",
                       f"Mail did not finish the reply within {REPLY_TIMEOUT} s, so it was not checked. A reply "
                       "window may still be open and Mail may autosave it into Drafts: close it without saving, "
                       "delete any partial copy in Drafts, and check the clipboard, which may still hold the text",
                       verified=None)
    out = (done.stdout or "").strip()
    if out.startswith("ERR|gone"):
        return Handoff(False, "apple-mail", f"the original ({original.message_id}) is no longer in Mail; "
                       "nothing was created")
    if out.startswith("ERR|"):
        fields = answer_fields(out)
        why = out.split("|")[1]
        closed = fields.get("closed") == "yes"
        saved = fields.get("saved") == "yes"
        if why == "focus":
            head = "the reply window was not in front of Mail when the text was to be pasted, so nothing was pasted"
            tail = ". Run it again and do not type meanwhile"
        elif why == "window":
            head = "Mail opened no reply window that could be told apart from the others"
            tail = ""
        else:
            head = f"Mail stopped the reply ({why})"
            tail = (". Allow the terminal to control the computer (System Settings, Privacy & Security, "
                    "Accessibility) and run it again") if ACCESS_HINT.search(why) else ""
        state = ("; a copy WAS saved to Drafts before the error: delete it" if saved
                 else " and nothing was saved")
        left = "" if closed else "; close the reply window without saving"
        return Handoff(False, "apple-mail", head + state + left + tail, verified=None)
    if done.returncode != 0 or not out.startswith("OK"):
        return Handoff(False, "apple-mail", (done.stderr or out or "no answer").strip())
    fields = answer_fields(out)
    to_now = fields.get("to") or ""
    notes = [f"reply to {original.describe()}", f"To: {to_now or 'nobody'}"]
    if fields.get("cc"):
        notes.append(f"Cc: {fields['cc']}")
    actual = fields.get("from", "")
    if d.sender and d.sender.lower() not in actual.lower():
        notes.append(f"sender NOT {d.sender}: Mail kept {actual or 'its default'}; switch 'From' before sending")
    wrong = _recipient_gaps(d, fields, set_to)
    found = inspect(d.subject)
    if found is None:
        return Handoff(False, "apple-mail", ", ".join(notes + wrong) + ", Drafts not readable", verified=None)
    count, saved = found
    if not count > before_count:
        notes.append(f"Drafts holds {count} with this subject, as before ({before_count}): the reply was not saved")
        return Handoff(False, "apple-mail", ", ".join(notes), verified=False)
    count, saved = dedupe(d.subject, started, before_count, found, notes)
    gaps = wrong + reply_gaps(d, original, saved, set_to)
    if gaps:
        notes.append("the saved reply is missing or differs in " + "; ".join(gaps)
                     + "; fix it in the window or delete the draft")
        return Handoff(False, "apple-mail", ", ".join(notes), verified=True)
    notes.append("text, footer and quote in the saved reply"
                 + (f", {len(d.attachments)} attachment(s)" if d.attachments else ""))
    return Handoff(True, "apple-mail", ", ".join(notes), verified=True)
