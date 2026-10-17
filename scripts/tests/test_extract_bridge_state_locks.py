"""A reader that runs every minute must never take the index lock.

THE SCAR, measured on a live instance. Committing this repository failed repeatedly with
`Unable to create '.git/index.lock': File exists`, while no git process was
running and the lock file was already gone by the time it was looked for. The
cause was a state-pusher launchd job on a sixty second
interval whose script calls `scripts/extract-bridge-state.py`, which reads the
repository with a dozen git commands.

Several read-only-looking git commands refresh the on-disk index as a side
effect and take `index.lock` to do it. That is correct behaviour and harmless
between two humans; between a per-minute background reader and someone typing
`git commit`, it is a collision every minute, reported as an error that names a
process which no longer exists by the time anyone looks.

`--no-optional-locks` is git's own answer: the command still answers, it simply
declines the refresh it does not need. A background READER never needs it.

The test asserts the flag is on every invocation rather than on the ones known
to refresh today, because which subcommands refresh is a git implementation
detail that has changed before and would change under us silently.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "scripts" / "extract-bridge-state.py"


class EveryGitCallDeclinesTheOptionalLock(unittest.TestCase):

    def setUp(self):
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} is gone")
        self.src = SCRIPT.read_text(encoding="utf-8")
        self.tree = ast.parse(self.src)

    def git_lists(self):
        """Every list literal whose first element is the string "git"."""
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value == "git":
                yield node

    def test_the_script_still_shells_out_to_git(self):
        # If this ever fails, the rest of the file is asserting nothing.
        self.assertGreater(len(list(self.git_lists())), 0,
                           "no git invocation found; this contract has lost "
                           "its subject and must be rewritten or deleted")

    def test_no_git_invocation_may_refresh_the_index(self):
        offenders = []
        for node in self.git_lists():
            args = [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if "--no-optional-locks" not in args:
                offenders.append((node.lineno, " ".join(args)))
        self.assertEqual(
            offenders, [],
            "git invocations that may take .git/index.lock while somebody is "
            "committing:\n" + "\n".join(f"  line {n}: {a}" for n, a in offenders))

    def test_the_flag_comes_before_the_subcommand(self):
        # `--no-optional-locks` is a git-level option. After the subcommand it
        # is an argument TO the subcommand, and most of them reject it.
        for node in self.git_lists():
            args = [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if "--no-optional-locks" not in args:
                continue
            i = args.index("--no-optional-locks")
            self.assertEqual(
                i, 1,
                f"line {node.lineno}: the flag sits at position {i} in "
                f"{' '.join(args)}; git parses it only before the subcommand")


if __name__ == "__main__":
    unittest.main()
