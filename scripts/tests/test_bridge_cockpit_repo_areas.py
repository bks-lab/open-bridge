# SPDX-License-Identifier: MIT
"""An issue or a pull request without an area takes the workspace whose `repos:` match its repository.

workplace.workspaces may carry `repos:` (owner/repo globs). A row of the briefing that names a repository
(`ref: owner/repo#n`) and has no area of its own then stands in that workspace's area on the start page
and under its filter, aliases included; a row with an area keeps it, and no match leaves it without one.

Run: pytest -q scripts/tests/test_bridge_cockpit_repo_areas.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import model as m  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

SPACES = [
    {"name": "Lab", "aliases": ["L"], "repos": ["lab-org/*"]},
    {"name": "Shop", "repos": ["acme/shop-*", " acme/site ", "", 3]},
    {"name": "Home", "default": True},
    {"name": "Junk", "repos": "lab-org/*"},
]


def test_the_config_reads_repos_as_globs_per_workspace(tmp_path):
    cfg = load_web_config(tmp_path, {"workplace": {"workspaces": SPACES}})
    assert cfg.area_repos == (("Lab", ("L",), ("lab-org/*",)), ("Shop", (), ("acme/shop-*", "acme/site")))
    assert load_web_config(tmp_path, {}).area_repos == ()


def row(ref, **over):
    return {"key": f"ref:{ref}", "ref": ref, "title": ref, "area": None, "area_names": [], **over}


def test_a_row_of_a_matching_repository_takes_that_area():
    rules = load_web_config(Path("."), {"workplace": {"workspaces": SPACES}}).area_repos
    view = {"buckets": [{"id": "now", "rows": [
        row("lab-org/engine#12"),
        row("acme/shop-api#3"),
        row("acme/site#9"),
        row("other/thing#1"),
        row("lab-org/engine#13", area="Shop", area_names=["Shop"]),
        {"key": "inbox:x", "ref": None, "title": "x", "area": None, "area_names": []},
    ]}]}
    out = m.with_repo_areas(view, rules)
    got = [(r["area"], r["area_names"]) for r in out["buckets"][0]["rows"]]
    assert got == [("Lab", ["Lab", "L"]), ("Shop", ["Shop"]), ("Shop", ["Shop"]), (None, []), ("Shop", ["Shop"]), (None, [])]
    # pure: the view handed in stays as it was, and no rules change nothing
    assert view["buckets"][0]["rows"][0]["area"] is None
    assert m.with_repo_areas(view, ()) == view


def test_aliases_are_read_only_as_a_list_of_names(tmp_path):
    spaces = [
        {"name": "Lab", "aliases": "L", "repos": ["lab-org/*"]},
        {"name": "Shop", "aliases": [3, True, "", " Store "], "repos": ["acme/*"]},
        {"name": "Home", "aliases": 7},
        {"name": "Desk", "aliases": [" Bench "]},
    ]
    cfg = load_web_config(tmp_path, {"workplace": {"workspaces": spaces}})
    assert cfg.area_repos == (("Lab", (), ("lab-org/*",)), ("Shop", ("Store",), ("acme/*",)))
    # every alias of every workspace, for the page to fold a tab's or a row's name into its area
    assert cfg.area_aliases == (("Store", "Shop"), ("Bench", "Desk"))
