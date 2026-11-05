"""Helpers shared by the html-canvas tests (imported by name, unlike conftest).

A uniquely named module on purpose: several skills ship a tests/conftest.py, and
`from conftest import ...` resolves to whichever one pytest imported first when
the suites run in one session. Tests import from here; conftest.py keeps only
fixtures.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[1]
ASSETS = SKILL / "assets"
SCRIPTS = SKILL / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "canvas"


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


def mini_bridge(tmp_path: Path, brand_primary: str = "#5A1E3C") -> Path:
    """A throwaway Bridge holding this skill, scripts/designs.py and two designs.

    The scripts find their Bridge three levels above themselves, so a test that
    needs a context or a theme pointing at a design runs a copy that lives in a
    tree it may write. The root DESIGN.md and the design `brand` are the token
    fixture, `brand` with its primary changed so a page shows which one it wore.
    """
    import shutil
    root = tmp_path / "bridge"
    (root / ".git").mkdir(parents=True)
    shutil.copytree(SKILL, root / "skills" / "html-canvas", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (root / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "designs.py", root / "scripts" / "designs.py")
    fixture = (Path(__file__).resolve().parent / "fixtures" / "tokens" / "design-current.md").read_text("utf-8")
    (root / "DESIGN.md").write_text(fixture, encoding="utf-8")
    brand = fixture.replace("name: fixture-current", "scope: user\nname: brand\ndescription: A second brand.", 1)
    brand = brand.replace("#102030", brand_primary)
    (root / "identity" / "designs").mkdir(parents=True)
    (root / "identity" / "designs" / "brand.md").write_text(brand, encoding="utf-8")
    (root / "workflow" / "contexts").mkdir(parents=True)
    (root / "workflow" / "contexts" / "client.yaml").write_text("id: client\ndesign_ref: brand\n", encoding="utf-8")
    return root
