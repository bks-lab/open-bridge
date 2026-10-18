# SPDX-License-Identifier: MIT
"""The Betrieb page's cost and token cards end to end: the files the collectors write are the files the cards read.

Each part has its own tests against the shapes in its own head. This file runs the real chain once, with fakes
only at the edges (the provider CLIs, the keychain, the ECB, ssh), and renders the cards from what comes out:

- scripts/cloud-costs.py writes the report -> bridge-resources.py costs keeps costs-view.json -> GET /api/costs
  serves it -> CostCard (scripts/web/views/costs.js) draws it, the login command included;
- usage.py on another machine exports (usage-export) -> this machine reads it over ssh -> view(days=30)
  -> GET /api/usage?days=30 -> UsageCard draws the Bridges of both machines.

The render step runs Node with scripts/tests/cockpit_render.mjs; without Node it is skipped.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
for p in (ROOT / "scripts", ROOT / "scripts" / "lib", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = _load("cloud_costs_contract", "scripts/cloud-costs.py")
br = _load("bridge_resources_contract", "scripts/bridge-resources.py")

TODAY = dt.date.today()
SUB = "00000000-0000-0000-0000-000000000001"
ECB = b"""<gesmes:Envelope><Cube><Cube time='2026-10-16'><Cube currency='USD' rate='1.08'/></Cube></Cube></gesmes:Envelope>"""


@pytest.fixture(autouse=True)
def private_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_COCKPIT_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude"))


def bridge(base: Path) -> Path:
    acc = base / "identity" / "accounts"
    con = base / "identity" / "contracts"
    acc.mkdir(parents=True)
    con.mkdir(parents=True)
    (acc / "_template.yaml").write_text("costs: {enabled: true}\n")
    (acc / "azure-example.yaml").write_text(
        f"id: azure-example\ndisplay_name: Example Azure\nstatus: active\ncloud: {{provider: azure}}\n"
        f"tenant: {{id: 00000000-0000-0000-0000-0000000000aa}}\nsubscriptions:\n  - id: {SUB}\n"
        "costs: {enabled: true, group_by: service, budget_month: 5}\n")
    (acc / "openai-example.yaml").write_text(
        "id: openai-example\ndisplay_name: Example OpenAI\nstatus: active\ncloud: {provider: openai}\n"
        "costs: {enabled: true, key_ref: 'keychain://openai-admin/example'}\n")
    (con / "example-plan.yaml").write_text(
        "id: example-plan\ndisplay_name: Example plan\nproduct: Pro plan\nstatus: active\n"
        "pricing: {monthly_fee: {gross: 20}}\ncosts: {enabled: true}\n")
    return base


def fake_run(argv, **kw):
    if argv[:2] == ["az", "rest"]:
        start = TODAY - dt.timedelta(days=6)
        rows = [[1.5 + i * 0.1, int((start + dt.timedelta(days=i)).strftime("%Y%m%d")), "Functions", "EUR"] for i in range(7)]
        rows += [[0.25, int(TODAY.strftime("%Y%m%d")), "Storage", "EUR"]]
        body = {"properties": {"columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "ServiceName"},
                                           {"name": "Currency"}], "rows": rows}}
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")
    if "find-generic-password" in argv:     # no key stored yet: the account must ask for it
        return types.SimpleNamespace(returncode=44, stdout="", stderr="could not be found")
    raise AssertionError(f"unexpected call {argv}")


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(req, timeout=None):
    assert "ecb.europa.eu" in req.full_url
    return Resp(ECB)


def render(script: str, fixture: dict, tmp_path: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    runner = tmp_path / "render.mjs"
    runner.write_text(
        f"import fs from 'node:fs'\n"
        f"const {{ loadCockpit, mount, cockpitState, recorder }} = await import({json.dumps((HERE / 'cockpit_render.mjs').as_uri())})\n"
        f"const {{ html, views, text: tx }} = await loadCockpit()\n"
        f"const fx = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'fixture.json'))}, 'utf8'))\n"
        f"const out = {{}}\n{script}\nprocess.stdout.write(JSON.stringify(out))\n", encoding="utf-8")
    res = subprocess.run([node, str(runner)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_the_cost_report_reaches_the_cost_card_with_the_keys_it_reads(tmp_path):
    from test_bridge_cockpit import World
    root = bridge(tmp_path / "src")
    report = tmp_path / "out" / "costs.json"
    assert cc.main(["--root", str(root), "--host", "my-server", "--out", str(report)], run=fake_run, opener=fake_opener) == 0
    doc = json.loads(report.read_text())
    by = {a["id"]: a for a in doc["accounts"]}
    assert by["azure-example"]["ok"] and by["example-plan"]["kind"] == "fixed"
    assert by["openai-example"]["error_kind"] == "auth"

    world = World(tmp_path / "w")
    try:
        now = dt.datetime.now().astimezone()
        rows = br.cost_rows(world.root, br.TX["de"], f"ssh:my-server:{report}", now, 36,
                            run=lambda argv, **kw: types.SimpleNamespace(returncode=0, stdout=report.read_text(), stderr=""))
        assert {r["id"] for r in rows} >= {"costs:azure-example", "costs:openai-example", "costs:example-plan"}
        status, _, body = world.request("GET", "/api/costs", headers=world.cookie)
        view = json.loads(body)["view"]
    finally:
        world.close()
    assert status == 200
    # the head of the card
    for key in ("at", "host", "source", "stale", "currency", "accounts"):
        assert key in view, key
    assert view["stale"] is False and view["source"] and view["host"] == "my-server"
    acc = {a["id"]: a for a in view["accounts"]}
    # every key the card and its helpers read off an account (views/costs.js, logic.js)
    for a in acc.values():
        for key in ("id", "display_name", "provider", "kind", "ok", "error", "currency", "original_currency",
                    "budget_month", "days", "month_to_date", "forecast_month"):
            assert key in a, (a["id"], key)
    day = acc["azure-example"]["days"][-1]
    assert set(day) >= {"day", "amount", "provisional", "groups"} and day["groups"]["Storage"] == 0.25
    ask = acc["openai-example"]
    assert ask["login"]["hint"] and ask["login_command"].startswith("ssh -t my-server ")
    # the store command names the collecting Bridge's own secrets skill by absolute path, with its root, because
    # ssh starts in the remote home directory, not in the Bridge
    import shlex
    inner = shlex.split(shlex.split(ask["login_command"])[-1])
    assert inner[:2] == ["bash", str(root / "skills" / "secrets" / "secrets.sh")]
    assert inner[2:4] == ["store", "keychain://openai-admin/example"] and inner[inner.index("--root") + 1] == str(root)

    shown = render("""
tx.setLanguage('de')
const c = recorder()
const s = cockpitState(Date.now(), { costs: { status: 'ok', data: fx, error: null } })
const el = mount(html`<${views.costs.CostCard} page=${{ id: 'ops' }} s=${s} c=${c} />`)
out.title = el.$('.sec-title').text()
out.bars = el.$$('.ubar').length
out.rows = el.$$('.crow').length
out.text = el.text()
const failed = el.$('.crow.is-failed')
out.failed = failed ? failed.text() : null
out.code = failed && failed.$('code') ? failed.$('code').text() : null
if (failed) failed.button('Befehl kopieren').click()
out.copied = (c.calls.find(x => x[0] === 'copy') || [])[1] || null
const page = { id: 'ops', title: 'Ops', overview: true, sections: [], cards: [{ id: 'costs', after: null }] }
const board = mount(html`<${views.pages.OverviewBoard} page=${page} s=${s} c=${recorder()} />`)
out.tileBars = board.$$('.otile-bar').length
""", view, tmp_path)
    assert shown["title"] == "Cloud-Kosten" and shown["bars"] == 7 and shown["rows"] == 3
    assert "Example Azure" in shown["text"] and "Example plan" in shown["text"]
    assert "NaN" not in shown["text"] and "undefined" not in shown["text"] and "null" not in shown["text"]
    assert "Anmeldung nötig" in shown["failed"] and shown["code"] == ask["login_command"]
    assert shown["copied"] == ask["login_command"]
    assert shown["tileBars"] == 7


def test_another_machines_token_export_reaches_the_token_card(tmp_path):
    from bridge_cockpit import usage
    from test_bridge_cockpit_usage import line, write
    from test_bridge_cockpit import World
    # the other machine: its transcripts, its Bridge, its export
    far = tmp_path / "far"
    write(far / "claude", "p/s.jsonl", [line(mid="a", out=40, cwd="/srv/far-bridge/x")])
    (far / "root" / "infra" / "instances").mkdir(parents=True)
    (far / "root" / "infra" / "instances" / "far.yaml").write_text("name: Far\nlocation: {path: /srv/far-bridge}\n")
    export = usage.Usage(base=far / "claude", now=lambda: usage_now(), root=far / "root", host="my-server",
                         remotes=False).export(days=90)
    # this machine: one session of its own, and the other machine as a remote
    world = World(tmp_path / "w", config="cockpit:\n  enabled: true\n  usage:\n    remotes: [my-server, gone-box]\n")
    try:
        home = tmp_path / "near"
        write(home, "p/s.jsonl", [line(mid="b", out=7, cwd=str(world.root / "x"))])

        def ssh(argv, **kw):
            if "my-server" in argv:
                return types.SimpleNamespace(returncode=0, stdout=json.dumps(export), stderr="")
            return types.SimpleNamespace(returncode=255, stdout="", stderr="ssh: connect to host gone-box: timed out")
        world.app.usage = usage.Usage(base=home, now=lambda: usage_now(), root=world.root, host="my-laptop", run=ssh)
        world.app.usage.refresh_remotes()
        status, _, body = world.request("GET", "/api/usage?days=30", headers=world.cookie)
    finally:
        world.close()
    assert status == 200
    view = json.loads(body)["usage"]
    assert view["range"] == 30 and len(view["days"]) == 30 and view["host"] == "my-laptop"
    hosts = {h["host"]: h for h in view["hosts"]}
    assert hosts["my-laptop"]["local"] and hosts["my-server"]["ok"] and hosts["gone-box"]["ok"] is False
    assert {(b["bridge"], b["host"]) for b in view["bridges"]} >= {("Far", "my-server")}
    assert view["total"]["output"] == 47

    shown = render("""
const c = recorder()
const s = cockpitState(Date.now(), { usage: { status: 'ok', data: fx, error: null, days: 30 } })
const el = mount(html`<${views.costs.UsageCard} page=${{ id: 'ops' }} s=${s} c=${c} />`)
out.bars = el.$$('.ubar').length
out.brows = el.$$('.brow').length
out.failed = el.$('.brow.is-failed') ? el.$('.brow.is-failed').text() : null
out.text = el.text()
""", view, tmp_path)
    assert shown["bars"] == 30
    assert shown["brows"] == len(view["bridges"]) + 1
    assert "gone-box: not reachable" in shown["failed"]
    assert "Far" in shown["text"] and "my-server" in shown["text"] and "NaN" not in shown["text"]


def usage_now() -> dt.datetime:
    from test_bridge_cockpit_usage import NOW
    return NOW


# ---------------------------------------------------------------- the four series of a stacked chart

def _rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lab(c: tuple) -> tuple:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = map(lin, c)
    x, y, z = ((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b,
               (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _delta(a: tuple, b: tuple) -> float:
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5


def _resolve(expr: str, tokens: dict):
    """A series value of style.css against one palette: var(--x), color-mix(in srgb, var(--a) N%, var(--b)),
    or a pattern (a gradient), which is told apart by its shape, not its colour."""
    import re
    expr = expr.strip()
    if "gradient(" in expr:
        return "pattern"
    m = re.fullmatch(r"var\(--([a-z0-9-]+)\)", expr)
    if m:
        value = tokens[m.group(1)]
        return _resolve(value, tokens) if value.startswith(("var(", "color-mix(")) else _rgb(value)
    m = re.fullmatch(r"color-mix\(in srgb, (var\(--[a-z0-9-]+\)) (\d+)%, (var\(--[a-z0-9-]+\))\)", expr)
    assert m, f"cannot resolve {expr}"
    a, p, b = _resolve(m.group(1), tokens), int(m.group(2)) / 100, _resolve(m.group(3), tokens)
    return tuple(round(x * p + y * (1 - p)) for x, y in zip(a, b))


def test_the_four_series_and_the_track_are_told_apart_in_both_modes():
    import re
    from lib.bridge_cockpit import design
    css = (ROOT / "scripts" / "web" / "style.css").read_text(encoding="utf-8")
    series = dict(re.findall(r"\.sr-(\d) \{ --us: (.+?); \}", css))
    assert sorted(series) == ["0", "1", "2", "3"], series
    for name, pal in (("DESIGN.md", design.palette(design.front_matter(ROOT / "DESIGN.md"))), ("defaults", design.palette({}))):
        for mode in ("light", "dark"):
            tokens = {**pal[mode], **design.DERIVED[mode]}
            got = {k: _resolve(v, tokens) for k, v in series.items()}
            assert got["3"] == "pattern", "the rest is hatched, so it never takes a colour of a named series"
            solid = [got[k] for k in ("0", "1", "2")]
            track = _rgb(tokens["surface-muted"])
            for i, a in enumerate(solid):
                assert _delta(a, track) >= 15, (name, mode, f"sr-{i} vanishes into the bar track")
                for j in range(i + 1, 3):
                    assert _delta(a, solid[j]) >= 15, (name, mode, f"sr-{i} and sr-{j} look alike")
