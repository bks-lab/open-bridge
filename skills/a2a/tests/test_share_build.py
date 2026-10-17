"""share_build: one folder per peer from an access file, and grants on request.

The folder is the whole boundary of a peer agent (see agents/_runtime/access.py), so
these tests pin what lands in it: each level carries exactly its fields, a topic at
``none`` is absent everywhere, secrets never appear whatever the level, and a grant
opens exactly the topic the owner said yes to.
"""
from __future__ import annotations

import json
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
    assert "plan.md" in text                      # listed, not copied
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
