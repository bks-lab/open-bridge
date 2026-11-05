# SPDX-License-Identifier: MIT
"""The usage panel of render-motd.sh shows the weekly limit and nothing else.

The usage endpoint answers `five_hour: null` since the five-hour window went away.
A reset timestamp that lands in a percentage aborts the greeting in bash arithmetic,
so the panel reads the fields it shows and no more.
"""
import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render-motd.sh"

RESET = "2026-11-02T02:00:00.149649+00:00"


def render(tmp_path, payload):
    """Run show_claude_usage alone against a cache file holding `payload`."""
    cache = tmp_path / "claude.cache"
    cache.write_text(json.dumps(payload), encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("show_claude_usage() {")
    end = source.index("\n}\n", start) + 3
    harness = (
        f"CLAUDE_CACHE={cache}\n"
        "RESET=; DIM=; BOLD=; RED=; BRAND_PRIMARY=; BRAND_ACCENT=\n"
        "anim_sleep() { :; }\n"
        "draw_hline() { :; }\n"
        + source[start:end]
        + "show_claude_usage\n"
        "echo finished\n"
    )
    return subprocess.run(
        ["/bin/bash", "-c", harness], capture_output=True, text=True, check=False
    )


def test_a_response_without_a_five_hour_window_renders_whole(tmp_path):
    result = render(
        tmp_path,
        {"five_hour": None, "seven_day": {"utilization": 75.0, "resets_at": RESET}},
    )
    assert result.stderr == ""
    assert "75%" in result.stdout
    assert "Resets" in result.stdout
    assert "└" in result.stdout
    assert "finished" in result.stdout


def test_a_five_hour_window_in_the_response_is_not_shown(tmp_path):
    result = render(
        tmp_path,
        {
            "five_hour": {"utilization": 12.0},
            "seven_day": {"utilization": 75.0, "resets_at": RESET},
        },
    )
    assert result.stderr == ""
    assert "5h window" not in result.stdout
    assert "Resets" in result.stdout
