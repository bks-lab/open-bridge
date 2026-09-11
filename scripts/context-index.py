#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Print the index of a declared map source, or one block out of it.

    python3 scripts/context-index.py ecosystem.yaml
    python3 scripts/context-index.py ecosystem.yaml --get customers.example
    python3 scripts/context-index.py ecosystem.yaml --list

The card that stays resident, and the body that arrives when somebody names
it. Same split skills have always had; this is the half a registry never got.
The shape of the card is declared once, next to the size ceiling it has to
respect, in `context-budget.yaml` under the item's `card:` block. A file with
no declaration is still indexed, from its own shape.

Mechanics and the reasoning behind them: `scripts/lib/context_index.py`.
Contract: `scripts/tests/test_context_index.py`.
"""

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _lib():
    """Import scripts/lib/context_index.py by path — `scripts/` is not a package.

    Loading the module through `compile`/`exec` rather than adding `scripts/`
    to `sys.path` keeps this from writing a `__pycache__` into a tracked
    directory, which a guardrail elsewhere in this repo treats as a finding.
    """
    spec = importlib.util.spec_from_file_location(
        "context_index", HERE / "lib" / "context_index.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(ci, root: Path, only: str | None) -> int:
    """Run every guard over every declared card, and say what it found.

    Wired into CI on purpose. A guard that exists as a library function and is
    called by nothing is the failure this repo has already paid for once: a
    551-line regression suite that ran in no job and proved nothing while it
    sat there looking like proof.
    """
    cards = ci.declared_cards(root)
    if only:
        cards = {only: cards.get(only)}

    findings: list[str] = []
    skipped: list[str] = []
    for rel, card in cards.items():
        target = root / rel
        if not target.is_file():
            # Instance data, absent in a fresh clone. Declared-and-absent is
            # the budget's business, not this guard's, so the skip stays. What
            # does not stay is counting it: a card nothing was read from has
            # not checked out, it was never looked at. It is named below
            # instead, because a skip folded into the green line is how an
            # absent source hides from the guard that exists to look at it.
            skipped.append(rel)
            continue
        text = target.read_text(encoding="utf-8")
        for finding in (
            ci.check_declaration(text, card)
            + ci.check_structure(text)
            + ci.check_round_trip(text, card)
            + ci.check_coverage(text, rendered=ci.render_card(text, card, rel))
        ):
            findings.append(f"{rel}: {finding}")

    for finding in findings:
        print(finding, file=sys.stderr)
    if findings:
        print(f"context-index: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"context-index: {len(cards) - len(skipped)} declared card(s) check out")
    if skipped:
        print(
            f"context-index: {len(skipped)} card(s) NOT checked, source absent: "
            + ", ".join(sorted(skipped))
        )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "path", nargs="?", help="repo-relative path of the source file"
    )
    parser.add_argument("--get", metavar="DOTTED", help="print one block verbatim")
    parser.add_argument(
        "--list", action="store_true", help="print every path --get accepts"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify every declared card against its source; non-zero on findings",
    )
    parser.add_argument("--repo-root", default=str(HERE.parent))
    args = parser.parse_args(argv)

    ci = _lib()

    # Without PyYAML every label renders as "(no label)" and this exits 0. The
    # label IS the routing signal: a name with no description says something
    # exists and nothing about whether it is the one you want. A degraded card
    # is worse than no card, because no card sends you to the file. Refuse.
    if ci.yaml is None:
        sys.exit(
            "error: PyYAML is not importable, so labels cannot be read and every\n"
            "       entry would render as '(no label)'. Install it rather than\n"
            "       accept a card that lists names and routes nowhere."
        )

    root = Path(args.repo_root)

    if args.check:
        return _check(ci, root, args.path)

    if not args.path:
        parser.error("a path is required unless --check is given")
    target = root / args.path

    # A registry is instance data, and absent is the normal state of a fresh
    # clone. Failing here would fail every session that has not onboarded yet,
    # which is the opposite of what a progressive-disclosure feature is for.
    if not target.is_file():
        return 0

    text = target.read_text(encoding="utf-8")
    card = ci.card_for(root, args.path)

    if args.list:
        for path in ci.addressable(text, card):
            print(path)
        return 0

    if args.get:
        block = ci.slice_block(text, args.get)
        if not block.strip():
            available = ci.addressable(text, card)
            head = args.get.split(".")[0]
            near = [p for p in available if p.startswith(head)] or available
            print(f"error: no block at '{args.get}' in {args.path}", file=sys.stderr)
            print("available: " + ", ".join(near), file=sys.stderr)
            return 2
        sys.stdout.write(block)
        return 0

    sys.stdout.write(ci.render_card(text, card, args.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
