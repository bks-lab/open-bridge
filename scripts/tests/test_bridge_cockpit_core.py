# SPDX-License-Identifier: MIT
"""The cockpit as CORE: what ships to another Bridge must load there and carry nothing of this one.

Three guards:
- import closure: every file a CORE dashboard file loads statically is CORE too (scripts/categorize-commits.py
  SCRIPTS_CORE_ALLOWLIST), so a promote never ships a page that cannot load; an optional integration is
  loaded with a dynamic import() behind its switch and may stay out;
- no instance words in CORE dashboard files (names, hosts, profile ids), with a short exception list;
- a fresh Bridge: the server against a bare tree (no cmux, no Jev, no resources, no workers source) answers
  every endpoint the page needs, and its state names nobody.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_spec = importlib.util.spec_from_file_location("categorize_commits", ROOT / "scripts" / "categorize-commits.py")
_cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cc)
CORE = _cc.SCRIPTS_CORE_ALLOWLIST

# text files only: the fonts and icons the page serves itself are binary and name nothing
DASHBOARD = sorted(p for p in CORE if not p.endswith((".woff2", ".png", ".ico")) and p.startswith(("scripts/web/", "scripts/lib/bridge_cockpit/")) or p in (
    "scripts/bridge-cockpit.py", "scripts/bridge-resources.py", "scripts/cloud-inventory.py", "scripts/cloud-costs.py",
    "scripts/usage-export.py", "scripts/cockpit-usage.py", "scripts/bridge-setup.py", "scripts/lib/briefing_view.py"))

JS_STATIC = re.compile(r"""^\s*(?:import|export)\b[^'"]*?\bfrom\s+['"](\.{1,2}/[^'"]+)['"]|^\s*import\s+['"](\.{1,2}/[^'"]+)['"]""", re.M)
HTML_REF = re.compile(r"""<(?:script|link)\b[^>]*?\b(?:src|href)=["'](?!https?:|//|#)([^"']+)["']""")


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def static_deps(rel: str) -> list[str]:
    path = ROOT / rel
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if rel.endswith((".js", ".mjs")):
        return [_rel(path.parent / (a or b)) for a, b in JS_STATIC.findall(text)]
    if rel.endswith(".html"):
        return [_rel(path.parent / ref.split("?")[0]) for ref in HTML_REF.findall(text)]
    if rel.endswith(".py") and rel.startswith("scripts/lib/bridge_cockpit/"):
        out = []
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and node.level >= 1:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                mods = [node.module] if node.module else [a.name for a in node.names]
                for mod in mods:
                    target = base.joinpath(*mod.split("."))
                    for cand in (target.with_suffix(".py"), target / "__init__.py"):
                        if cand.is_file():
                            out.append(_rel(cand))
                            break
        return out
    return []


def test_the_dashboard_list_is_not_empty():
    assert "scripts/web/components.js" in DASHBOARD and "scripts/lib/bridge_cockpit/server.py" in DASHBOARD


def test_every_static_import_of_a_core_dashboard_file_is_core():
    missing = {f"{rel} -> {dep}" for rel in DASHBOARD for dep in static_deps(rel)
               if dep not in CORE and not dep.startswith("scripts/web/vendor/") and dep not in SERVED}
    assert not missing, "CORE files load files that would not ship:\n" + "\n".join(sorted(missing))


# what the server renders itself and no file holds: the colours from the Bridge's DESIGN.md (design.py)
SERVED = {"scripts/web/colors.css"}


def test_the_closure_check_sees_a_static_import_and_ignores_a_dynamic_one(tmp_path):
    js = "import { a } from './x.js'\nexport { b } from '../y.js'\nconst m = await import('./optional.js')\n"
    assert [a or b for a, b in JS_STATIC.findall(js)] == ["./x.js", "../y.js"]


def instance_words(root: Path) -> list:
    """The words that name this instance, read from the instance itself, so this CORE test carries no name:
    identity.name and identity.org, cockpit.person_name, git user.name, and the machines in infra/remotes/.
    A fresh clone without a config has none, and the check then has nothing to find."""
    words = set()
    try:
        cfg = yaml.safe_load((root / "bridge-config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        cfg = {}
    ident = cfg.get("identity") if isinstance(cfg.get("identity"), dict) else {}
    cockpit = cfg.get("cockpit") if isinstance(cfg.get("cockpit"), dict) else {}
    for value in (ident.get("name"), ident.get("org"), cockpit.get("person_name")):
        if isinstance(value, str) and len(value) >= 3:
            words |= {value.lower(), value.lower().replace("-", " ")}
    git = subprocess.run(["git", "-C", str(root), "config", "user.name"], capture_output=True, text=True)
    if git.returncode == 0 and len(git.stdout.strip()) >= 3:
        words.add(git.stdout.strip().lower())
    for path in (root / "infra" / "remotes").glob("*.yaml"):
        if not path.name.startswith("_") and len(path.stem) >= 6:
            words.add(path.stem.lower())
    return sorted(words)


# words that name this instance; a CORE file names none of them
_WORDS = instance_words(ROOT)
INSTANCE_WORDS = re.compile(r"\b(" + "|".join(map(re.escape, _WORDS)) + r")\b", re.I) if _WORDS else re.compile(r"(?!)")
PROFILE_ID = re.compile(r"""['"]morning['"]""")
EXCEPTIONS = {
    # the demo data of the page (mock.js) names a profile; "morning" is the CORE example profile name
    ("scripts/web/mock.js", "profile"),
}


def test_the_instance_words_come_from_the_instance(tmp_path):
    (tmp_path / "infra" / "remotes").mkdir(parents=True)
    (tmp_path / "infra" / "remotes" / "studio-box7.yaml").write_text("id: studio-box7\n", encoding="utf-8")
    (tmp_path / "infra" / "remotes" / "_template.yaml").write_text("id: x\n", encoding="utf-8")
    (tmp_path / "bridge-config.yaml").write_text(
        "identity:\n  name: ada\n  org: acme-labs\ncockpit:\n  person_name: Ada Example\n", encoding="utf-8")
    words = instance_words(tmp_path)
    assert {"ada", "acme-labs", "acme labs", "ada example", "studio-box7"} <= set(words) and "_template" not in words
    assert instance_words(tmp_path / "missing") == []                 # a fresh clone: nothing to look for


def test_no_instance_words_in_core_dashboard_files():
    hits = []
    for rel in DASHBOARD:
        path = ROOT / rel
        if not path.is_file() or "/vendor/" in rel:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if INSTANCE_WORDS.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:120]}")
            elif PROFILE_ID.search(line) and (rel, "profile") not in EXCEPTIONS:
                hits.append(f"{rel}:{n}: {line.strip()[:120]}")
    assert not hits, "instance words in CORE files:\n" + "\n".join(hits)


# ---------------------------------------------------------------- a fresh Bridge

FRESH_CONFIG = "cockpit:\n  enabled: true\n  language: en\n"


@pytest.fixture(autouse=True)
def private_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_COCKPIT_KEY_DIR", str(tmp_path / "default-keys"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude"))


@pytest.fixture
def fresh(tmp_path):
    from test_bridge_cockpit import World
    w = World(tmp_path, config=FRESH_CONFIG, cmux=None)
    yield w
    w.close()


def test_a_fresh_bridge_answers_what_the_page_needs_and_names_nobody(fresh):
    status, _, body = fresh.request("GET", "/api/state", headers=fresh.cookie)
    assert status == 200
    state = json.loads(body)
    assert state["jev"]["enabled"] is False                       # an optional integration stays off
    status, _, body = fresh.request("GET", "/api/workers", headers=fresh.cookie)
    assert status == 200 and json.loads(body)["view"] is None     # no workers source: no tab, and no error either
    assert fresh.request("GET", "/api/bootstrap", headers=fresh.cookie)[0] == 200
    text = json.dumps(state, ensure_ascii=False)
    assert not INSTANCE_WORDS.search(text), INSTANCE_WORDS.search(text)


def test_without_a_name_the_chat_and_jev_say_the_user(fresh):
    from lib.bridge_cockpit import jev
    from lib.bridge_cockpit.quick import system_text
    assert fresh.app.cfg.person_name is None
    assert "the user" in system_text(fresh.app.cfg.language, fresh.app.cfg.person_name)
    req = jev.build_request([{"id": "t1", "key": "a", "title": "x"}], "2026-10-10", lang="en")
    assert not INSTANCE_WORDS.search(json.dumps(req))


def test_jev_is_loaded_only_when_switched_on():
    """The Jev page is an optional integration: nothing loads it statically, the page imports it with
    import() behind s.jev.enabled, and its stylesheet comes with it."""
    for rel in ("scripts/web/components.js", "scripts/web/app.js", "scripts/web/index.html"):
        assert not [d for d in static_deps(rel) if "/jev/" in d], rel
    comp = (ROOT / "scripts/web/components.js").read_text(encoding="utf-8")
    assert re.search(r"import\(\s*['\"]\./jev/page\.js['\"]\s*\)", comp)


# ---------------------------------------------------------------- Jev is optional: off unless a Bridge says so

def test_jev_is_off_by_default_in_the_template_and_in_code(tmp_path):
    import yaml
    from lib.bridge_cockpit.config import load_web_config
    template = yaml.safe_load((ROOT / "bridge-config.yaml.template").read_text(encoding="utf-8"))
    assert template["integrations"]["typesafe"]["enabled"] is False
    for raw in ({}, {"integrations": {}}, {"integrations": {"typesafe": {}}}, {"integrations": {"typesafe": {"enabled": "true"}}}):
        assert load_web_config(tmp_path, raw).jev_enabled is False, raw


def test_jev_criteria_come_from_config_and_a_bad_scale_keeps_the_default(tmp_path):
    from lib.bridge_cockpit import jev
    from lib.bridge_cockpit.config import load_web_config
    own = ["a", "b", "c", "d"]
    cfg = load_web_config(tmp_path, {"integrations": {"typesafe": {"criteria": {"impact": own, "effort": ["only", "three", "x"]}}}})
    assert cfg.jev_criteria == {"impact": own}
    req = jev.build_request([{"id": "t1", "key": "k", "title": "x"}], "2026-10-10", lang="en", criteria=cfg.jev_criteria)
    assert req["questions"]["t1.impact"]["criteria"] == own
    assert req["questions"]["t1.effort"]["criteria"] == jev.TEXT["en"]["effort"]


def test_jev_model_is_pinned_and_a_bridge_may_choose_another_version(tmp_path):
    from lib.bridge_cockpit import jev
    from lib.bridge_cockpit.config import load_web_config
    assert load_web_config(tmp_path, {}).jev_model is None
    assert jev.build_request([], "2026-10-10", model=None)["model"] == jev.MODEL
    for bad in ("jev-latest", "jev-1.14.0; rm", "gpt-5", "", 7, "jev-"):
        assert load_web_config(tmp_path, {"integrations": {"typesafe": {"model": bad}}}).jev_model is None, bad
    cfg = load_web_config(tmp_path, {"integrations": {"typesafe": {"model": "jev-1.13.0"}}})
    assert cfg.jev_model == "jev-1.13.0"
    req = jev.build_request([{"id": "t1", "key": "k", "title": "x"}], "2026-10-10", model=cfg.jev_model)
    assert req["model"] == "jev-1.13.0"

SERVE_WITHOUT_JEV = r"""
import http.client, json, sys, threading
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from lib.bridge_cockpit import server
assert server.jev is None, "jev.py was found"
srv = server.make_server(Path(sys.argv[2]), port=0, state_dir=Path(sys.argv[3]), background=False, key_dir=Path(sys.argv[4]))
threading.Thread(target=srv.serve_forever, daemon=True).start()
app = srv.app
def call(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", app.port, timeout=5)
    h = {"Host": f"127.0.0.1:{app.port}", "Cookie": f"{app.cookie_name}={app.session_value()}"}
    if body is not None:
        h.update({"X-Bridge-Token": app.csrf, "Origin": f"http://127.0.0.1:{app.port}", "Content-Type": "application/json"})
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    r = c.getresponse(); data = r.read(); c.close()
    return r.status, data
s, body = call("GET", "/api/state")
out = {"state": s, "jev": json.loads(body)["jev"], "page": call("GET", "/")[0], "components": call("GET", "/components.js")[0],
       "run": call("POST", "/api/jev/run", {})}
out["run"] = [out["run"][0], json.loads(out["run"][1])["error"]["code"]]
print(json.dumps(out))
app.stop(); srv.shutdown(); srv.server_close()
"""


def test_a_bridge_without_the_jev_files_loads_and_says_jev_is_off(tmp_path):
    """jev.py and scripts/web/jev/ removed, switched on in the config even: the server starts, the page
    and its modules are served, Jev reports off and its endpoint answers 404 jev_off."""
    import shutil
    import subprocess
    copy = tmp_path / "bridge"
    shutil.copytree(ROOT / "scripts", copy / "scripts", ignore=shutil.ignore_patterns("tests", "__pycache__", ".bridge"))
    (copy / "scripts" / "lib" / "bridge_cockpit" / "jev.py").unlink()
    shutil.rmtree(copy / "scripts" / "web" / "jev")
    (copy / "bridge-config.yaml").write_text(
        "cockpit:\n  enabled: true\n  language: en\nintegrations:\n  typesafe:\n    enabled: true\n", encoding="utf-8")
    run = subprocess.run([sys.executable, "-c", SERVE_WITHOUT_JEV, str(copy / "scripts"), str(copy), str(tmp_path / "state"),
                          str(tmp_path / "keys")], capture_output=True, text=True, timeout=60,
                         env={**__import__("os").environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "no-claude")})
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert out["state"] == 200 and out["page"] == 200 and out["components"] == 200
    assert out["jev"] == {"enabled": False, "ready": False, "reason": "off"}
    assert out["run"] == [404, "jev_off"]


# ---------------------------------------------------------------- the smaller text tables (rules/language-policy.md section 3)
#
# Besides text.js and text.py, a few files word their own data in both languages. Each keeps its
# languages side by side under identical keys, and none may leave a value empty.

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _shape(value, where=""):
    """Every leaf path of a table, failing on an empty value."""
    if isinstance(value, dict):
        return {p for k, v in value.items() for p in _shape(v, f"{where}/{k}")}
    assert value not in (None, "", [], ()), where
    return {where}


def _small_tables():
    from lib import briefing_view
    from lib.bridge_cockpit import agents
    resources = _load("bridge_resources_tables", ROOT / "scripts" / "bridge-resources.py")
    advise = _load("advise_tables", ROOT / "skills" / "briefing" / "scripts" / "advise.py")
    return {"briefing_view": (briefing_view.LABELS, briefing_view.LABELS_DE),
            "bridge-resources": (resources.TX["en"], resources.TX["de"]),
            "advise": (advise.TEXTS["en"], advise.TEXTS["de"]),
            "agents.TASK_FRAME": ({"frame": agents.TASK_FRAME["en"]}, {"frame": agents.TASK_FRAME["de"]})}


@pytest.mark.parametrize("name", ["briefing_view", "bridge-resources", "advise", "agents.TASK_FRAME"])
def test_a_small_text_table_has_the_same_keys_in_both_languages(name):
    en, de = _small_tables()[name]
    assert _shape(en) == _shape(de)


def test_the_jev_page_table_has_the_same_keys_in_both_languages():
    text = (ROOT / "scripts" / "web" / "jev" / "page.js").read_text(encoding="utf-8")
    body = text[text.index("const TEXT = {"):]
    de = body[body.index("  de: {"):body.index("  en: {")]
    en = body[body.index("  en: {"):body.index("\n}\n")]
    keys = lambda block: set(re.findall(r"(?:^|[{,])\s*(\w+):\s", block, re.M)) - {"de", "en"}   # noqa: E731
    assert keys(de) and keys(de) == keys(en)


# ---------------------------------------------------------------- error codes (contract section 8.2)
#
# errorText (scripts/web/logic.js) words an error by its code and falls back to the server's
# English message, so a new code with no entry in the errors tables of text.js ships untranslated
# without anyone noticing. Every code the server or the demo mock sends needs both entries.

ERROR_CODE_PATTERNS = (r"\w*Error\(\s*\d{3},\s*\"([a-z_]+)\"",      # ActionError, LaunchError, JevError, ...
                       r"send_error_json\(\s*\"([a-z_]+)\"",
                       r"\"code\":\s*\"([a-z_]+)\"")
MOCK_ERROR_PATTERN = r"fail\(\s*\d{3},\s*'([a-z_]+)'"
INTERNAL_CODES: set[str] = set()   # a code the page never shows; none so far


def error_codes_in(source: str, patterns=ERROR_CODE_PATTERNS) -> set[str]:
    return {code for pattern in patterns for code in re.findall(pattern, source)}


def error_tables() -> dict[str, set[str]]:
    text = (ROOT / "scripts" / "web" / "text.js").read_text(encoding="utf-8")
    starts = [m.end() for m in re.finditer(r"^  errors: \{\n", text, re.M)]
    assert len(starts) == 2, "text.js should hold one errors table per language"
    tables = [set(re.findall(r"^    (\w+):", text[s:text.index("\n  },", s)], re.M)) for s in starts]
    return dict(zip(("en", "de"), tables))


def test_the_error_code_collector_sees_every_way_a_code_is_sent():
    source = ('raise ActionError(409, "alpha", "x")\nraise JevError(\n    502, "beta", "y")\n'
              'self.send_error_json("gamma", "z")\nhandler.send_json(404, {"ok": False, "error": {"code": "delta"}})\n')
    assert error_codes_in(source) == {"alpha", "beta", "gamma", "delta"}
    assert error_codes_in("return fail(404, 'epsilon', 'off')", (MOCK_ERROR_PATTERN,)) == {"epsilon"}


def test_every_error_code_the_server_sends_is_worded_in_both_languages():
    lib = ROOT / "scripts" / "lib" / "bridge_cockpit"
    codes = set().union(*(error_codes_in(p.read_text(encoding="utf-8")) for p in sorted(lib.glob("*.py"))))
    codes |= error_codes_in((ROOT / "scripts" / "web" / "mock.js").read_text(encoding="utf-8"), (MOCK_ERROR_PATTERN,))
    assert {"stale_row", "unreadable", "jev_off", "relay_disabled"} <= codes   # the collector still finds them
    tables = error_tables()
    for lang, keys in tables.items():
        assert codes - INTERNAL_CODES - keys == set(), f"text.js errors ({lang}) lacks these codes"
    assert tables["en"] == tables["de"]
