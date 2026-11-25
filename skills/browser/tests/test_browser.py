"""Tests for skills/browser/scripts/browser.py.

Hermetic by default: nothing here starts a browser. `runner` stands in for the
subprocess call and records every argv. The one live test drives a real Chrome
and runs only with BROWSER_LIVE=1 and playwright-cli on PATH.
"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "browser.py"


def load():
    spec = importlib.util.spec_from_file_location("browser_skill", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["browser_skill"] = mod
    spec.loader.exec_module(mod)
    return mod


B = load()

SNAPSHOT = """### Page
- Page URL: http://127.0.0.1:8765/form.html
- Page Title: Prüfseite
### Snapshot
```yaml
- generic [active] [ref=f1e1]:
  - heading "Prüfseite" [level=1] [ref=f1e2]
  - generic [ref=f1e3]:
    - text: Name
    - textbox "Name" [ref=f1e4]
  - combobox "Farbe" [ref=f1e5]:
    - option "rot" [selected]
  - checkbox "Zustimmen" [ref=f1e7]
  - button "Senden" [ref=e9]
```
"""


class Recorder:
    def __init__(self, outputs=None):
        self.calls = []
        self.outputs = outputs or {}

    def __call__(self, argv):
        self.calls.append(argv)
        for key, out in self.outputs.items():
            if key in argv:
                return 0, out
        return 0, "### Ran Playwright code\n"


# ---------- refs ----------

def test_find_ref_reads_role_and_name():
    assert B.find_ref(SNAPSHOT, "textbox", "Name") == "f1e4"
    assert B.find_ref(SNAPSHOT, "combobox", "Farbe") == "f1e5"
    assert B.find_ref(SNAPSHOT, "button", "Senden") == "e9"


def test_find_ref_missing_returns_none():
    assert B.find_ref(SNAPSHOT, "button", "Abbrechen") is None


def test_find_ref_does_not_match_a_longer_name():
    snap = '  - button "Senden später" [ref=e3]\n  - button "Senden" [ref=e4]\n'
    assert B.find_ref(snap, "button", "Senden") == "e4"


def test_page_url():
    assert B.page_url(SNAPSHOT) == "http://127.0.0.1:8765/form.html"


# ---------- target ----------

def test_target_defaults_to_chrome():
    assert B.resolve_target(None, None, {}) == ("chrome", None)


def test_target_from_environment():
    env = {"BRIDGE_BROWSER_TARGET": "cdp", "BRIDGE_BROWSER_CDP_URL": "http://127.0.0.1:9333"}
    assert B.resolve_target(None, None, env) == ("cdp", "http://127.0.0.1:9333")


def test_flag_beats_environment():
    env = {"BRIDGE_BROWSER_TARGET": "cdp", "BRIDGE_BROWSER_CDP_URL": "http://127.0.0.1:9333"}
    assert B.resolve_target("chrome", None, env) == ("chrome", None)


def test_cdp_without_address_is_an_error():
    with pytest.raises(B.BrowserError):
        B.resolve_target("cdp", None, {})


def test_cdp_address_must_be_local():
    with pytest.raises(B.BrowserError):
        B.resolve_target("cdp", "http://10.0.0.5:9222", {})


def test_unknown_target_is_an_error():
    with pytest.raises(B.BrowserError):
        B.resolve_target("safari", None, {})


# ---------- start ----------

def test_start_chrome_opens_a_persistent_visible_session():
    rec = Recorder()
    B.start("bahn", "https://www.bahn.de", ("chrome", None), headed=True, runner=rec, cli="pwc")
    assert rec.calls == [["pwc", "-s=bahn", "open", "https://www.bahn.de",
                          "--browser=chrome", "--persistent", "--headed"]]


def test_start_chrome_headless_leaves_out_headed():
    rec = Recorder()
    B.start("probe", None, ("chrome", None), headed=False, runner=rec, cli="pwc")
    assert rec.calls == [["pwc", "-s=probe", "open", "--browser=chrome", "--persistent"]]


def test_start_cdp_attaches_then_navigates():
    rec = Recorder()
    B.start("bahn", "https://www.bahn.de", ("cdp", "http://127.0.0.1:9333"), headed=True, runner=rec, cli="pwc")
    assert rec.calls == [["pwc", "-s=bahn", "attach", "--cdp=http://127.0.0.1:9333"],
                         ["pwc", "-s=bahn", "goto", "https://www.bahn.de"]]


def test_session_name_is_checked():
    with pytest.raises(B.BrowserError):
        B.start("bad name", None, ("chrome", None), headed=False, runner=Recorder(), cli="pwc")


def test_cli_error_output_raises():
    rec = Recorder({"open": "### Error\nAccess to \"file:\" protocol is blocked."})
    with pytest.raises(B.BrowserError):
        B.start("probe", "file:///x.html", ("chrome", None), headed=False, runner=rec, cli="pwc")


# ---------- check ----------

def test_check_steps_cover_the_common_commands():
    names = [s for s, _ in B.CHECK_STEPS]
    for needed in ("fill", "select", "check", "upload", "click", "wait", "eval", "console", "screenshot"):
        assert needed in names


def test_check_page_has_the_controls_the_steps_use():
    page = B.CHECK_PAGE
    for needle in ('aria-label="Farbe"', 'type="file"', ">Senden<", "Zustimmen"):
        assert needle in page


@pytest.mark.skipif(os.environ.get("BROWSER_LIVE") != "1" or not shutil.which("playwright-cli"),
                    reason="live run: set BROWSER_LIVE=1 and install playwright-cli")
def test_live_check_against_chrome(tmp_path):
    results = B.run_check(("chrome", None), workdir=tmp_path)
    failed = [r for r in results if not r[1]]
    assert not failed, failed
