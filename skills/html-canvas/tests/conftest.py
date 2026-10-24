"""Shared fixtures for the html-canvas tests.

Browser tests share one headless chromium per session and skip cleanly when
playwright or its browser is not installed. Pages are always opened through
file:// from a fresh temp dir, which is what proves the single-file, offline
contract: nothing the page needs may live next to it.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[1]
ASSETS = SKILL / "assets"
SCRIPTS = SKILL / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "canvas"


@pytest.fixture(scope="session")
def skill_root() -> Path:
    return SKILL


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


def load_script(filename: str):
    """Import a hyphenated script by path (new-simulation.py, repo-scan.py)."""
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_").removesuffix(".py"), SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_new_simulation(out: Path, *extra: str, scripts_dir: Path = SCRIPTS) -> subprocess.CompletedProcess:
    """Run new-simulation.py; `scripts_dir` lets a test point at a mutated copy."""
    return subprocess.run(
        [sys.executable, str(scripts_dir / "new-simulation.py"), "--out", str(out),
         "--design", str(REPO / "DESIGN.md"), *extra],
        capture_output=True, text=True,
    )


def render_shell(main_html: str, lang: str = "en", extra_css: str = "", extra_body: str = "") -> str:
    """The real shell with its <main> replaced, placeholders filled.

    `extra_css` goes before </style>, `extra_body` before </body>, so a test can
    add animations.css or a snippet from the references without a build step.
    """
    html = (ASSETS / "shell.html").read_text("utf-8")
    html = re.sub(r'<main class="wrap">.*?</main>', lambda _: '<main class="wrap">%s</main>' % main_html, html, flags=re.S)
    if lang == "de":
        html = html.replace('<html lang="en" class="">', '<html lang="de" class="">')
        html = html.replace("|| 'en')", "|| 'de')").replace("'data-lang', 'en')", "'data-lang', 'de')")
        mod = load_script("new-simulation.py")
        html = html.replace(mod.LANG_BLOCK_EN, mod.LANG_BLOCK_DE)
    if extra_css:
        html = html.replace("\n</style>\n</head>", "\n" + extra_css + "\n</style>\n</head>", 1)
    if extra_body:
        html = html.replace("</body>", extra_body + "\n</body>", 1)
    for key, val in (("TITLE_DE", "Titel"), ("TITLE_EN", "Title"), ("TITLE", "Title"),
                     ("DATE", "2026-01-01"), ("SOURCE_PATH", "fixture")):
        html = html.replace("{{%s}}" % key, val)
    return html


def md_snippet(md_path: Path, heading: str) -> str:
    """The first fenced code block after `heading` in a reference file.

    Tests run the snippets the docs tell people to paste, not a copy of them.
    """
    lines = md_path.read_text("utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## ") and heading in ln)
    block, inside = [], False
    for ln in lines[start + 1:]:
        if ln.startswith("```"):
            if inside:
                return "\n".join(block)
            inside = True
        elif inside:
            block.append(ln)
    raise AssertionError("no fenced block under %r in %s" % (heading, md_path))


@pytest.fixture(scope="module")
def browser():
    # Module scope on purpose: a live sync playwright instance owns an event loop,
    # and a test in another module that starts its own would fail inside it.
    sync_api = pytest.importorskip("playwright.sync_api")
    pw = sync_api.sync_playwright().start()
    try:
        b = pw.chromium.launch(headless=True)
    except Exception as exc:  # browser binary not installed
        pw.stop()
        pytest.skip("chromium not available: %s" % str(exc).splitlines()[0])
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def open_page(browser, tmp_path):
    """open_page(html, **context_opts) -> page, loaded from file:// in a fresh dir.

    Width stays at 500 px or more: a narrower headless viewport is clamped and
    would measure a layout nobody sees. Page errors are collected on `page.errors`.
    """
    contexts = []
    counter = [0]

    def _open(html: str, **opts):
        opts.setdefault("viewport", {"width": 900, "height": 800})
        init_script = opts.pop("init_script", None)
        ctx = browser.new_context(**opts)
        contexts.append(ctx)
        if init_script:
            ctx.add_init_script(init_script)
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        counter[0] += 1
        d = tmp_path / ("page%d" % counter[0])
        d.mkdir()
        f = d / "index.html"
        f.write_text(html, encoding="utf-8")
        page.goto(f.as_uri())
        return page

    yield _open
    for c in contexts:
        c.close()
