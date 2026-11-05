#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""No markdown link may point at this repo's root CLAUDE.md.

The operating manual is AGENTS.md. A root CLAUDE.md is not part of the layout
(when present, Claude Code loads only it and AGENTS.md disappears), so a
markdown link to it is a dangling route in CORE. Examples keep their own demo
CLAUDE.md and are exempt, as are the changelog and closed work.
"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ClaudeMdLinks(unittest.TestCase):
    def test_no_link_to_claude_md(self):
        r = subprocess.run(
            ["git", "grep", "-nE", r"\]\((\.\./)*CLAUDE\.md", "--", ".",
             ":!examples", ":!CHANGELOG.md", ":!work/done"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, f"links to CLAUDE.md remain:\n{r.stdout}")
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
