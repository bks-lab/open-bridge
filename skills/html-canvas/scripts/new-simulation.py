#!/usr/bin/env python3
"""Assemble a single-file html-canvas SIMULATION from the bundled parts.

    python3 skills/html-canvas/scripts/new-simulation.py \
        --archetype flow --lang de \
        --title "One report through the run" \
        --out work/tasks/<slug>/deliverables/run.html

Takes assets/shell.html (tokens, theme toggle, DE/EN toggle, print),
assets/simulation.css (the visual layer), assets/sim-engine.js (clock, controls,
feed) and one archetype fragment, and splices them into ONE offline file with no
external dependencies. That is the point: the parts stay single sources of truth
here, and every deliverable is still a self-contained page.

Then edit the MODEL block near the top of the deliverable's script. Geometry,
the item list, the durations and the text dictionary are the whole surface a new
domain has to touch.

Every splice asserts its anchor. A quietly missed anchor would produce a page
without an engine, and the failure would only show when somebody opens it.
"""

import argparse
import datetime
import pathlib
import re
import sys
from typing import NoReturn

HERE = pathlib.Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"


def load_design_to_css():
    """design-to-css.py has a hyphen in its name, so it is loaded by path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("design_to_css", HERE / "design-to-css.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def default_design(design=None):
    """The design the Bridge resolves (bridge_design.py), else the instance's DESIGN.md.

    A simulation is written for the instance, so no target repository is asked;
    --design (a path or an id) wins, then the theme's design, then the root file.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("bridge_design", HERE / "bridge_design.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        found = mod.resolve(design)
    except ValueError as e:
        fail(str(e))
    return found or HERE.parents[2] / "DESIGN.md"

ARCHETYPES = {
    "flow": (
        "sim-flow.html",
        "tokens travel a drawn route through stations with queues, a gate and outcomes",
    ),
    "worklist": (
        "sim-worklist.html",
        "a fixed plan executed step by step, protocol plus state strip, no geometry",
    ),
}

# The shell defaults to English. Flipping the default language means flipping
# this exact block, so it is matched literally and the script fails loudly if the
# shell ever changes it.
LANG_BLOCK_EN = """:root:not([data-lang="de"]) [data-de]:not([data-en]){display:none}
:root[data-lang="de"] [data-en]:not([data-de]){display:none}"""

LANG_BLOCK_DE = """:root:not([data-lang="en"]) [data-en]:not([data-de]){display:none}
:root[data-lang="en"] [data-de]:not([data-en]){display:none}"""


def fail(msg) -> NoReturn:
    sys.stderr.write("new-simulation: %s\n" % msg)
    sys.exit(1)


def read(path):
    if not path.exists():
        fail("missing bundled file: %s" % path)
    return path.read_text(encoding="utf-8")


def split_fragment(text, path):
    """Split an archetype fragment into its style / markup / script parts."""
    parts = {}
    for name in ("style", "markup", "script"):
        marker = "<!--@%s-->" % name
        if marker not in text:
            fail("fragment %s has no %s marker" % (path.name, marker))
    _, rest = text.split("<!--@style-->", 1)
    parts["style"], rest = rest.split("<!--@markup-->", 1)
    parts["markup"], parts["script"] = rest.split("<!--@script-->", 1)
    return {k: v.strip("\n") for k, v in parts.items()}


def replace_once(text, needle, repl, what):
    n = text.count(needle)
    if n != 1:
        fail("expected exactly one %s anchor in the shell, found %d" % (what, n))
    return text.replace(needle, repl, 1)


def build(args):
    shell = read(ASSETS / "shell.html")
    sim_css = read(ASSETS / "simulation.css")
    engine = read(ASSETS / "sim-engine.js")
    frag_name = ARCHETYPES[args.archetype][0]
    frag = split_fragment(read(ASSETS / frag_name), ASSETS / frag_name)

    title_de = args.title_de or args.title
    title_en = args.title_en or args.title
    date = args.date or datetime.date.today().isoformat()
    source = args.source or ("html-canvas / %s" % args.archetype)

    out = shell

    # 0. brand tokens from the instance's DESIGN.md, into the shell's marked region.
    #    Without a DESIGN.md the shell keeps its neutral system colours, loudly.
    design = pathlib.Path(default_design(args.design))
    if design.exists():
        d2c = load_design_to_css()
        css, skipped = d2c.build_css(d2c.frontmatter(design))
        try:
            out = d2c.inject(out, css)
        except ValueError as e:
            fail(str(e))
        if skipped:
            sys.stderr.write("new-simulation: DESIGN.md keys not mapped: %s\n" % ", ".join(skipped))
    else:
        sys.stderr.write("new-simulation: no DESIGN.md at %s, page keeps neutral system colours\n" % design)

    # 0b. fonts, opt in: a simulation runs inside a stage or is sent alone, where no
    #     page around it carries the brand's faces (same region as new-page.py).
    fonts = ""
    if args.embed_fonts:
        if not design.exists():
            fail("--embed-fonts needs a DESIGN.md (pass --design)")
        faces = load_design_to_css().font_faces(design, [pathlib.Path(d) for d in args.font_dir])
        if not faces:
            sys.stderr.write("new-simulation: no font file found for the DESIGN.md families\n")
        fonts = "\n/* page-fonts:begin */\n" + faces.strip("\n") + "\n/* page-fonts:end */\n"

    # 1. default language
    if args.lang == "de":
        out = replace_once(out, '<html lang="en" class="">',
                           '<html lang="de" class="">', "html lang")
        out = replace_once(out, LANG_BLOCK_EN, LANG_BLOCK_DE, "language swap CSS")
        out = out.replace("|| 'en')", "|| 'de')")
        out = out.replace("'data-lang', 'en')", "'data-lang', 'de')")

    # 2. styles: the simulation layer, then whatever the archetype adds
    style_add = (
        fonts
        + "\n/* --- simulation layer (skills/html-canvas/assets/simulation.css) --- */\n"
        + sim_css.rstrip()
        + "\n\n/* --- page-specific (archetype: %s) --- */\n" % args.archetype
        + frag["style"].rstrip()
        + "\n"
    )
    out = replace_once(out, "\n</style>\n</head>", style_add + "</style>\n</head>", "head style close")

    # 3. main content
    main_new = (
        '<main class="wrap">\n\n'
        '  <h1><span data-de>%s</span><span data-en>%s</span></h1>\n\n'
        % (title_de, title_en)
    )
    if args.lead_de or args.lead_en:
        main_new += (
            '  <p class="lead" data-de>%s</p>\n  <p class="lead" data-en>%s</p>\n\n'
            % (args.lead_de or args.lead_en, args.lead_en or args.lead_de)
        )
    main_new += frag["markup"] + "\n\n</main>"

    m = re.search(r'<main class="wrap">.*?</main>', out, re.S)
    if not m:
        fail("no <main class=\"wrap\"> ... </main> block in the shell")
    out = out[: m.start()] + main_new + out[m.end():]

    # 4. engine + model, before </body>
    script_add = (
        "\n<!-- simulation engine (skills/html-canvas/assets/sim-engine.js) -->\n"
        "<script>\n" + engine.rstrip() + "\n</script>\n\n"
        "<!-- model + stage (archetype: %s) -->\n" % args.archetype
        + "<script>\n(function () {\n  'use strict';\n"
        + frag["script"].rstrip()
        + "\n})();\n</script>\n"
    )
    out = replace_once(out, "</body>", script_add + "</body>", "body close")

    # 5. title + footer placeholders
    out = out.replace("{{TITLE}}", title_en if args.lang == "en" else title_de)
    out = out.replace("{{DATE}}", date).replace("{{SOURCE_PATH}}", source)

    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        fail("unfilled placeholders left in the output: %s" % ", ".join(sorted(set(left))))

    return out


def verify(text, archetype):
    """Cheap post-conditions. A splice that silently did nothing is the failure
    mode worth guarding: the page still opens, it just never runs."""
    checks = [
        ("engine present", "global.Sim = {" in text),
        ("simulation layer present", ".sim-feed__row" in text),
        ("model present", "new Sim.Clock(" in text),
        ("controls wired", "data-sim-run" in text),
        ("no fragment markers", "<!--@" not in text),
        ("reduced-motion note present", "data-sim-reduced-note" in text),
        ("provenance block present", "sim-prov-card" in text),
        ("token region intact", text.count("/* design-tokens:begin */") == 1),
    ]
    bad = [name for name, ok in checks if not ok]
    if bad:
        fail("assembled %s file failed its own checks: %s" % (archetype, ", ".join(bad)))
    return len(checks)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--archetype", choices=sorted(ARCHETYPES), help="which running model to start from")
    p.add_argument("--out", help="path of the single-file deliverable to write")
    p.add_argument("--title", default="Simulation", help="title, used for both languages unless overridden")
    p.add_argument("--title-de", dest="title_de")
    p.add_argument("--title-en", dest="title_en")
    p.add_argument("--lead-de", dest="lead_de")
    p.add_argument("--lead-en", dest="lead_en")
    p.add_argument("--lang", choices=("de", "en"), default="en", help="default language of the page")
    p.add_argument("--date", help="footer date (default: today)")
    p.add_argument("--design", help="DESIGN.md or design id to take the tokens from "
                                    "(default: the design the Bridge resolves, else the instance root)")
    p.add_argument("--source", help="footer source note")
    p.add_argument("--embed-fonts", action="store_true",
                   help="embed the DESIGN.md font families as base64 @font-face (off by default; "
                        "for a simulation in a slide stage or sent on its own)")
    p.add_argument("--font-dir", action="append", default=[], metavar="DIR",
                   help="with --embed-fonts: extra directory of <family>-latin-<weight>.woff2 files")
    p.add_argument("--list", action="store_true", help="list the archetypes and exit")
    p.add_argument("--force", action="store_true", help="overwrite an existing output file")
    args = p.parse_args()
    if args.font_dir and not args.embed_fonts:
        p.error("--font-dir needs --embed-fonts")

    if args.list or not args.archetype:
        print("archetypes:")
        for name in sorted(ARCHETYPES):
            print("  %-9s %s" % (name, ARCHETYPES[name][1]))
        if not args.list:
            print("\nPick one with --archetype, and give --out.")
        return 0

    if not args.out:
        fail("--out is required")
    dest = pathlib.Path(args.out)
    if dest.exists() and not args.force:
        fail("%s exists; pass --force to overwrite" % dest)

    text = build(args)
    n = verify(text, args.archetype)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print("wrote %s (%d bytes, %s, default lang %s, %d checks passed)"
          % (dest, len(text.encode("utf-8")), args.archetype, args.lang, n))
    print("next: open it, then edit the MODEL block near the top of the last <script>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
