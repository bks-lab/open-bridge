"""The second rendering of one event: an adaptive card, for a human at a distance.

WHY A CARD AND NOT JUST THE ROW
-------------------------------
`report.py` renders every event as one table row, the same six values the sticky
board comment carries. That row is right for a ledger and wrong for a room: it is
one line of small grey text, and a reader three metres from a screen cannot tell
two of them apart, let alone see that six of them belong to one incident.

This module renders the SAME six values a second way. It invents nothing: every
value it prints is handed in, already derived and already scrubbed by
`record.row_fields`. What it adds is shape — a coloured band that is identical on
every card of a run, a progress bar, and one button that always points at the same
place — so that belonging is visible before anything is read.

THE COUNT HAS ONE SOURCE, AND IT IS NOT THIS FILE
-------------------------------------------------
`chain` is the engine's own stage list, passed down from the config the engine
runs. The denominator is `len(chain)` and the numerator is the position of the
stage in it. Neither is written anywhere as a number: add a stage and every card
follows. That is deliberate and it is the scar of a real failure — the same count
once existed as three declarations in two files, one of them prose, with nothing
comparing them, so the channel showed six while the declared source said five.
`config.validate_report` refuses a `step` label that carries a digit for exactly
this reason: a label with a number in it is that third declaration.

VERSION 1.4, DELIBERATELY
-------------------------
`showBorder` and `roundedCorners` are 1.5 affordances, and a 1.5 card is reported
to fail rendering entirely on some clients ("We're sorry, this card couldn't be
displayed"). The only shape proven on this channel is 1.4, so the colour comes
from container `style` rather than from a border. `msteams.width: Full` is not a
version-gated feature and is the single largest legibility win on a projector.

The labels are ENGLISH here and configurable per target. This skill is `scope:
core` and ships into whatever repo it drives; the language of a channel belongs to
the instance that owns the channel, so it lives in the project YAML.
"""
from __future__ import annotations

import re

CARD_VERSION = "1.4"

# The container style that carries the band, per event. `style` is the 1.2 way to
# get colour; the values are Adaptive Cards' own vocabulary, not hand-picked hexes.
_ACCENT = {
    "armed": "accent",
    "stage": "emphasis",
    "reject": "attention",
    "park": "warning",
    "gate": "good",
    # A note is not a state change, so it gets the quietest style there is.
    "note": "default",
}
_ACCENT_DEFAULT = "emphasis"

# The bar: what a stage looks like once it is behind us, while it runs, and before
# it is reached.
_BAR_DONE, _BAR_CURRENT, _BAR_PENDING = "good", "accent", "emphasis"

DEFAULT_LABELS = {
    "incident": "Incident",
    # MUST carry {n} and {m} and MUST NOT carry a digit — see the module docstring.
    "step": "Step {n} of {m}",
    # MAY carry {m} — and when it does, MUST NOT carry a digit, for the same reason
    # `step` must not: the total has one source and it is `len(chain)`. Carrying it
    # here is what makes the ARM card say how long the chain is BEFORE the first
    # stage runs, which is the one moment a viewer has nothing else to judge by.
    "armed": "armed · none of {m}",
    "item": "Item",
    "stage": "Stage",
    "kind": "Kind",
    "criteria": "Criteria",
    "duration": "Duration",
    "outcome": "Outcome",
    "button": "Open item",
    # The journey line: where this card sits in the chain, in words rather than a
    # number. Every value comes from `chain` and `current`, which the card already
    # has — a hand-written predecessor list would be a SECOND declaration of the
    # chain and wrong the day somebody inserts a stage.
    "journey_prev": "before {prev}",
    "journey_now": "now {now}",
    "journey_next": "next {next}",
}
LABEL_KEYS = tuple(DEFAULT_LABELS)

# The row fields this module reads. Named so a change in `record._ROW_FIELDS` that
# never reaches here fails loudly on a KeyError instead of rendering a blank card.
_FACT_FIELDS = (("stage", "stage"), ("kind", "kind"), ("criteria", "criteria"),
                ("duration", "took"), ("outcome", "outcome"))


def step_of(chain, current):
    """1-based position of `current` in `chain`, or None when there is no stage.

    None is the honest answer at ARM: the dispatch loop has not run, so no stage is
    resolved yet, and borrowing the first stage's number would claim work that has
    not started.
    """
    try:
        return list(chain).index(current) + 1
    except (ValueError, TypeError):
        return None


def progress_bar(chain, step):
    """One narrow column per stage: done, current, pending.

    The same information as "Step 3 of 5", seen instead of read. It is the only
    part of the card that tells a viewer WITHOUT reading that this message belongs
    to a chain and where the chain stands.
    """
    columns = []
    for i, name in enumerate(chain, start=1):
        if step is None:
            style = _BAR_PENDING
        elif i < step:
            style = _BAR_DONE
        elif i == step:
            style = _BAR_CURRENT
        else:
            style = _BAR_PENDING
        columns.append({
            "type": "Column",
            "width": "stretch",
            "style": style,
            "items": [{
                "type": "TextBlock",
                "text": str(i),
                "size": "Small",
                "horizontalAlignment": "Center",
                "weight": "Bolder" if step is not None and i == step else "Default",
                "wrap": False,
            }],
        })
    return {"type": "ColumnSet", "columns": columns, "spacing": "Small"}


def _format_tolerant(template, **values):
    """Substitute the placeholders we know and leave anything else literally.

    `str.format` raises on an unknown key, and this runs inside a report sink where
    a raise costs a ledger line and buys nothing. A label is presentation; a typo in
    one must show up as a visible `{typo}` on the card, not as a silent gap in the
    channel while the run continues.
    """
    out = str(template)
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def headline(*, incident, title, chain, current, labels):
    """The line that makes five separate posts read as one story.

    It carries the step and the item's own title. The INCIDENT sits above it, in
    the band, because that is the part which must be identical on every card.
    """
    step = step_of(chain, current)
    if step:
        where = labels["step"].format(n=step, m=len(chain))
    else:
        # `armed` is allowed to carry {m} and allowed not to, so it is formatted
        # TOLERANTLY: an instance that just wants the word "armiert" must not have
        # its card blow up on a KeyError inside a report sink, which is the one
        # place an exception is most expensive and least visible.
        where = _format_tolerant(labels["armed"], m=len(chain))
    return " · ".join(p for p in (where, str(title or "")) if p)


def journey(chain, current, labels, names=None):
    """Previous, current and next stage as one line. Empty when unresolved.

    Empty is the honest answer at ARM and for a stage outside the chain: a line
    built from an unresolved position would put the first stage's name on a card
    describing something that has not run.

    `names` renames a stage WHERE IT IS INSERTED, and that is deliberately not the
    card's `words` dictionary. `words` is applied to the outcome, which carries the
    values that are really in the board column (`pass → pr-ready`); `say()`
    replaces whole words and a hyphen is a word boundary, so a `pr: Pull-Request`
    entry there rewrote `pr-ready` into `Pull-Request-ready` — a card claiming a
    column value that does not exist. Stage ids and pipeline values collide by
    construction, so they get two dictionaries.

    An unmapped stage appears as itself. A partial mapping is the normal case.
    """
    names = names or {}
    step = step_of(chain, current)
    if not step:
        return ""
    stages = list(chain)
    parts = []
    if step > 1:
        parts.append(_format_tolerant(labels.get("journey_prev", "before {prev}"),
                                      prev=names.get(stages[step - 2], stages[step - 2])))
    parts.append(_format_tolerant(labels.get("journey_now", "now {now}"),
                                  now=names.get(stages[step - 1], stages[step - 1])))
    if step < len(stages):
        parts.append(_format_tolerant(labels.get("journey_next", "next {next}"),
                                      next=names.get(stages[step], stages[step])))
    return " · ".join(parts)


_URL_SCHEMES = ("https://", "http://")


def is_url(value) -> bool:
    """A button target, or not one at all.

    `Action.OpenUrl` with a non-URL fails to render on some clients and does
    nothing on others, and the values that feed a link are LIFTED FROM STAGE
    OUTPUT — a stage that printed a sentence instead of a URL must not be able to
    put that sentence on a button.
    """
    return isinstance(value, str) and value.startswith(_URL_SCHEMES)


def say(text, words):
    """Swap declared words in an engine-authored line, leave everything else.

    Three properties, each one a way this goes wrong:

    - **Whole words only.** Substring replacement is the obvious implementation and
      turns `bypassed` into `bybestandened`. The boundary is a regex `\b`.
    - **Longest key first**, so a dictionary carrying both `dispatched` and
      `dispatched, no result yet` cannot have the short key shred the long one.
    - **Unknown stays.** A word with no entry is passed through unchanged. Blanking
      it would turn a missing dictionary entry into a missing fact, which is the
      expensive direction to fail in.

    This is presentation, NOT a second source: it never invents a value, only
    renames one the caller already had. `record.row_fields` is untouched, so the
    ledger and the card still mean the same thing while saying it differently.
    """
    if not words:
        return text
    out = str(text)
    for key in sorted(words, key=len, reverse=True):
        out = re.sub(r"\b" + re.escape(str(key)) + r"\b", str(words[key]), out)
    return out


def buttons(labels, url, links, values):
    """The item first, then whatever the instance declared, minus what has no value.

    The item is first because it is the one destination every card of a run shares
    and the one a reader reaches for without looking. Everything after it is
    optional and per-instance: a board, a pull request, a dashboard.

    A link whose placeholder has no value for THIS event is DROPPED. A stage card
    has no pull request, and a button that opens nothing gets tapped on stage and
    does nothing, which is worse than no button at all.
    """
    out = []
    if url:
        out.append({"type": "Action.OpenUrl", "title": labels["button"], "url": str(url)})
    for link in links or ():
        target = _format_tolerant(link.get("url", ""), **(values or {}))
        if not is_url(target):
            continue
        out.append({"type": "Action.OpenUrl", "title": str(link.get("label", "")), "url": target})
    return out


def build_card(event, *, incident, title, chain, current, fields, labels=None,
               url="", sender="", item_ref="", links=None, words=None, values=None,
               names=None):
    """One event → one adaptive card. Every value comes in already derived.

    `fields` is the dict `record.row_fields` returns — the same six values the
    sticky comment renders. This function never derives one of its own, which is
    what keeps the board and the channel from disagreeing.
    """
    labels = {**DEFAULT_LABELS, **(labels or {})}
    chain = tuple(chain or ())

    band = [{
        "type": "TextBlock",
        "text": f"{labels['incident']} {incident}".strip(),
        "weight": "Bolder",
        "wrap": True,
    }]
    if sender:
        band.insert(0, {"type": "TextBlock", "text": sender, "isSubtle": True,
                        "size": "Small", "spacing": "None", "wrap": True})
    band.append({
        "type": "TextBlock",
        "text": headline(incident=incident, title=title, chain=chain,
                         current=current, labels=labels),
        "isSubtle": True,
        "size": "Small",
        "spacing": "None",
        "wrap": True,
    })

    # Said ONCE, used twice. The big line and the fact must be the same string, or
    # one card contradicts itself while both halves come from the same source.
    outcome = say(fields["outcome"], words)

    facts = []
    if item_ref:
        facts.append({"title": labels["item"], "value": str(item_ref)})
    for label_key, field_key in _FACT_FIELDS:
        value = outcome if field_key == "outcome" else str(fields[field_key])
        facts.append({"title": labels[label_key], "value": value})

    # `names` first, `say()` after: the line is engine-authored, so the ordinary
    # word dictionary still applies to the words this module wrote.
    weg = say(journey(chain, current, labels, names), words)

    body = [
        {"type": "Container", "style": _ACCENT.get(event, _ACCENT_DEFAULT),
         "bleed": True, "items": band},
        progress_bar(chain, step_of(chain, current)),
        {"type": "TextBlock", "size": "Medium", "weight": "Bolder",
         "text": outcome, "wrap": True},
        {"type": "FactSet", "facts": facts},
    ]
    if weg:
        # Under the bar and above the headline fact: it answers "where am I",
        # which is the question a viewer asks before "what happened".
        body.insert(2, {"type": "TextBlock", "text": weg, "isSubtle": True,
                        "size": "Small", "wrap": True, "spacing": "Small"})

    content = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": CARD_VERSION,
        # The single largest legibility win on a projector, and not version-gated.
        # Worth checking on a phone once: full width can truncate in narrow form
        # factors, and the stage is watched on both.
        "msteams": {"width": "Full"},
        "body": body,
    }
    # Always OpenUrl. The channel's trigger does not support actionable messages, so
    # an Action.Submit would fail silently rather than loudly.
    actions = buttons(labels, url, links, values)
    if actions:
        content["actions"] = actions

    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive",
        "contentUrl": None,
        "content": content,
    }]}
