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
    if count > before_count + 1:
        # Measured 2026-10-07 on an Exchange account: one run left two drafts
        # five seconds apart (Mail's own autosave of the new window, then the
        # explicit save), and Exchange kept both. Only copies with this subject
        # created during THIS run are removed, never an older draft.
        window = int(time.monotonic() - started) + 5
        done = osascript(DEDUPE, [d.subject, str(window)], timeout=60)
        removed = (done.stdout or "").strip()
        if removed.isdigit() and int(removed):
            notes.append(f"removed {removed} duplicate(s) Mail saved during this run")
            found = inspect(d.subject) or found
            count, saved = found
    expected = sorted(p.name for p in d.attachments if p.is_file())
    if sorted(saved["attachments"]) != expected:
        notes.append(f"attachments in the saved draft: {saved['attachments'] or 'none'}, "
                     f"expected {expected}; attach them by hand before sending")
        return Handoff(False, "apple-mail", ", ".join(notes), verified=True)
    if expected:
        notes.append(f"{len(expected)} attachment(s) in the saved draft")
    return Handoff(True, "apple-mail", ", ".join(notes), verified=True)


def inspect(subject: str) -> tuple[int, dict] | None:
    """Read the saved draft back from a fresh process: count, attachments, sender.

    The creating script's own counts are not evidence: it counted an attachment
    that the saved draft did not contain.
    """
    done = osascript(VERIFY, [subject], timeout=60)
    raw = done.stdout or ""
    head, _, source = raw.partition("\n")
    try:
        count = int(head.strip())
    except ValueError:
        return None
    saved = {"attachments": [], "from": "", "text": "", "html": ""}
    if source.strip():
        import email
        from email import policy
        msg = email.message_from_string(source, policy=policy.default)
        saved["from"] = str(msg.get("From", ""))
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
# first that Mail is the frontmost app and its front window is this reply,
# and gives up (closing the reply unsaved) instead of pasting elsewhere. The
# saved draft is then read back from Drafts and checked for the text, the
# footer, the quote and every attachment, because the creating script cannot
# see what Mail really stored.

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
        set excerpt to ""
        try
            set excerpt to content of best
        end try
    end tell
    if (length of excerpt) > 400 then set excerpt to text 1 thru 400 of excerpt
    return "OK" & linefeed & (n as string) & linefeed & mid & linefeed & who & linefeed & subj & linefeed & dr & linefeed & excerpt
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

-- Mail is the frontmost app AND its front window is this reply. Anything else
-- means a paste would land in somebody's other text.
on replyInFront(s)
    tell application "System Events"
        set frontName to name of first application process whose frontmost is true
    end tell
    if frontName is not "Mail" then return false
    tell application "Mail"
        if (count of windows) is 0 then return false
        set wname to name of front window
    end tell
    return wname is s
end replyInFront

-- The only paste in this script, and it checks the focus first.
on pasteIfFront(s)
    if not my replyInFront(s) then return false
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

-- Nothing half done stays behind: the reply is closed WITHOUT saving, unless
-- a window with this subject was already open (it may be the person's own).
on giveUp(s, preWindows, why)
    set closedIt to "no"
    if preWindows is 0 then
        try
            tell application "Mail" to close (every window whose name is s) saving no
            set closedIt to "yes"
        end try
    end if
    my restoreClip()
    return "ERR|" & why & "|closed=" & closedIt
end giveUp

on run argv
    set d to item 1 of argv
    set showIt to ((item 2 of argv) is "show")
    set mid to item 3 of argv
    set toAll to ((item 4 of argv) is "all")
    set theSubject to my readFile(d & "/subject.txt")
    set theHtml to my readFile(d & "/body.html")
    set theText to my readFile(d & "/body.txt")
    set theSender to my readFile(d & "/sender.txt")
    set attList to my nonEmptyLines(my readFile(d & "/attachments.txt"))
    try
        set savedClip to the clipboard as text
    end try
    tell application "Mail"
        set hits to (messages of inbox whose message id is mid)
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
        if (count of hits) is 0 then return "ERR|gone|closed=no"
        set orig to item 1 of hits
        set preWindows to count of (every window whose name is theSubject)
        if toAll then
            set r to reply orig with opening window and reply to all
        else
            set r to reply orig with opening window
        end if
        set replySubject to subject of r
        if theSubject is not "" and theSubject is not replySubject then set subject of r to theSubject
        if theSender is not "" then
            try
                set sender of r to theSender
            end try
        end if
        activate
    end tell
    delay 1.5
    my putHtml(theHtml, theText)
    if not my pasteIfFront(theSubject) then return my giveUp(theSubject, preWindows, "focus")
    set attached to 0
    repeat with p in attList
        set the clipboard to (POSIX file (p as text))
        if not my pasteIfFront(theSubject) then return my giveUp(theSubject, preWindows, "focus")
        set attached to attached + 1
    end repeat
    -- An attachment is still loading for a moment after the paste.
    delay 2
    tell application "Mail"
        save r
        delay 1
        set nTo to (count of to recipients of r) as string
        set actualSender to ""
        try
            set actualSender to (sender of r) as text
        end try
        set closedIt to "no"
        if not showIt and preWindows is 0 then
            try
                close (every window whose name is theSubject) saving no
                set closedIt to "yes"
            end try
        end if
    end tell
    my restoreClip()
    return "OK|to=" & nTo & "|attachments=" & (attached as string) & "|closed=" & closedIt & "|from=" & actualSender
end run
'''

REPLY_PREFIX = re.compile(r"^\s*(re|aw|sv|antw)\s*:", re.I)


@dataclass
class Original:
    """The message a reply answers, as Mail described it."""

    message_id: str
    sender: str
    subject: str
    date: str
    excerpt: str
    matches: int = 1

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
    done = osascript(FIND, [kind, value], timeout=120)
    out = (done.stdout or "").rstrip("\n")
    if done.returncode != 0 or not out.startswith("OK"):
        raise ConfigError(f"could not ask Mail for the original message: {(done.stderr or out or 'no answer').strip()}")
    lines = out.split("\n")
    count = int(lines[1]) if len(lines) > 1 and lines[1].strip().isdigit() else 0
    if count == 0 or len(lines) < 6:
        where = "in any mailbox" if kind == "id" else "in the inbox"
        raise ConfigError(f"no message in Mail matches {'Message-ID' if kind == 'id' else 'subject'} "
                          f"'{value}' {where}; nothing was created")
    return Original(lines[2], lines[3], lines[4], lines[5], "\n".join(lines[6:]), count)


def _norm(text: str) -> str:
    return " ".join(text.replace(">", " ").split()).lower()


def _visible(saved: dict) -> str:
    import html as h
    from_html = h.unescape(re.sub(r"<[^>]+>", " ", saved.get("html") or ""))
    return _norm((saved.get("text") or "") + " " + from_html)


def reply_gaps(d, original: Original, saved: dict) -> list[str]:
    """What the saved reply lacks: its text, its footer, the quote, attachments."""
    seen = _visible(saved)
    gaps = []
    body = d.text.split("\n-- \n", 1)[0]
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    if lines:
        probe = _norm(max(lines, key=len)[:60])
        if probe not in seen:
            gaps.append("the text")
    name = str((d.footer_cfg or {}).get("name") or "")
    if name and _norm(name) not in seen:
        gaps.append("the footer")
    excerpt = next((x.strip() for x in original.excerpt.splitlines() if x.strip()), "")
    raw_html = (saved.get("html") or "").lower()
    quoted = (excerpt and _norm(excerpt[:40]) in seen) or 'type="cite"' in raw_html or "<blockquote" in raw_html
    if not quoted:
        gaps.append("the quote of the original")
    expected = sorted(p.name for p in d.attachments if p.is_file())
    missing = [n for n in expected if n not in (saved.get("attachments") or [])]
    if missing:
        gaps.append("attachment(s) " + ", ".join(missing))
    return gaps


def reply_handoff(d, workdir: Path, original: Original, show: bool = True, reply_all: bool = False) -> Handoff:
    before = inspect(d.subject)
    before_count = before[0] if before else 0
    # Pasted, the HTML is converted under the current appearance just like a
    # new draft's content, so it is the copy without dark-mode rules.
    write_inputs(d, workdir, d.html_static)
    done = osascript(REPLY, [str(workdir), "show" if show else "hide", original.message_id,
                             "all" if reply_all else "one"], timeout=180)
    out = (done.stdout or "").strip()
    if out.startswith("ERR|focus"):
        closed = "closed=yes" in out
        return Handoff(False, "apple-mail",
                       "the reply window was not in front of Mail when the text was to be pasted, so nothing "
                       "was pasted and nothing was saved" + ("" if closed else
                       "; close the reply window without saving") + ". Run it again and do not type meanwhile",
                       verified=None)
    if out.startswith("ERR|gone"):
        return Handoff(False, "apple-mail", f"the original ({original.message_id}) is no longer in Mail; "
                       "nothing was created")
    if done.returncode != 0 or not out.startswith("OK"):
        return Handoff(False, "apple-mail", (done.stderr or out or "no answer").strip())
    fields = answer_fields(out)
    notes = [f"reply to {original.describe()}", f"{fields.get('to')} recipient(s)"]
    actual = fields.get("from", "")
    if d.sender and d.sender.lower() not in actual.lower():
        notes.append(f"sender NOT {d.sender}: Mail kept {actual or 'its default'}; switch 'From' before sending")
    found = inspect(d.subject)
    if found is None:
        return Handoff(False, "apple-mail", ", ".join(notes) + ", Drafts not readable", verified=None)
    count, saved = found
    if not count > before_count:
        notes.append(f"Drafts holds {count} with this subject, as before ({before_count}): the reply was not saved")
        return Handoff(False, "apple-mail", ", ".join(notes), verified=False)
    gaps = reply_gaps(d, original, saved)
    if gaps:
        notes.append("the saved reply is missing " + ", ".join(gaps)
                     + "; complete it in the window or delete the draft")
        return Handoff(False, "apple-mail", ", ".join(notes), verified=True)
    notes.append("text, footer and quote in the saved reply"
                 + (f", {len(d.attachments)} attachment(s)" if d.attachments else ""))
    return Handoff(True, "apple-mail", ", ".join(notes), verified=True)
