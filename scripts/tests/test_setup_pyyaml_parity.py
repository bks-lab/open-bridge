"""Both setup scripts treat a missing PyYAML as an error, not a silent pass.

bin/setup checks `import yaml` and sets rc=1. The Windows script has no shell
to run here, so this is a static parity check: the same probe, and a failure
path that clears $ok, must be present in bin/setup.ps1.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_bash_setup_checks_pyyaml() -> None:
    text = (ROOT / "bin" / "setup").read_text(encoding="utf-8")
    assert 'python3 -c "import yaml"' in text
    assert "ERR PyYAML missing" in text


def test_windows_setup_checks_pyyaml_and_fails_without_it() -> None:
    text = (ROOT / "bin" / "setup.ps1").read_text(encoding="utf-8")
    probe = re.search(r'-c "import yaml"', text)
    assert probe, "setup.ps1 never probes for PyYAML"
    block = text[probe.start():probe.start() + 600]
    assert "ERR  PyYAML missing" in block
    assert "$ok = $false" in block, "a missing PyYAML must fail the setup run"
