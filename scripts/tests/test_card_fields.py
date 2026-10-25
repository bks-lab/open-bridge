# SPDX-License-Identifier: MIT
"""Contract for scripts/lib/bridge_cockpit/card_fields.py: the wire shape of a card and the `brief` block.

A brief is what a model (or a person) wrote about one item: a goal, an optional user story and a few
acceptance criteria, plus who wrote it, when, against which text (`basis`) and whether a person has
changed it since. It lives in two places with one shape: the `brief:` block of a STATUS.md and the
`describe` event of an inbox item. `validate_brief` is the one gate both pass, `brief_basis` the one way
to say which text a brief was written for, so a changed STATUS.md shows its brief as stale.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import card_fields as cf  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GOOD = {"goal": "Invoices reach the customer without a manual resend",
        "story": {"as": "an accountant", "want": "every invoice delivered once", "so_that": "nobody chases a resend"},
        "acceptance": ["A rejected invoice shows up in the inbox within an hour",
                       "No invoice is delivered twice"],
        "by": "claude-haiku-4-5-20251001", "at": "2026-10-25", "basis": "0123456789abcdef", "edited": False}


# ---------------------------------------------------------------- the wire shape

def test_card_fields_name_the_whole_wire_shape_in_order():
    assert cf.CARD_FIELDS == ("kind", "subkind", "title", "summary", "goal", "story", "acceptance", "next", "state",
                              "owner", "priority", "due", "area", "updated", "source", "links", "progress",
                              "written", "gaps")
    assert cf.NEXT_FIELDS == ("what", "who", "due", "from", "since")
    assert cf.STATE_FIELDS == ("word", "blocked_by", "since")
    assert cf.PROGRESS_FIELDS == ("done", "total")
    assert cf.STORY_FIELDS == ("as", "want", "so_that")
    assert cf.BRIEF_FIELDS == ("goal", "story", "acceptance", "by", "at", "basis", "edited")


def test_the_limits_are_the_ones_both_schemas_declare():
    status = yaml.safe_load((ROOT / "work/templates/_schema.status.yaml").read_text(encoding="utf-8"))
    brief = status["$defs"]["Brief"]
    assert status["properties"]["brief"] == {"$ref": "#/$defs/Brief"}
    assert brief["additionalProperties"] is False
    assert set(brief["properties"]) == set(cf.BRIEF_FIELDS)
    assert brief["properties"]["goal"]["maxLength"] == cf.BRIEF_LIMITS["goal"]
    assert brief["properties"]["acceptance"]["maxItems"] == cf.BRIEF_LIMITS["acceptance_items"]
    assert brief["properties"]["acceptance"]["items"]["maxLength"] == cf.BRIEF_LIMITS["acceptance_len"]
    for part in cf.STORY_FIELDS:
        assert brief["properties"]["story"]["properties"][part]["maxLength"] == cf.BRIEF_LIMITS["story"]
    item = yaml.safe_load((ROOT / "work/templates/_schema.inbox-item.yaml").read_text(encoding="utf-8"))
    assert item["$defs"]["brief"] == brief, "the inbox describe event carries the same brief as STATUS.md"


# ---------------------------------------------------------------- validate_brief

def test_a_good_brief_passes_unchanged():
    clean, errors = cf.validate_brief(GOOD)
    assert errors == []
    assert clean == GOOD
    assert clean is not GOOD


def test_a_brief_needs_only_a_goal():
    clean, errors = cf.validate_brief({"goal": "Close the account"})
    assert (clean, errors) == ({"goal": "Close the account"}, [])


@pytest.mark.parametrize("value", [None, "a goal", ["goal"], 3])
def test_anything_but_a_mapping_is_no_brief(value):
    clean, errors = cf.validate_brief(value)
    assert clean is None and errors


def test_a_brief_without_a_goal_is_none():
    clean, errors = cf.validate_brief({"acceptance": ["x works"]})
    assert clean is None
    assert any("goal" in e for e in errors)


def test_more_than_five_criteria_are_clipped_to_five_and_said():
    eight = [f"Criterion {n} holds" for n in range(8)]
    clean, errors = cf.validate_brief({"goal": "g", "acceptance": eight})
    assert clean["acceptance"] == eight[:5]
    assert any("acceptance" in e and "8" in e for e in errors)


def test_a_stream_brief_may_have_no_criteria():
    clean, errors = cf.validate_brief({"goal": "Keep the fleet patched", "acceptance": []})
    assert errors == [] and clean["acceptance"] == []


def test_over_long_texts_are_errors_and_left_out_never_cut():
    clean, errors = cf.validate_brief({"goal": "g", "acceptance": ["ok", "x" * 121],
                                       "story": {"as": "a" * 81, "want": "w", "so_that": "s"}})
    assert clean == {"goal": "g", "acceptance": ["ok"]}
    assert any("acceptance[1]" in e for e in errors)
    assert any("story.as" in e for e in errors)
    clean, errors = cf.validate_brief({"goal": "g" * 141})
    assert clean is None and any("goal" in e and "140" in e for e in errors)


@pytest.mark.parametrize("dash", [chr(0x2014), chr(0x2013)])  # em dash, en dash
def test_a_dash_as_punctuation_is_an_error_never_rewritten(dash):
    clean, errors = cf.validate_brief({"goal": "Ship it", "acceptance": [f"Green {dash} and merged", "Tagged"],
                                       "story": {"as": "a user", "want": f"less {dash} noise", "so_that": "calm"}})
    assert clean == {"goal": "Ship it", "acceptance": ["Tagged"]}
    assert len([e for e in errors if "dash" in e]) == 2
    clean, errors = cf.validate_brief({"goal": f"Ship {dash} now"})
    assert clean is None and any("dash" in e for e in errors)


def test_a_hyphen_inside_a_word_is_fine():
    clean, errors = cf.validate_brief({"goal": "Re-run the test-plan for 8-13 cases"})
    assert errors == [] and clean["goal"] == "Re-run the test-plan for 8-13 cases"


def test_a_story_needs_all_three_parts():
    clean, errors = cf.validate_brief({"goal": "g", "story": {"as": "a user", "want": "x"}})
    assert "story" not in clean
    assert any("story" in e and "so_that" in e for e in errors)


def test_unknown_keys_are_errors_and_dropped():
    clean, errors = cf.validate_brief({"goal": "g", "done_when": ["x"], "story": {**GOOD["story"], "why": "y"}})
    assert clean == {"goal": "g", "story": GOOD["story"]}
    assert any("done_when" in e for e in errors) and any("story.why" in e for e in errors)


@pytest.mark.parametrize("alias", ["haiku", "sonnet", "opus", "Haiku", "opus[1m]", ""])
def test_by_is_a_model_id_never_an_alias(alias):
    clean, errors = cf.validate_brief({"goal": "g", "by": alias})
    assert "by" not in clean and any("by" in e for e in errors)


def test_by_takes_any_versioned_model_id():
    for model in ("claude-haiku-4-5-20251001", "claude-opus-5-5", "gpt-5.1-mini"):
        clean, errors = cf.validate_brief({"goal": "g", "by": model})
        assert errors == [] and clean["by"] == model


def test_at_is_a_date_and_a_yaml_date_becomes_its_text():
    clean, errors = cf.validate_brief({"goal": "g", "at": dt.date(2026, 10, 25)})
    assert errors == [] and clean["at"] == "2026-10-25"
    clean, errors = cf.validate_brief({"goal": "g", "at": "25.10.2026"})
    assert "at" not in clean and errors


def test_basis_is_sixteen_hex_characters_and_edited_a_bool():
    clean, errors = cf.validate_brief({"goal": "g", "basis": "0123456789ABCDEF", "edited": "yes"})
    assert clean == {"goal": "g"}
    assert any("basis" in e for e in errors) and any("edited" in e for e in errors)



@pytest.mark.parametrize("key,value", [("basis", "0123456789abcdef\n"), ("by", "claude-haiku-4-5-20251001\n"),
                                       ("at", "2026-10-25\n")])
def test_a_trailing_newline_is_no_match(key, value):
    # `$` matches before a final newline; the stored value must be exactly what the schema pattern takes
    clean, errors = cf.validate_brief({"goal": "g", key: value})
    if key == "basis":
        assert "basis" not in clean and any("basis" in e for e in errors)
    else:  # by and at are texts a person may type, so their surrounding whitespace is dropped
        assert clean[key] == value.strip() and not errors


# ---------------------------------------------------------------- brief_basis

STATUS = """# yaml-language-server: $schema=../../templates/_schema.status.yaml
---
slug: invoices
status: doing
brief:
  goal: Invoices reach the customer
  acceptance:
    - No invoice twice

  by: claude-haiku-4-5-20251001
priority: P1
---

# Invoices

- [ ] resend the batch
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def test_basis_is_the_sha_prefix_of_the_text_without_the_brief_block():
    without = STATUS.replace("brief:\n  goal: Invoices reach the customer\n  acceptance:\n    - No invoice twice\n\n"
                             "  by: claude-haiku-4-5-20251001\n", "")
    assert cf.brief_basis(STATUS) == _sha(without)
    assert len(cf.brief_basis(STATUS)) == 16


def test_writing_or_rewriting_the_brief_keeps_the_basis():
    bare = STATUS.replace("brief:\n  goal: Invoices reach the customer\n  acceptance:\n    - No invoice twice\n\n"
                          "  by: claude-haiku-4-5-20251001\n", "")
    inline = bare.replace("priority: P1\n", "brief: {goal: Something else}\npriority: P1\n")
    assert cf.brief_basis(bare) == cf.brief_basis(STATUS) == cf.brief_basis(inline)



def test_a_brief_appended_with_a_separator_line_keeps_the_basis():
    bare = STATUS.replace("brief:\n  goal: Invoices reach the customer\n  acceptance:\n    - No invoice twice\n\n"
                          "  by: claude-haiku-4-5-20251001\n", "")
    appended = bare.replace("priority: P1\n---", "priority: P1\n\nbrief:\n  goal: Invoices reach the customer\n---")
    assert cf.brief_basis(appended) == cf.brief_basis(bare)


def test_only_one_separator_line_belongs_to_the_brief():
    bare = "---\nslug: a\n\nstatus: doing\n---\n"
    assert cf.brief_basis("---\nslug: a\n\nbrief: {goal: g}\nstatus: doing\n---\n") == cf.brief_basis(
        "---\nslug: a\nstatus: doing\n---\n")
    assert cf.brief_basis(bare) != cf.brief_basis("---\nslug: a\nstatus: doing\n---\n")

def test_any_other_change_moves_the_basis():
    assert cf.brief_basis(STATUS) != cf.brief_basis(STATUS.replace("status: doing", "status: review"))
    assert cf.brief_basis(STATUS) != cf.brief_basis(STATUS.replace("- [ ] resend", "- [x] resend"))


def test_a_brief_word_in_the_body_is_not_the_block():
    text = STATUS + "\nbrief:\n  not front matter\n"
    assert cf.brief_basis(text) != cf.brief_basis(STATUS)


def test_line_endings_do_not_move_the_basis():
    assert cf.brief_basis(STATUS.replace("\n", "\r\n")) == cf.brief_basis(STATUS)


def test_the_template_example_passes_the_schema_and_the_gate():
    lines = (ROOT / "work/templates/STATUS.md").read_text(encoding="utf-8").splitlines()
    start = lines.index("# brief:")
    block = []
    for line in lines[start:]:
        if not line.startswith("# ") or (block and not line.startswith("#   ")):
            break
        block.append(line[2:])
    example = yaml.safe_load("\n".join(block).replace("YYYY-MM-DD", "2026-10-25"))["brief"]
    clean, errors = cf.validate_brief(example)
    assert errors == [] and clean["acceptance"]
    jsonschema = pytest.importorskip("jsonschema")
    schema = yaml.safe_load((ROOT / "work/templates/_schema.status.yaml").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator({**schema["$defs"]["Brief"], "$defs": schema["$defs"]},
                                                format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    assert list(validator.iter_errors(clean)) == []
    assert list(validator.iter_errors({**clean, "by": "haiku"})), "the schema refuses an alias too"
