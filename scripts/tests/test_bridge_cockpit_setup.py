# SPDX-License-Identifier: MIT
"""Contract for the cockpit's Setup page (scripts/bridge-setup.py, briefing.py collect --setup).

The first visit of the cockpit advises on setting the Bridge up; a later visit says on the same page
what still keeps the cockpit from working well. The page is three ordinary `command` sections, so the
row machinery acts: a finding gets Let AI do it, Advise, Close and Later, and an item filed for a row
that is gone closes by itself after a full pass.

- `check --part checks`: a finding only when something is actually wrong, an empty list when all is well;
  read only, each probe short, an external tool probed only for an integration that is switched on;
- `check --part available`: catalogue features that are off and not silenced, each naming how it is
  switched on, with the steps later and not for me; `--part on`: what is on, information only;
- `act <id> later|silence`: the only write, into work/onboarding-state.yaml, with an undo token the
  command checks itself;
- the catalogue (skills/bridge-onboard/references/features.yaml) has one entry or skip per heading of
  feature-catalog.md, and names no heading it does not have.

Run: pytest -q scripts/tests/test_bridge_cockpit_setup.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit.config import load_web_config  # noqa: E402


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bs = _load("bridge_setup", ROOT / "scripts" / "bridge-setup.py")
bf = _load("briefing", ROOT / "scripts" / "briefing.py")
bv = _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")

TODAY = dt.date(2026, 10, 28)
GOOD = {"work": {"enabled": True}, "inbox": {"runner": "homebox"}, "language": {"conversation": "en"},
        "cockpit": {"enabled": True}}


class Probes:
    """Stands in for the two probes that leave the Bridge's files: the terminal driver and the gh CLI."""

    def __init__(self, launch=True, gh="ok"):
        self._launch, self._gh, self.calls = launch, gh, []

    def launch(self):
        self.calls.append("launch")
        return self._launch

    def gh(self):
        self.calls.append("gh")
        return self._gh


def bridge(tmp: Path, cfg: dict | None = None, profile: str | None = "mine") -> Path:
    root = tmp / "bridge"
    (root / "workflow" / "briefings").mkdir(parents=True)
    (root / "bridge-config.yaml").write_text(yaml.safe_dump(GOOD if cfg is None else cfg), encoding="utf-8")
    if profile:
        (root / "workflow" / "briefings" / f"{profile}.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "scope": "user", "id": profile, "for": "ada",
            "sections": [{"kind": "inbox"}, {"kind": "tracker", "id": "gh", "provider": "github",
                                             "query": {"owners": ["example-org"]}}]}), encoding="utf-8")
    return root


def ids(rows) -> list:
    return [r["id"] for r in rows]


def checks(root, probes=None):
    return bs.check_part(root, "checks", probes=probes or Probes(), today=TODAY)


# ---------------------------------------------------------------- the catalogue

def catalog_headings() -> list:
    text = (ROOT / "skills" / "bridge-onboard" / "references" / "feature-catalog.md").read_text(encoding="utf-8")
    return re.findall(r"^### (.+?)\s*$", text, re.M)


def test_every_catalogue_heading_has_one_entry_or_skip_and_no_entry_names_another():
    entries = bs.load_catalog()
    named = [e["catalog"] for e in entries]
    headings = catalog_headings()
    assert sorted(set(headings) - set(named)) == [], "a heading of feature-catalog.md has no entry in features.yaml"
    assert sorted(set(named) - set(headings)) == [], "an entry of features.yaml names a heading the catalogue lacks"
    assert len(named) == len(set(named)), "a heading has two entries"


def test_every_entry_says_how_it_is_on_how_it_is_switched_on_and_where_its_state_lives():
    groups = {"identity", "communication", "infrastructure", "productivity", "integrations", "visualization"}
    features = [e for e in bs.load_catalog() if "skip" not in e]
    assert features
    for e in features:
        assert re.fullmatch(r"[a-z][a-z0-9-]{0,39}", e["id"]), e
        assert e["group"] in groups, e
        assert e["title"].strip() and e["when"].strip() and e["activate"].strip(), e
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,39}", e["state_key"]), e
        assert isinstance(e["enabled_when"], list) and e["enabled_when"], e
        for test in e["enabled_when"] + (e["offer_only_when"] if isinstance(e.get("offer_only_when"), list) else []):
            assert isinstance(test, dict) and len(test) == 1 and next(iter(test)) in ("config", "files", "exists"), e
        assert e.get("offer_only_when", []) == "never" or isinstance(e.get("offer_only_when", []), list), e
        if e.get("doc"):
            assert (ROOT / e["doc"]).is_file(), e["doc"]
    for key in ("id", "state_key"):
        values = [e[key] for e in features]
        assert len(values) == len(set(values)), key
    for e in bs.load_catalog():
        if "skip" in e:
            assert set(e) == {"catalog", "skip"} and e["skip"].strip(), e


def test_the_catalogue_rules_the_offers_it_spells_out():
    by_id = {e["id"]: e for e in bs.load_catalog() if "skip" not in e}
    deck = next(e for e in bs.load_catalog() if e["catalog"].startswith("Bridge-Deck"))
    assert "skip" in deck                                           # not public yet: never offered
    assert {"config": "integrations.typesafe.key_ref"} in by_id["jev"]["offer_only_when"]
    assert {"exists": "mods/cockpit-relay"} in by_id["cockpit-relay"]["offer_only_when"]
    assert by_id["github-projects"]["enabled_when"] == [{"config": "integrations.github.enabled"}]


# ---------------------------------------------------------------- checks: findings only when something is wrong

def test_a_bridge_set_up_well_has_no_finding(tmp_path):
    assert checks(bridge(tmp_path)) == []


def test_task_management_off_is_a_finding(tmp_path):
    root = bridge(tmp_path, {**GOOD, "work": {"enabled": False}})
    rows = checks(root)
    assert ids(rows) == ["work-off"]
    assert rows[0]["tone"] == "warn" and "work.enabled" in rows[0]["detail"]


def test_no_terminal_driver_is_a_finding_and_an_unknown_answer_is_none(tmp_path):
    root = bridge(tmp_path)
    rows = checks(root, Probes(launch=False))
    assert ids(rows) == ["no-driver"] and "workplace.driver" in rows[0]["detail"]
    assert checks(root, Probes(launch=None)) == []


def test_inbox_approvals_without_a_runner_are_a_finding(tmp_path):
    cfg = {k: v for k, v in GOOD.items() if k != "inbox"}
    rows = checks(bridge(tmp_path, cfg))
    assert ids(rows) == ["no-runner"]
    assert "inbox.runner" in rows[0]["detail"] and "inbox.py run" in rows[0]["detail"]


def test_only_the_builtin_profile_is_a_finding(tmp_path):
    rows = checks(bridge(tmp_path, profile=None))
    assert ids(rows) == ["builtin-profile"]
    assert "workflow/briefings/_template.yaml" in rows[0]["detail"]


def test_a_profile_copied_from_the_template_keeps_its_placeholders_and_says_so(tmp_path):
    root = bridge(tmp_path, profile=None)
    (root / "workflow" / "briefings" / "morning.yaml").write_text(
        (ROOT / "workflow" / "briefings" / "_template.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    rows = checks(root)
    assert "placeholder-morning-github-mine" in ids(rows)
    row = next(r for r in rows if r["id"] == "placeholder-morning-github-mine")
    assert "your-org" in row["detail"] and row["tone"] == "warn"
    # once the owner is a real one the section finds its rows, and the finding goes
    text = (root / "workflow" / "briefings" / "morning.yaml").read_text(encoding="utf-8")
    (root / "workflow" / "briefings" / "morning.yaml").write_text(text.replace("your-org", "example-org"), encoding="utf-8")
    assert not [r for r in checks(root) if r["id"].startswith("placeholder-morning-github")]


def test_github_on_without_gh_or_without_a_login_is_red_and_gh_is_asked_only_when_github_is_on(tmp_path):
    root = bridge(tmp_path, {**GOOD, "integrations": {"github": {"enabled": True}}})
    rows = checks(root, Probes(gh="missing"))
    assert ids(rows) == ["gh-missing"] and rows[0]["tone"] == "bad"
    rows = checks(root, Probes(gh="signed_out"))
    assert ids(rows) == ["gh-signed-out"] and rows[0]["tone"] == "bad" and "gh auth login" in rows[0]["detail"]
    assert checks(root, Probes(gh=None)) == []                     # unknown (it timed out): no claim
    off = Probes(gh="missing")
    assert checks(bridge(tmp_path / "off"), off) == [] and "gh" not in off.calls


def test_cockpit_keys_it_does_not_use_are_findings(tmp_path):
    root = bridge(tmp_path, {**GOOD, "cockpit": {"enabled": True, "tuor": False}})
    rows = checks(root)
    assert len(rows) == 1 and rows[0]["id"].startswith("config-") and "tuor" in rows[0]["detail"]
    assert ids(checks(root)) == ids(rows)                         # a stable id: the same finding keys the same item


def test_checks_speak_the_bridges_language(tmp_path):
    root = bridge(tmp_path, {**GOOD, "work": {"enabled": False}, "language": {"conversation": "de"}})
    assert checks(root)[0]["title"] == bv.LABELS_DE["setup_work_off"]


# ---------------------------------------------------------------- available and on

def available(root, **kw):
    return bs.check_part(root, "available", probes=Probes(), today=kw.get("today", TODAY))


def test_available_lists_what_is_off_with_how_to_switch_it_on_and_the_two_steps(tmp_path):
    rows = {r["id"]: r for r in available(bridge(tmp_path))}
    gh = rows["github-projects"]
    assert "/bridge-onboard --add github-projects" in gh["detail"]
    assert [a["id"] for a in gh["actions"]] == ["later", "silence"]
    assert "cockpit" not in rows                                   # on: not offered
    assert "task-management" not in rows                           # never offered: the check names it
    assert "jev" not in rows and "cockpit-relay" not in rows       # their offer conditions do not hold here


def test_offer_conditions_follow_the_catalogue(tmp_path):
    cfg = {**GOOD, "integrations": {"typesafe": {"key_ref": "keychain://jev/key"}}}
    root = bridge(tmp_path, cfg)
    (root / "mods" / "cockpit-relay").mkdir(parents=True)
    rows = ids(available(root))
    assert "jev" in rows and "cockpit-relay" in rows
    assert "bridge-deck" not in rows


def test_a_feature_with_its_files_counts_as_on(tmp_path):
    root = bridge(tmp_path)
    (root / "infra" / "remotes").mkdir(parents=True)
    (root / "infra" / "remotes" / "_template.yaml").write_text("x: 1\n", encoding="utf-8")
    assert "remotes" in ids(available(root))                     # a `_` file is no machine
    (root / "infra" / "remotes" / "box.yaml").write_text("x: 1\n", encoding="utf-8")
    assert "remotes" not in ids(available(root))
    assert "remotes" in ids(bs.check_part(root, "on", probes=Probes(), today=TODAY))


def state(root) -> dict:
    return yaml.safe_load((root / "work" / "onboarding-state.yaml").read_text(encoding="utf-8"))


def write_state(root, suggestions: dict) -> None:
    (root / "work").mkdir(exist_ok=True)
    (root / "work" / "onboarding-state.yaml").write_text(yaml.safe_dump({"suggestions": suggestions}), encoding="utf-8")


def test_deferred_shows_dim_with_its_date_until_it_is_due_and_silenced_or_declined_never(tmp_path):
    root = bridge(tmp_path)
    write_state(root, {"github_projects": {"status": "deferred", "remind_after": "2026-11-20"},
                       "remotes": {"status": "silenced"}, "personas": {"status": "declined", "decline_count": 1},
                       "mandants": {"status": "deferred", "remind_after": "2026-10-01"}})
    rows = {r["id"]: r for r in available(root)}
    assert rows["github-projects"]["tone"] == "dim" and "2026-11-20" in rows["github-projects"]["detail"]
    assert [a["id"] for a in rows["github-projects"]["actions"]] == ["silence"]
    assert "remotes" not in rows and "personas" not in rows
    assert rows["mandants"].get("tone") != "dim"                     # its date passed: offered as before


def test_on_lists_what_is_on_as_information(tmp_path):
    rows = bs.check_part(bridge(tmp_path), "on", probes=Probes(), today=TODAY)
    assert {"cockpit", "task-management"} <= set(ids(rows))
    assert all(r["tone"] == "dim" and not r.get("actions") for r in rows)


# ---------------------------------------------------------------- act: the one write

def test_later_defers_for_30_days_and_its_undo_restores_what_was_there(tmp_path):
    root = bridge(tmp_path)
    write_state(root, {"github_projects": {"status": "not_evaluated"}})
    code, out = bs.act(root, "github-projects", "later", today=TODAY)
    assert code == 0 and out["did"] == "later"
    entry = state(root)["suggestions"]["github_projects"]
    assert entry["status"] == "deferred" and str(entry["remind_after"]) == "2026-11-27" and entry["decided_at"]
    assert re.fullmatch(r"restore:[A-Za-z0-9._~-]{1,120}", out["undo"])
    code, back = bs.act(root, "github-projects", out["undo"], today=TODAY)
    assert code == 0, back
    assert state(root)["suggestions"]["github_projects"] == {"status": "not_evaluated"}


def test_not_for_me_silences_and_an_undo_without_an_earlier_entry_removes_it(tmp_path):
    root = bridge(tmp_path)
    code, out = bs.act(root, "remotes", "silence", today=TODAY)
    assert code == 0 and state(root)["suggestions"]["remotes"]["status"] == "silenced"
    assert "remotes" not in ids(available(root))
    assert bs.act(root, "remotes", out["undo"], today=TODAY)[0] == 0
    assert "remotes" not in (state(root).get("suggestions") or {})
    assert "remotes" in ids(available(root))


def test_the_command_checks_its_undo_token_itself(tmp_path):
    root = bridge(tmp_path)
    code, out = bs.act(root, "remotes", "later", today=TODAY)
    # someone decided anew meanwhile: the undo would overwrite that, so it is refused
    write_state(root, {"remotes": {"status": "accepted"}})
    assert bs.act(root, "remotes", out["undo"], today=TODAY)[0] == 2
    assert state(root)["suggestions"]["remotes"] == {"status": "accepted"}
    for bad in ("restore:nope.none._", "restore:remotes.bogus._", "restore:remotes.none.2026-13-40",
                "restore:personas.none._", "restore:remotes", "restore:../x"):
        assert bs.act(root, "remotes", bad, today=TODAY)[0] == 2, bad


def test_act_refuses_what_it_does_not_know(tmp_path):
    root = bridge(tmp_path)
    assert bs.act(root, "no-such-feature", "later", today=TODAY)[0] == 2
    assert bs.act(root, "remotes", "enable", today=TODAY)[0] == 2
    assert not (root / "work" / "onboarding-state.yaml").exists()


def test_act_keeps_the_other_entries_and_keys_of_the_state_file(tmp_path):
    root = bridge(tmp_path)
    (root / "work").mkdir()
    (root / "work" / "onboarding-state.yaml").write_text(yaml.safe_dump({
        "scanned_at": "2026-05-16", "suggestions": {"finance": {"status": "accepted"},
                                                    "remotes": {"status": "declined", "decline_count": 2}}}),
        encoding="utf-8")
    bs.act(root, "remotes", "silence", today=TODAY)
    data = state(root)
    assert data["scanned_at"] == "2026-05-16" and data["suggestions"]["finance"] == {"status": "accepted"}
    assert data["suggestions"]["remotes"]["decline_count"] == 2 and data["suggestions"]["remotes"]["status"] == "silenced"


def test_the_cli_prints_the_list_a_command_section_reads(tmp_path, capsys):
    root = bridge(tmp_path, {**GOOD, "work": {"enabled": False}})
    assert bs.main(["--root", str(root), "check", "--part", "available", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list) and all({"id", "title", "detail"} <= set(r) for r in rows)


# ---------------------------------------------------------------- briefing.py collect --setup

SETUP_IDS = ["setup-checks", "setup-available", "setup-on"]


def collected(root, *extra, capsys) -> dict:
    assert bf.main(["--root", str(root), "collect", "mine", "--json", "--no-save", "--skip", "tracker", *extra]) == 0
    return json.loads(capsys.readouterr().out)


def test_collect_with_setup_appends_three_command_sections_and_without_it_none(tmp_path, capsys):
    root = bridge(tmp_path, {**GOOD, "work": {"enabled": False}})
    plain = collected(root, capsys=capsys)
    assert not {s["id"] for s in plain["sections"]} & set(SETUP_IDS)
    data = collected(root, "--setup", capsys=capsys)
    sections = {s["id"]: s for s in data["sections"]}
    assert all(sections[sid]["kind"] == "command" and sections[sid]["status"] == "ok" for sid in SETUP_IDS)
    assert "work-off" in ids(sections["setup-checks"]["items"])
    # the briefing's own rows never carry them
    rows = [it for b in (data.get("view") or {}).get("buckets", []) for it in b["items"]]
    assert not [r for r in rows if str(r.get("section", "")).startswith("setup-")]


def test_the_setup_page_stands_on_its_own_and_never_on_the_rest_page(tmp_path, capsys):
    root = bridge(tmp_path, {**GOOD, "work": {"enabled": False}})
    pages = {p["id"]: p for p in collected(root, "--setup", capsys=capsys)["pages"]}
    setup = pages["setup"]
    assert setup["title"] == "Setup"
    assert [s["id"] for s in setup["sections"]] == SETUP_IDS
    by = {s["id"]: s for s in setup["sections"]}
    assert by["setup-checks"]["items"][0]["actionable"] is True and by["setup-checks"]["weight"] >= 1
    assert all(it["actionable"] is True for it in by["setup-available"]["items"])
    assert by["setup-available"]["weight"] == 0 and by["setup-on"]["weight"] == 0
    assert all(it["actionable"] is False for it in by["setup-on"]["items"])
    assert all(sid not in [s["id"] for s in p["sections"]] for p in pages.values() if p["id"] != "setup"
               for sid in SETUP_IDS)


def test_the_setup_page_title_follows_the_language():
    assert bv.LABELS["page_setup"] == "Setup" and bv.LABELS_DE["page_setup"] == "Einrichtung"


def test_the_section_titles_speak_the_language_and_a_profile_may_rename_them(tmp_path):
    root = bridge(tmp_path)
    de = bf.setup_sections(root, {"language": {"conversation": "de"}})
    assert [s["title"] for s in de] == [bv.LABELS_DE[f"section_{x.replace('-', '_')}"] for x in SETUP_IDS]
    own = bf.setup_sections(root, {}, {"labels": {"section_setup_on": "Active"}})
    assert own[2]["title"] == "Active" and all(s["bucket"] == "none" for s in own)


def test_a_profile_that_places_the_setup_sections_itself_keeps_them_there():
    result = {"collected_at": "2026-10-28T09:00", "sections": [
        {"id": sid, "kind": "command", "title": sid, "status": "ok", "items": [], "total": 0} for sid in SETUP_IDS]}
    profile = {"id": "p", "view": {"pages": [{"id": "ops", "title": "Ops", "sections": ["setup-checks"]}]}}
    pages = {p["id"]: p for p in bv.pages(result, profile)}
    assert [s["id"] for s in pages["ops"]["sections"]] == ["setup-checks"]
    assert [s["id"] for s in pages["setup"]["sections"]] == ["setup-available", "setup-on"]
    assert "more" not in pages


def test_validate_reserves_the_setup_ids_but_a_page_may_name_them(tmp_path):
    root = bridge(tmp_path)
    path = root / "workflow" / "briefings" / "mine.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["view"] = {"pages": [{"id": "ops", "sections": ["setup-checks", "gh"]}]}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert bf.validate(root) == []
    data["sections"].append({"kind": "command", "id": "setup-on", "argv": ["true"]})
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert any("setup-on" in p and "reserved" in p for p in bf.validate(root))


def test_a_step_of_the_setup_page_runs_through_briefing_act(tmp_path, capsys):
    root = bridge(tmp_path)
    assert bf.main(["--root", str(root), "act", "mine", "setup-available", "remotes", "later"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["did"] == "later" and out["undo"].startswith("restore:")
    assert state(root)["suggestions"]["remotes"]["status"] == "deferred"
    # the undo goes to the command, which checks it
    assert bf.main(["--root", str(root), "act", "mine", "setup-available", "remotes", out["undo"]]) == 0
    capsys.readouterr()
    # a step the row does not offer is refused before anything runs
    assert bf.main(["--root", str(root), "act", "mine", "setup-on", "cockpit", "later"]) == 2


# ---------------------------------------------------------------- the cockpit passes --setup

def test_the_cockpit_collects_the_setup_page_unless_switched_off(tmp_path):
    root = tmp_path / "c"
    root.mkdir()
    assert load_web_config(root, {"cockpit": {"enabled": True}}).setup is True
    off = load_web_config(root, {"cockpit": {"enabled": True, "setup": False}})
    assert off.setup is False and off.config_warnings == ()
    bad = load_web_config(root, {"cockpit": {"enabled": True, "setup": "yes"}})
    assert bad.setup is True and any("setup" in w for w in bad.config_warnings)


def test_collect_argv_carries_setup_on_every_pass_unless_switched_off(tmp_path):
    w = World(tmp_path / "on", config="cockpit:\n  enabled: true\n  language: en\n", serve=False, prepare=False)
    try:
        for kind in ("quick", "full", "delta"):
            assert "--setup" in w.app.collector.collect_argv(kind, False), kind
    finally:
        w.close()
    w = World(tmp_path / "off", config="cockpit:\n  enabled: true\n  language: en\n  setup: false\n", serve=False,
              prepare=False)
    try:
        assert "--setup" not in w.app.collector.collect_argv("full", False)
    finally:
        w.close()
