#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for scripts/check-site-links.py.

Two readings this pins down. A `<base href>` is not a link: the 404 page
carries one so its assets load at any depth, and it names the site root,
which is no file under docs/. And an anchor whose target is built at run
time from a shared data script (docs/assets/concepts-data.js) exists, even
though the id is not in the page's own text.

Run: python3 -m pytest scripts/tests/test_check_site_links.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("check_site_links", REPO / "scripts" / "check-site-links.py")
assert _spec and _spec.loader
csl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csl)


def run(tmp: pathlib.Path, files: dict[str, str], monkeypatch) -> int:
    for rel, text in files.items():
        p = tmp / "docs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    monkeypatch.setattr(csl, "DOCS", tmp / "docs")
    return csl.main()


def test_live_site_links_resolve():
    assert csl.main() == 0


def test_base_href_is_not_a_link(tmp_path, monkeypatch):
    files = {"index.html": "<p>home</p>", "404.html": '<base href="/open-bridge/"><a href="index.html">x</a>'}
    assert run(tmp_path, files, monkeypatch) == 0


def test_anchor_from_a_shared_data_script_counts(tmp_path, monkeypatch):
    files = {
        "assets/data.js": 'window.D = [{"id":"skills"}];',
        "a.html": '<script src="assets/data.js"></script>',
        "b.html": '<a href="a.html#skills">x</a>',
    }
    assert run(tmp_path, files, monkeypatch) == 0


def test_anchor_nowhere_still_fails(tmp_path, monkeypatch):
    files = {
        "assets/data.js": 'window.D = [{"id":"skills"}];',
        "a.html": '<script src="assets/data.js"></script>',
        "b.html": '<a href="a.html#nothing">x</a>',
    }
    assert run(tmp_path, files, monkeypatch) == 1
