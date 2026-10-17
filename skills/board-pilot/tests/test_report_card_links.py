"""The card as a NAVIGATION surface, and as a card somebody can read out loud.

`test_report_card.py` measures that a card is built and carries the right values.
This file measures the two things that decide whether the card is any use to a
person standing in front of it:

  L1-L4  LINKS   — a run touches four places (the item, the board, the pull request,
                   the journal) and the card carried a route to exactly ONE of them.
                   A reader who wanted the board had to know where it was.
  V1-V4  WORDS   — the outcome is engine vocabulary (`pass`, `reject`, `park`,
                   `dispatched, no result yet`). On a projector in a German room that
                   is the weakest line on the card.

The hard constraint both share: the card is a SECOND RENDERING of
`record.row_fields`, never a second source. A link may only be built from values
the event actually carries, and a word may only be SWAPPED, never invented. If the
card could show a value the ledger does not have, the two could disagree, and the
whole point of `_fields` going through one function would be gone.

The rule that follows, and the one most likely to be got wrong: a link whose
placeholder has no value for THIS event is dropped, not rendered empty. A button
that opens nothing gets tapped on stage and does nothing, which is worse than no
button at all.
"""
import pytest

from engine.card import build_card
from engine.config import CardConfig, load_pipeline_from_dict

_CHAIN = ("spec", "implement", "verify", "review", "pr")

_LABELS = {
    "incident": "Case",
    "step": "Phase {n} out of {m}",
    "armed": "armed · zero out of {m}",
    "item": "Ticket",
    "stage": "Phase",
    "kind": "Type",
    "criteria": "Yardstick",
    "duration": "Took",
    "outcome": "Result",
    "button": "Open ticket",
}

_LINKS = [
    {"label": "Board", "url": "https://github.com/orgs/acme/projects/35"},
    {"label": "Pull Request", "url": "{pr}"},
]

_WORDS = {
    "pass": "passed",
    "reject": "rejected",
    "park": "parked",
    "armed": "primed",
    "running": "in progress",
    "dispatched, no result yet": "kicked off, no result yet",
}


def _fields(**over):
    base = dict(when="w", stage="verify", kind="machine", criteria="verify.md@abc1234",
                took="1m37s", outcome="pass → reviewing")
    base.update(over)
    return base


def _card(**kw):
    kw.setdefault("incident", "LOOP-001")
    kw.setdefault("title", "Scrap rate rising")
    kw.setdefault("chain", _CHAIN)
    kw.setdefault("current", "verify")
    kw.setdefault("fields", _fields())
    kw.setdefault("labels", _LABELS)
    kw.setdefault("url", "https://github.com/acme/repo/issues/1")
    return build_card(kw.pop("event", "stage"), **kw)


def _content(card):
    return card["attachments"][0]["content"]


def _actions(card):
    return [(a["title"], a["url"]) for a in _content(card).get("actions", ())]


def _outcome_text(card):
    """The big line: the outcome, rendered once as its own block."""
    for block in _content(card)["body"]:
        if block.get("type") == "TextBlock" and block.get("size") == "Medium":
            return block["text"]
    raise AssertionError("no outcome block in the card")


def _facts(card):
    for block in _content(card)["body"]:
        if block.get("type") == "FactSet":
            return {f["title"]: f["value"] for f in block["facts"]}
    return {}


# === L: the card routes to every place the run touched =====================


def test_l1_without_links_the_card_carries_exactly_one_button(tmp_path):
    """Today's card, unchanged. The addition must not alter a card that did not
    ask for it."""
    assert _actions(_card()) == [("Open ticket", "https://github.com/acme/repo/issues/1")]


def test_l2_declared_links_become_buttons_after_the_item(tmp_path):
    """The item stays FIRST. It is the one destination every card shares, and the
    thing a reader reaches for without looking."""
    got = _actions(_card(links=[_LINKS[0]]))

    assert got == [
        ("Open ticket", "https://github.com/acme/repo/issues/1"),
        ("Board", "https://github.com/orgs/acme/projects/35"),
    ]


def test_l3_a_link_whose_value_is_missing_is_dropped_not_rendered_empty(tmp_path):
    """`{pr}` has no value on a stage card. A button that opens nothing gets tapped
    on stage and does nothing, which is worse than no button."""
    got = _actions(_card(links=_LINKS))

    assert [t for t, _ in got] == ["Open ticket", "Board"]
    assert all(url for _, url in got)


def test_l4_the_gate_card_gains_the_pull_request(tmp_path):
    """The one moment the PR exists, and the one card a human acts on."""
    got = _actions(_card(
        event="gate", current="pr",
        fields=_fields(stage="pr", outcome="pass → pr-open"),
        links=_LINKS,
        values={"pr": "https://github.com/acme/repo/pull/7"},
    ))

    assert ("Pull Request", "https://github.com/acme/repo/pull/7") in got
    assert got[0][0] == "Open ticket"


def test_l4_a_value_that_is_not_a_url_never_becomes_a_button(tmp_path):
    """`pr` is lifted out of a stage's stdout. Whatever else that line held must not
    be able to reach a button: an `Action.OpenUrl` with a non-URL is a card that
    fails to render on some clients, and a silent one on others."""
    got = _actions(_card(
        event="gate", current="pr", links=_LINKS,
        values={"pr": "no pull request was created"},
    ))

    assert [t for t, _ in got] == ["Open ticket", "Board"]


# === V: the words on the card, without a second source =====================


def test_v1_without_a_dictionary_the_outcome_is_the_engines_own_words(tmp_path):
    assert _outcome_text(_card()) == "pass → reviewing"


def test_v2_declared_words_are_swapped_and_the_rest_is_left_alone(tmp_path):
    """`reviewing` is a PIPELINE VALUE, not vocabulary — it is what the board column
    actually says, so translating it would make the card disagree with the board."""
    got = _outcome_text(_card(words=_WORDS))

    assert got == "passed → reviewing"


def test_v2_the_running_line_reads_as_a_sentence(tmp_path):
    """The stage_start line is the one a viewer sees for minutes at a time."""
    got = _outcome_text(_card(
        event="stage_start",
        fields=_fields(outcome="**running** · dispatched, no result yet", took="—"),
        words=_WORDS,
    ))

    assert "in progress" in got and "kicked off, no result yet" in got
    assert "running" not in got and "dispatched" not in got


def test_v3_an_unknown_word_survives_untouched(tmp_path):
    """Fail-soft in the direction that keeps information. A dictionary that silently
    blanks what it does not know would turn a missing entry into a missing fact."""
    got = _outcome_text(_card(fields=_fields(outcome="rewind → implementing"),
                              words=_WORDS))

    assert got == "rewind → implementing"


def test_v3_a_word_inside_another_word_is_not_swapped(tmp_path):
    """`pass` must not eat `passed`, `bypassed` or a branch called `pass-through`.
    Substring replacement is the obvious implementation and the wrong one."""
    got = _outcome_text(_card(fields=_fields(outcome="bypassed → passed-through"),
                              words=_WORDS))

    assert got == "bypassed → passed-through"


def test_v4_the_dictionary_touches_the_card_and_never_the_row(tmp_path):
    """THE INVARIANT. The card is a second rendering, not a second source. The value
    handed in must come back unmodified, so the ledger and the channel still mean the
    same thing even while they say it in different languages."""
    row = _fields()
    before = dict(row)

    card = build_card("stage", incident="X", title="t", chain=_CHAIN, current="verify",
                      fields=row, labels=_LABELS, url="", words=_WORDS)

    assert row == before, "build_card mutated the row it was handed"
    assert _facts(card)[_LABELS["outcome"]] == _outcome_text(card), \
        "the fact and the headline outcome disagree"


# === the config side: both blocks are validated at load ====================


def _load(card_block):
    return load_pipeline_from_dict({"pipeline": {
        "project": "p",
        "stages": [{"name": "pr", "run": "cmd:true", "on_success": "pr-open", "gate": "human"}],
        "report": {"targets": [{"name": "c", "type": "file", "path": "/tmp/x",
                                "card": card_block}]},
    }})


def test_c1_a_link_without_a_url_is_refused_at_load(tmp_path):
    with pytest.raises(ValueError, match="url"):
        _load({"links": [{"label": "Board"}]})


def test_c1_a_link_without_a_label_is_refused_at_load(tmp_path):
    with pytest.raises(ValueError, match="label"):
        _load({"links": [{"url": "https://example.invalid"}]})


def test_c2_the_blocks_reach_the_reporter(tmp_path):
    cfg = _load({"links": [{"label": "Board", "url": "https://example.invalid"}],
                 "words": {"pass": "passed"}})
    card = cfg.report[0].card

    assert isinstance(card, CardConfig)
    assert card.links == [{"label": "Board", "url": "https://example.invalid"}]
    assert card.words == {"pass": "passed"}
