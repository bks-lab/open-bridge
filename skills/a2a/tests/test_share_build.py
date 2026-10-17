"""share_build: one folder per peer from an access file, and grants on request.

The folder is the whole boundary of a peer agent (see agents/_runtime/access.py), so
these tests pin what lands in it: each level carries exactly its fields, a topic at
``none`` is absent everywhere, secrets never appear whatever the level, and a grant
opens exactly the topic the owner said yes to.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "share_build.py"
sys.path.insert(0, str(SCRIPT.parent))

import share_build  # noqa: E402

STATUS = """# yaml-language-server: $schema=../../templates/_schema.status.yaml
---
slug: {slug}
status: doing
context: {context}
headline: "{headline}"
last_updated: 2026-10-17
{extra}---

# {slug}

Body text of {slug}.

## Next step

Call the customer on Monday.

<!-- share: private -->
## Money

Daily rate 1234 EUR.

## History

- 2026-10-01: started
"""

MACHINE = {
    "name": "bigpc",
    "type": "windows",
    "hardware": {"cpu": "Ryzen 9", "ram": "128GB", "gpu": "RTX 4090"},
    "ssh": {"user": "someone", "host": "bigpc", "port": 22},
    "network": {"tailscale_ip": "100.91.1.2", "lan_ip": "192.168.1.33", "mac": "E8:9C:25:C3:90:30"},
    "capabilities": ["ssh", "llm-inference", "password-cracking"],
    "services": [{"slug": "ollama", "note": "binds 0.0.0.0, allowed from 100.64.0.0/10, models on D:\\ollama\\models",
                  "token_ref": "keychain://x"}],
    "credential_ref": "keychain://y",
}


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for slug, context, extra in (
        ("acme-thing", "acme", ""),
        ("blocked-thing", "blocked", ""),
        ("hidden-thing", "acme", "share:\n  alice: none\n"),
        ("open-thing", "reinvent", ""),
    ):
        d = root / "work" / "tasks" / slug
        (d / "deliverables").mkdir(parents=True)
        (d / "STATUS.md").write_text(STATUS.format(slug=slug, context=context, headline=f"Headline {slug}",
                                                   extra=extra), "utf-8")
        (d / "deliverables" / "plan.md").write_text(f"plan of {slug}", "utf-8")
    m = root / "infra" / "remotes"
    m.mkdir(parents=True)
    (m / "bigpc.yaml").write_text(yaml.safe_dump(MACHINE), "utf-8")
    return root


ACCESS = {
    "schema_version": 1,
    "sources": ["work/tasks/*/STATUS.md"],
    "peers": {
        "alice": {
            "default": "none",
            "rules": [
                {"match": {"context": ["blocked"]}, "level": "none"},
                {"match": {"context": ["acme"]}, "level": "details"},
                {"match": {"path": ["infra/remotes/bigpc.yaml"]}, "level": "details",
                 "only": ["name", "hardware", "capabilities", "services"]},
                {"match": {"context": ["reinvent"]}, "level": "on_request", "grant_level": "files"},
            ],
        },
        "bob": {"default": "status"},
    },
}


@pytest.fixture
def setup(tmp_path):
    root = _repo(tmp_path)
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(ACCESS), "utf-8")
    out = tmp_path / "share"
    share_build.build(cfg, root=root, out=out)
    return root, cfg, out


def _all_text(folder: Path) -> str:
    return "\n".join(p.read_text("utf-8") for p in folder.rglob("*") if p.is_file())


def test_each_peer_gets_its_own_folder_with_an_index(setup):
    _, _, out = setup
    assert (out / "peers" / "alice" / "index.md").is_file()
    assert (out / "peers" / "bob" / "index.md").is_file()


def test_details_carry_the_body_but_never_a_private_section(setup):
    _, _, out = setup
    text = (out / "peers" / "alice" / "topics" / "acme-thing.md").read_text("utf-8")
    assert "Body text of acme-thing" in text
    assert "Call the customer on Monday" in text
    assert "plan.md" not in text                  # attachments are listed only at level files
    assert "1234" not in text and "Money" not in text
    assert not (out / "peers" / "alice" / "topics" / "acme-thing").exists()


def test_status_carries_headline_state_and_next_step_only(setup):
    _, _, out = setup
    text = (out / "peers" / "bob" / "topics" / "acme-thing.md").read_text("utf-8")
    assert "Headline acme-thing" in text and "doing" in text
    assert "Call the customer on Monday" in text
    assert "Body text" not in text and "plan.md" not in text


def test_none_is_absent_everywhere(setup):
    _, _, out = setup
    alice = _all_text(out / "peers" / "alice")
    assert "blocked-thing" not in alice
    assert "hidden-thing" not in alice           # share: {alice: none} in the STATUS.md
    assert "hidden-thing" in _all_text(out / "peers" / "bob")


def test_on_request_is_listed_by_name_only(setup):
    _, _, out = setup
    index = (out / "peers" / "alice" / "index.md").read_text("utf-8")
    assert "open-thing" in index and "on request" in index.lower()
    assert not (out / "peers" / "alice" / "topics" / "open-thing.md").exists()
    assert "Body text of open-thing" not in _all_text(out / "peers" / "alice")


def test_a_machine_file_never_leaks_secrets_or_addresses(setup):
    _, _, out = setup
    text = (out / "peers" / "alice" / "topics" / "bigpc.md").read_text("utf-8")
    assert "Ryzen 9" in text and "RTX 4090" in text and "llm-inference" in text
    for secret in ("100.91.1.2", "192.168.1.33", "E8:9C:25", "keychain://", "someone",
                   "100.64.0.0", "D:\\ollama", "tailscale_ip", "ssh:"):
        assert secret not in text, secret


def test_only_limits_a_file_to_the_named_keys(setup):
    _, _, out = setup
    text = (out / "peers" / "alice" / "topics" / "bigpc.md").read_text("utf-8")
    assert "windows" not in text                 # `type` is not in only:


def test_only_reaches_into_nested_keys_and_exclude_drops_values(tmp_path):
    root = _repo(tmp_path)
    access = {"schema_version": 1, "peers": {"alice": {"default": "none", "rules": [
        {"match": {"path": ["infra/remotes/bigpc.yaml"]}, "level": "details",
         "only": ["name", "hardware.gpu", "capabilities", "services.slug"],
         "exclude": ["password-cracking"]}]}}}
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(access), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    text = (tmp_path / "share" / "peers" / "alice" / "topics" / "bigpc.md").read_text("utf-8")
    assert "RTX 4090" in text and "Ryzen" not in text
    assert "ollama" in text and "binds" not in text
    assert "llm-inference" in text and "password-cracking" not in text


def test_home_paths_are_masked():
    assert "~/" not in share_build.mask("see ~/PARA-Documents/x/contract.pdf for it")


def test_bob_sees_no_machine_without_a_rule(setup):
    _, _, out = setup
    assert "Ryzen" not in _all_text(out / "peers" / "bob")


def test_a_rebuild_removes_what_is_no_longer_allowed(setup):
    root, cfg, out = setup
    access = yaml.safe_load(cfg.read_text("utf-8"))
    access["peers"]["alice"]["rules"][1]["level"] = "none"
    cfg.write_text(yaml.safe_dump(access), "utf-8")
    share_build.build(cfg, root=root, out=out)
    assert not (out / "peers" / "alice" / "topics" / "acme-thing.md").exists()


def _grant(cfg, root, out, payload):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "grant", "--config", str(cfg), "--root", str(root), "--out", str(out)],
        input=json.dumps(payload), capture_output=True, text=True,
    )
    return proc


def test_a_once_grant_opens_the_topic_in_a_folder_of_its_own(setup):
    root, cfg, out = setup
    proc = _grant(cfg, root, out, {"action": "grant", "peer": "alice", "topic": "open-thing",
                                   "scope": "once", "task_id": "t-1"})
    assert proc.returncode == 0, proc.stderr
    folder = Path(json.loads(proc.stdout)["grounding_dir"])
    assert folder.parent == (out / "grants" / "alice").resolve()
    text = (folder / "topics" / "open-thing.md").read_text("utf-8")
    assert "Body text of open-thing" in text
    assert (folder / "topics" / "open-thing" / "plan.md").is_file()     # grant_level: files
    assert (folder / "topics" / "acme-thing.md").is_file()               # the rest stays
    assert not (out / "peers" / "alice" / "topics" / "open-thing.md").exists()
    _grant(cfg, root, out, {"action": "release", "peer": "alice", "topic": "open-thing",
                            "scope": "once", "task_id": "t-1"})
    assert not folder.exists()


def test_an_always_grant_is_recorded_and_lands_in_the_peer_folder(setup):
    root, cfg, out = setup
    proc = _grant(cfg, root, out, {"action": "grant", "peer": "alice", "topic": "open-thing",
                                   "scope": "always", "task_id": "t-2"})
    assert proc.returncode == 0, proc.stderr
    assert Path(json.loads(proc.stdout)["grounding_dir"]).parent == (out / "grants" / "alice").resolve()
    grants = yaml.safe_load((cfg.parent / "access.grants.yaml").read_text("utf-8"))
    entry = grants["grants"][0]
    assert entry["peer"] == "alice" and entry["topic"] == "open-thing" and entry["level"] == "files"
    assert entry["since"]
    assert (out / "peers" / "alice" / "topics" / "open-thing.md").is_file()
    # survives a rebuild from scratch
    share_build.build(cfg, root=root, out=out)
    assert (out / "peers" / "alice" / "topics" / "open-thing.md").is_file()


@pytest.mark.parametrize("topic", ["blocked-thing", "hidden-thing", "acme-thing", "nope", "../x"])
def test_only_an_on_request_topic_can_be_granted(setup, topic):
    root, cfg, out = setup
    proc = _grant(cfg, root, out, {"action": "grant", "peer": "alice", "topic": topic,
                                   "scope": "once", "task_id": "t-3"})
    assert proc.returncode != 0
    assert not (out / "grants" / "t-3").exists()


def test_release_refuses_a_task_id_that_is_a_path(setup):
    root, cfg, out = setup
    (out / "keep").mkdir()
    proc = _grant(cfg, root, out, {"action": "release", "peer": "alice", "topic": "open-thing",
                                   "scope": "once", "task_id": "../keep"})
    assert proc.returncode != 0
    assert (out / "keep").exists()


def test_an_unknown_level_stops_the_build(tmp_path):
    root = _repo(tmp_path)
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "peers": {"alice": {"default": "everything"}}}), "utf-8")
    with pytest.raises(ValueError, match="everything"):
        share_build.build(cfg, root=root, out=tmp_path / "share")


# --- review round 17.10. ------------------------------------------------------------

def _one(tmp_path, body, *, level="details", meta_extra="", peers=None):
    root = tmp_path / "repo"
    d = root / "work" / "tasks" / "t1"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text(
        f"---\nslug: t1\nstatus: doing\ncontext: c\nheadline: \"{meta_extra or 'H'}\"\n---\n\n{body}\n", "utf-8")
    access = {"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"],
              "peers": peers or {"alice": {"default": "none",
                                           "rules": [{"match": {"context": ["c"]}, "level": level}]}}}
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(access), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    p = tmp_path / "share" / "peers" / "alice" / "topics" / "t1.md"
    return p.read_text("utf-8") if p.exists() else "", root, cfg


@pytest.mark.parametrize("level", ["status", "details"])
def test_status_topics_are_masked_too(tmp_path, level):
    home = "/" + "Users" + "/someone"             # spelled apart for the repo's own leak scan
    body = ("## Next step\n\nssh deploy@100.91.1.2, see " + home + "/x and "
            "keychain://tok, host db.tailabc123.ts.net, mail a.b@example.org\n")
    text, _, _ = _one(tmp_path, body, level=level, meta_extra="at 10.0.0.5")
    for secret in ("100.91.1.2", home, "keychain://", "tailabc123.ts.net", "a.b@example.org", "10.0.0.5"):
        assert secret not in text, (level, secret)


@pytest.mark.parametrize("body", [
    "## Open\n\nfine\n\n## Money\n<!-- share: private -->\nDaily rate 1234\n\n## After\n\nkept",
    "## Open\n\nfine\n\n## Money <!-- share: private -->\n\nDaily rate 1234\n\n## After\n\nkept",
    "## Open\n\nfine\n\n<!-- share: private -->\n## Money\n\nDaily rate 1234\n\n## After\n\nkept",
    "## Open\n\nfine\n\n<!-- share: private -->\n\n## Money\n\nDaily rate 1234\n```\n# not a heading\nrate 1234 again\n```\n\n## After\n\nkept",
    "## Open\n\nfine\n\n## Money\n\nintro\n\n<!-- share: private -->\nDaily rate 1234\n\n## After\n\nkept",
    "## Open\n\nfine\n\n<!-- share: private -->\n## Money\n\n### Sub\n\nrate 1234\n\n## After\n\nkept",
])
def test_private_marker_drops_exactly_its_section(tmp_path, body):
    text, _, _ = _one(tmp_path, body)
    assert "1234" not in text
    assert "fine" in text and "kept" in text


def test_a_path_rule_of_one_peer_is_no_topic_for_another(tmp_path):
    root = _repo(tmp_path)
    access = {"schema_version": 1, "peers": {
        "alice": {"default": "none", "rules": [
            {"match": {"path": ["infra/remotes/bigpc.yaml"]}, "level": "details", "only": ["name"]}]},
        "bob": {"default": "details"}}}
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(access), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    assert "bigpc" not in _all_text(tmp_path / "share" / "peers" / "bob")


def _grant_call(cfg, root, out, **payload):
    return share_build.grant(cfg, root=root, out=out,
                             request={"action": "grant", "task_id": "t-9", **payload})


def test_always_works_when_on_request_comes_from_default(tmp_path):
    _, root, cfg = _one(tmp_path, "## X\n\nbody text", peers={"alice": {"default": "on_request"}})
    out = tmp_path / "share"
    _grant_call(cfg, root, out, peer="alice", topic="t1", scope="always")
    assert (out / "peers" / "alice" / "topics" / "t1.md").is_file()


def test_always_works_when_on_request_comes_from_a_status_override(tmp_path):
    root = tmp_path / "repo"
    d = root / "work" / "tasks" / "t2"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\nslug: t2\ncontext: c\nshare:\n  alice: on_request\n---\n\nbody two\n", "utf-8")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"],
                                   "peers": {"alice": {"default": "none"}}}), "utf-8")
    out = tmp_path / "share"
    share_build.build(cfg, root=root, out=out)
    _grant_call(cfg, root, out, peer="alice", topic="t2", scope="always")
    assert "body two" in (out / "peers" / "alice" / "topics" / "t2.md").read_text("utf-8")


def test_a_repeated_always_grant_is_recorded_once(setup):
    root, cfg, out = setup
    for task in ("t-a", "t-b"):
        share_build.grant(cfg, root=root, out=out, request={
            "action": "grant", "peer": "alice", "topic": "open-thing", "scope": "always", "task_id": task})
    grants = yaml.safe_load((cfg.parent / "access.grants.yaml").read_text("utf-8"))["grants"]
    assert len(grants) == 1


def test_grant_folders_are_per_peer_and_always_also_gets_its_own(setup):
    root, cfg, out = setup
    once = share_build.grant(cfg, root=root, out=out, request={
        "action": "grant", "peer": "alice", "topic": "open-thing", "scope": "once", "task_id": "t-5"})
    assert Path(once["grounding_dir"]).parent == (out / "grants" / "alice").resolve()
    always = share_build.grant(cfg, root=root, out=out, request={
        "action": "grant", "peer": "alice", "topic": "open-thing", "scope": "always", "task_id": "t-6"})
    assert Path(always["grounding_dir"]).parent == (out / "grants" / "alice").resolve()
    share_build.grant(cfg, root=root, out=out, request={
        "action": "release", "peer": "alice", "topic": "open-thing", "scope": "once", "task_id": "t-5"})
    assert not Path(once["grounding_dir"]).exists() and Path(always["grounding_dir"]).exists()


def test_build_sweeps_stale_grant_folders(setup):
    import os
    root, cfg, out = setup
    stale = out / "grants" / "alice" / "old-task"
    stale.mkdir(parents=True)
    os.utime(stale, (0, 0))
    share_build.build(cfg, root=root, out=out)
    assert not stale.exists()


@pytest.mark.parametrize("key", ["ssh-user", "apiKey", "macAddress", "ipAddress", "ipv4", "tenant_id",
                                 "subscription", "iban", "phone"])
def test_more_key_shapes_are_sensitive(key):
    assert share_build._clean_yaml({key: "x", "keep": "y"}) == {"keep": "y"}


@pytest.mark.parametrize("value", ["fd7a:115c:a1e0::1", "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
                                   "sk-ant-abcdefghijklmnop1234", "box.tailabc123.ts.net", "me@example.org"])
def test_more_value_shapes_are_masked(value):
    assert value not in share_build.mask(f"value {value} here")


@pytest.mark.parametrize("body", [
    "## Open\n\nfine\n\n## Money\n\nDaily rate 1234\n<!-- share: private -->\n\n## After\n\nmore 1234",
    "Preamble 1234\n<!-- share: private -->\n## Open\n\nrate 1234",
])
def test_a_marker_right_after_content_hides_both_sides(tmp_path, body):
    text, _, _ = _one(tmp_path, body)
    assert "1234" not in text


def test_ipv4_mapped_ipv6_is_masked_whole():
    out = share_build.mask("peer ::ffff:10.1.2.3 here")
    assert "10" not in out and "1.2.3" not in out


def test_build_sweeps_leftover_swap_folders(setup):
    root, cfg, out = setup
    (out / "peers" / ".old-alice-1").mkdir()
    (out / "peers" / ".build-xyz").mkdir()
    share_build.build(cfg, root=root, out=out)
    assert not (out / "peers" / ".old-alice-1").exists()
    assert not (out / "peers" / ".build-xyz").exists()


def test_the_next_step_heading_can_be_named(tmp_path):
    body = "## Up next\n\nCall on Monday.\n\n## Rest\n\nmore"
    peers = {"alice": {"default": "none", "rules": [{"match": {"context": ["c"]}, "level": "status"}]}}
    root = tmp_path / "repo"
    d = root / "work" / "tasks" / "t1"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text(f"---\nslug: t1\ncontext: c\n---\n\n{body}\n", "utf-8")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"],
                                   "next_step_headings": ["Up next"], "peers": peers},
                                  allow_unicode=True), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    text = (tmp_path / "share" / "peers" / "alice" / "topics" / "t1.md").read_text("utf-8")
    assert "Call on Monday" in text and "more" not in text


@pytest.mark.parametrize("text,secret", [
    ("IBAN DE89370400440532013000, done", "DE89370400440532013000"),
    ("IBAN DE89 3704 0044 0532 0130 00, done", "3704 0044"),
    ("account GB82WEST12345698765432", "GB82WEST12345698765432"),
    ("BIC COBADEFFXXX and more", "COBADEFFXXX"),
    ("BIC: DEUTDEFF, rest", "DEUTDEFF"),
])
def test_bank_details_are_masked(text, secret):
    assert secret not in share_build.mask(text)


def test_plain_uppercase_words_survive_the_bank_mask():
    text = "SHAREPOINT and BENELUX_OUT and PASSWORD stay readable"
    assert share_build.mask(text) == text


# --- third round: fuzzing, content audit, answer quality (17.10.) -------------------

import time as _time


def test_a_symlinked_attachment_is_never_copied(tmp_path):
    root = _repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("TOP SECRET", "utf-8")
    (root / "work" / "tasks" / "open-thing" / "deliverables" / "link.txt").symlink_to(outside)
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"],
                                   "peers": {"alice": {"default": "files"}}}), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    assert "TOP SECRET" not in _all_text(tmp_path / "share")


@pytest.mark.parametrize("text", ["a-" * 30000, "word-" * 12000, "x." * 30000, "a" * 60000 + "@"])
def test_mask_stays_fast_on_hostile_input(text):
    start = _time.monotonic()
    share_build.mask(text)
    assert _time.monotonic() - start < 2.0


def test_a_broken_frontmatter_hides_the_topic(tmp_path):
    root = tmp_path / "repo"
    d = root / "work" / "tasks" / "t1"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("﻿---\nslug: t1\nshare: {alice: none\n---\n\nsecret body\n", "utf-8")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"],
                                   "peers": {"alice": {"default": "details"}}}), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    assert "secret body" not in _all_text(tmp_path / "share")


def test_a_bom_does_not_break_the_frontmatter():
    meta, body = share_build._split_frontmatter("﻿---\nslug: x\n---\n\nbody\n")
    assert meta.get("slug") == "x" and body.strip() == "body"


@pytest.mark.parametrize("value", [
    "2001:1234:5678:9012:3456:7890:1234:5678",
    "+43 664 8593772", "+49 (0)231 39599333", "Tel. 0231 39599333", "Mobil: 0178 800 5725",
    "b2b4c1a0-1234-4bcd-9abc-0123456789ab",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop",
    "AKIAIOSFODNN7EXAMPLE", "AIzaSyA1234567890abcdefghijklmnopqrstu",
    "Bearer abcdefghijklmnopqrstuvwxyz012345",
    "password=hunter2secret", "Passwort: geheim123",
    "de89-3704-0044-0532-0130-00", "DE89.3704.0044.0532.0130.00",
    "/" + "Users/Max Muster/Documents/x.txt", "\\\\fileserver\\share\\dir",
    "/root/x", "/srv/data/x", "/mnt/disk/x", "/tmp/x.txt",
    "www.example.com/p?token=abc",
    "USt-IdNr. DE123456789", "Steuernummer 012/345/67890",
    "-----BEGIN PRIVATE KEY-----\nMIIEvQ\n-----END PRIVATE KEY-----",
])
def test_round_three_secret_shapes_are_masked(value):
    out = share_build.mask(f"x {value} y")
    labels = {"Mobil", "Bearer", "password", "Passwort", "Steuernummer", "BEGIN", "PRIVATE"}
    for part in [p for p in re.split(r"[\s/\\\\:.()=-]+", value) if len(p) >= 5 and p not in labels]:
        assert part not in out, (value, out)


@pytest.mark.parametrize("prose", [
    "Abschnitt 1.2.3.4.5 regelt das", "Version 2.14.3 vom 2026-10-17 um 10:30:45",
    "Termin 17.10.2026, KW 42, Ticket K2A-E123", "ISO 27001 und DIN 5008",
    "Rechnung STAT1001090 und Auftrag 4711", "siehe Abschnitt 3 bis 7",
])
def test_round_three_prose_survives(prose):
    assert share_build.mask(prose) == prose


def test_path_mask_keeps_the_rest_of_the_line():
    path = "/" + "Users/x/y.md"                 # spelled apart for the repo's own leak scan
    assert share_build.mask(f"Datei `{path}` ist da") == "Datei `[path]` ist da"


def test_markdown_links_keep_their_text():
    assert share_build.mask("siehe [PR #95](https://github.com/o/r/pull/95) dazu") == "siehe PR #95 dazu"
    assert share_build.mask("siehe [Plan](../../tasks/x/plan.md) dazu") == "siehe Plan dazu"


@pytest.mark.parametrize("key", ["authorization", "cookie", "passphrase", "pwd", "connectionString",
                                 "dsn", "sas", "sig", "salt", "cert", "webhook", "endpoint", "server",
                                 "fqdn", "domain", "ssn", "imei", "vin", "serial", "salary"])
def test_round_three_keys_are_sensitive(key):
    assert share_build._clean_yaml({key: "x", "keep": "y"}) == {"keep": "y"}


@pytest.mark.parametrize("marker", ["<!--  SHARE :  PRIVATE  -->", "<!-- note share: private -->"])
def test_marker_variants(tmp_path, marker):
    text, _, _ = _one(tmp_path, f"## Open\n\nfine\n\n{marker}\n## Money\n\nrate 1234\n\n## After\n\nkept")
    assert "1234" not in text and "fine" in text and "kept" in text


def test_mixed_fences_do_not_end_a_private_section(tmp_path):
    body = "## Open\n\nfine\n\n<!-- share: private -->\n## Money\n\n~~~\n```\n# fake\n~~~\nSECRET 1234\n\n## After\n\nkept"
    text, _, _ = _one(tmp_path, body)
    assert "1234" not in text and "kept" in text


@pytest.mark.parametrize("bad", ["a\n", "t-1\n"])
def test_ids_with_a_newline_are_refused(setup, bad):
    root, cfg, out = setup
    with pytest.raises(ValueError):
        share_build.grant(cfg, root=root, out=out, request={
            "action": "grant", "peer": "alice", "topic": "open-thing", "scope": "once", "task_id": bad})


def test_an_always_grant_works_before_any_build(tmp_path):
    root = _repo(tmp_path)
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(ACCESS), "utf-8")
    out = tmp_path / "share"
    share_build.grant(cfg, root=root, out=out, request={
        "action": "grant", "peer": "alice", "topic": "open-thing", "scope": "always", "task_id": "t1"})
    assert (out / "peers" / "alice" / "topics" / "open-thing.md").is_file()


def test_one_unreadable_topic_does_not_stop_the_build(tmp_path):
    root = _repo(tmp_path)
    (root / "work" / "tasks" / "bks-broken").mkdir()
    (root / "work" / "tasks" / "bks-broken" / "STATUS.md").write_bytes(b"---\nslug: x\n---\n\xff\xfe bad")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(ACCESS), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    assert (tmp_path / "share" / "peers" / "alice" / "topics" / "acme-thing.md").is_file()


def test_a_path_rule_cannot_leave_the_root(tmp_path):
    root = _repo(tmp_path)
    (tmp_path / "outside.yaml").write_text("name: outside\nsecret: 1\n", "utf-8")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "peers": {"alice": {"default": "none", "rules": [
        {"match": {"path": ["../outside.yaml"]}, "level": "details"}]}}}), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    assert "outside" not in _all_text(tmp_path / "share" / "peers" / "alice")


def test_redact_terms_drop_the_paragraph_or_list_item(tmp_path):
    body = ("## Stand\n\nBKS part stays.\n\nThe Globex mandate runs in parallel, rate 99.\n\n"
            "- item one stays\n- item about globex goes\n- item three stays\n")
    peers = {"alice": {"default": "none", "redact_terms": ["Globex"],
                       "rules": [{"match": {"context": ["c"]}, "level": "details"}]}}
    text, _, _ = _one(tmp_path, body, peers=peers)
    assert "BKS part stays" in text and "item one stays" in text and "item three stays" in text
    assert "Globex" not in text and "globex" not in text and "rate 99" not in text


def test_the_index_has_a_summary_a_date_and_groups(tmp_path):
    root = _repo(tmp_path)
    d = root / "work" / "tasks" / "no-headline"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\nslug: no-headline\ncontext: acme\nlast_updated: 2026-10-15\n---\n\n"
                                 "# Title\n\nFirst real sentence of the topic. Second one.\n", "utf-8")
    access = {"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"], "peers": {"alice": {
        "default": "none", "rules": [{"match": {"context": ["acme"]}, "level": "details", "group": "Acme work"}]}}}
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(access), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    index = (tmp_path / "share" / "peers" / "alice" / "index.md").read_text("utf-8")
    assert "## Acme work" in index
    line = next(l for l in index.splitlines() if "no-headline" in l)
    assert "First real sentence of the topic." in line and "2026-10-15" in line
    assert "(details)" not in line
    topic = (tmp_path / "share" / "peers" / "alice" / "topics" / "no-headline.md").read_text("utf-8")
    assert "Level:" not in topic


def test_status_falls_back_to_the_first_open_item(tmp_path):
    text, _, _ = _one(tmp_path, "## Work\n\n- [x] done thing\n- [ ] call the customer\n- [ ] later",
                      level="status")
    assert "call the customer" in text and "done thing" not in text


def test_huge_details_are_cut_with_a_note(tmp_path):
    body = "## Current\n\nnow\n\n" + "\n\n".join(f"## Old {i}\n\n" + "x" * 2000 for i in range(40))
    text, _, _ = _one(tmp_path, body)
    assert len(text.encode()) < 30_000
    assert "now" in text and "shortened" in text.lower()


def test_emails_of_named_domains_stay_readable(tmp_path):
    peers = {"alice": {"default": "none", "rules": [{"match": {"context": ["c"]}, "level": "details"}]}}
    root = tmp_path / "repo"
    d = root / "work" / "tasks" / "t1"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\nslug: t1\ncontext: c\n---\n\nmail ops@acme.example and x@other.example\n", "utf-8")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"],
                                   "keep_email_domains": ["acme.example"], "peers": peers}), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    text = (tmp_path / "share" / "peers" / "alice" / "topics" / "t1.md").read_text("utf-8")
    assert "ops@acme.example" in text and "x@other.example" not in text


def test_rule_fields_and_summary_template(tmp_path):
    root = tmp_path / "repo"
    d = root / "work" / "apps" / "a1"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text(
        "---\nfirma: Initech\nrolle: Tester\nstatus: offen\nkontakt:\n  name: Bob\n  telefon: +49 211 530653 754\n"
        "konditionen:\n  rate: 100\n---\n\n# Initech\n\nVehikel: solo (a@b.example). Body.\n", "utf-8")
    access = {"schema_version": 1, "sources": ["work/apps/*/STATUS.md"], "peers": {"alice": {
        "default": "none", "rules": [{"match": {"path": ["work/apps/*/STATUS.md"]}, "level": "details",
                                      "fields": ["firma", "rolle", "konditionen.rate", "kontakt.telefon"],
                                      "summary": "{firma}: {rolle}, Status {status}, Satz {konditionen[rate]} {missing}"}]}}}
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(access, allow_unicode=True), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    index = (tmp_path / "share" / "peers" / "alice" / "index.md").read_text("utf-8")
    assert "Initech: Tester, Status offen, Satz 100" in index
    topic = (tmp_path / "share" / "peers" / "alice" / "topics" / "a1.md").read_text("utf-8")
    assert "- firma: Initech" in topic and "- konditionen.rate: 100" in topic
    assert "530653" not in topic                  # a sensitive key stays out even when named


def test_label_lines_are_no_summary(tmp_path):
    text = share_build._first_sentence("# T\n\nVehikel: solo (x).\nEinsatzort Frankfurt, mostly remote work.\n")
    assert text.startswith("Einsatzort Frankfurt")


# --- final round (17.10.) -------------------------------------------------------------

def test_a_level_typo_in_one_topic_hides_only_that_topic(tmp_path):
    root = _repo(tmp_path)
    d = root / "work" / "tasks" / "typo"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\nslug: typo\ncontext: acme\nshare:\n  alice: detail\n---\n\nx\n", "utf-8")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump(ACCESS), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    topics = tmp_path / "share" / "peers" / "alice" / "topics"
    assert (topics / "acme-thing.md").is_file() and not (topics / "typo.md").exists()


def test_an_unclosed_frontmatter_hides_the_topic():
    meta, _ = share_build._split_frontmatter("---\nslug: x\nrate: 99\n\nbody without a closing fence\n")
    assert meta.get("__broken__")


@pytest.mark.parametrize("value,secret", [
    ("client_secret: abc123def", "abc123def"), ("access_token=xyz987abc", "xyz987abc"),
    ('"password": "hunter22"', "hunter22"), ("Passwort:      geheim99", "geheim99"),
    ("| Passwort | geheim77 |", "geheim77"), ("api_key: k-123456", "k-123456"), ("API-Key: zz998877", "zz998877"),
    ("Steuer-Nr. 012/345/67890", "345/67890"), ("Steuernr. 01234567890", "01234567890"),
    ("Steuer-Identifikationsnummer 12 345 678 901", "345 678"), ("USt-ID-Nr. DE123456789", "123456789"),
    ("Telefonnummer: 069 123456", "123456"), ("Tel.-Nr. 0171 1234567", "1234567"), ("Handynr. 0151 2223334", "2223334"),
    ("ruf an unter 0171 1234567", "1234567"), ("IBAN AT…7000 vom Kunden", "7000"), ("Konto `12264476` bei", "12264476"),
])
def test_final_secret_shapes(value, secret):
    assert secret not in share_build.mask(value), share_build.mask(value)


@pytest.mark.parametrize("prose", [
    "AGESA 1.3.0.0a vom Hersteller", "commit ab12cd34ef56 auf main", "release rc12.2026.1017",
    "python x[::2] und f :: Int", "am 2026-10-17 um 14:30 Uhr", "die Zahl 0815 allein", "KW 42 von 2026",
])
def test_final_prose_survives(prose):
    assert share_build.mask(prose) == prose


def test_a_keep_domain_needs_the_real_domain():
    out = share_build.mask("a@bks.example.evil.org und b@bks.example", ("bks.example",))
    assert "a@bks.example.evil.org" not in out and "b@bks.example" in out


def test_a_multiline_private_comment_hides_its_section(tmp_path):
    body = "## Open\n\nfine\n\n<!--\nshare: private\n-->\n## Money\n\nrate 1234\n\n## After\n\nkept"
    text, _, _ = _one(tmp_path, body)
    assert "1234" not in text and "fine" in text and "kept" in text


def test_redact_drops_a_hit_heading_with_its_section_and_empty_headings(tmp_path):
    body = ("## Globex-Mandat\n\nTagessatz 999.\n\n### Detail\n\nmore 999\n\n## Mapping\n\n"
            "| Req | Fit |\n|---|---|\n| Python | ja |\n| Globex | ja |\n\n## Gaps\n\n- Globex only item\n\n## After\n\nkept")
    peers = {"alice": {"default": "none", "redact_terms": ["Globex"],
                       "rules": [{"match": {"context": ["c"]}, "level": "details"}]}}
    text, _, _ = _one(tmp_path, body, peers=peers)
    assert "999" not in text and "Globex" not in text
    assert "| Python | ja |" in text and "kept" in text
    assert "## Gaps" not in text                  # nothing left under it


def test_redact_in_yaml_drops_only_the_item(tmp_path):
    cleaned = share_build._clean_yaml({"caps": ["llm", "globex-runner", "ci"], "note": "for Globex", "cpu": "x"},
                                      None, frozenset(), share_build._term_re(("Globex",)))
    assert cleaned == {"caps": ["llm", "ci"], "cpu": "x"}


def test_yaml_keys_that_are_addresses_are_dropped():
    assert share_build._clean_yaml({"nas.home.lan": 1, "10.0.0.1": 2, "keep": 3}) == {"keep": 3}


def test_updated_uses_frontmatter_dates_not_the_checkout_time(tmp_path):
    p = tmp_path / "STATUS.md"
    p.write_text("x", "utf-8")
    t = share_build.Topic(id="a", path=p, rel="a", kind="status", meta={"gesendet": "2026-03-15"})
    assert share_build._updated(t) == "2026-03-15"
    t2 = share_build.Topic(id="b", path=p, rel="b", kind="status", meta={})
    assert share_build._updated(t2) == ""


@pytest.mark.parametrize("template", ["{x.__class__}", "{firma.__class__.__mro__}", "{firma:>999999999}", "{0}"])
def test_summary_templates_cannot_reach_attributes(template):
    assert "class" not in share_build._from_template(template, {"firma": "Initech", "x": {}})


def test_summary_template_optional_segments():
    meta = {"firma": "Initech", "konditionen": {"rate": 100}}
    assert share_build._from_template("{firma}[[, Satz {konditionen[rate]} €/h]][[, Ort {ort}]]", meta) == \
        "Initech, Satz 100 €/h"


def test_cap_keeps_the_newest_sections(tmp_path):
    body = "Intro now.\n\n## Nächster Schritt\n\ncall\n\n" + "\n\n".join(
        f"## Update 2026-0{1 + i // 10}-{10 + i % 10:02d}\n\n" + "y" * 2500 for i in range(30))
    text, _, _ = _one(tmp_path, body)
    assert "Update 2026-03-19" in text and "Update 2026-01-10" not in text
    assert "Intro now." in text and "call" in text


def test_first_sentence_joins_wrapped_lines():
    s = share_build._first_sentence("A sentence that is wrapped\nacross two lines ends here. Next.\n")
    assert s == "A sentence that is wrapped across two lines ends here."


def test_on_request_ids_are_listed_for_the_runtime(setup):
    _, _, out = setup
    assert (out / "peers" / "alice" / ".on_request").read_text("utf-8").split() == ["open-thing"]


def test_text_attachments_are_masked_and_redacted(tmp_path):
    root = _repo(tmp_path)
    (root / "work" / "tasks" / "open-thing" / "deliverables" / "notes.md").write_text(
        "call +49 171 1234567\n\nGlobex paragraph here\n\nkeep this", "utf-8")
    cfg = tmp_path / "access.yaml"
    cfg.write_text(yaml.safe_dump({"schema_version": 1, "sources": ["work/tasks/*/STATUS.md"],
                                   "peers": {"alice": {"default": "files", "redact_terms": ["Globex"]}}}), "utf-8")
    share_build.build(cfg, root=root, out=tmp_path / "share")
    copied = (tmp_path / "share" / "peers" / "alice" / "topics" / "open-thing" / "notes.md").read_text("utf-8")
    assert "1234567" not in copied and "Globex" not in copied and "keep this" in copied


def test_a_redact_term_catches_its_inflections():
    out = share_build._redact("Teil des Globex-Mandats hier.\n\nanderes bleibt", ("Globex-Mandat",))
    assert "Mandats" not in out and "anderes bleibt" in out
