# SPDX-License-Identifier: MIT
"""The backups template names the state sidecar where instances keep it.

The defect this pins: `infra/backups/_template.yaml` said
`state_file: backups/_state.yaml`, a path from before the cluster wrappers.
Both examples use `infra/backups/_state.yaml`, and an instance copied from the
template got a reference `check-edges.py` reports as moved.

Run: python3 -m pytest scripts/tests/test_backups_template.py -q
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WHERE = "infra/backups/_state.yaml"


def _docs(rel: str) -> dict:
    docs = [d for d in yaml.safe_load_all((REPO / rel).read_text(encoding="utf-8")) if d]
    return docs[0]


def test_the_template_names_the_sidecar_beside_it():
    assert _docs("infra/backups/_template.yaml")["state_file"] == WHERE


def test_every_example_agrees_with_the_template():
    for topology in sorted(REPO.glob("examples/*/infra/backups/topology.yaml")):
        assert _docs(str(topology.relative_to(REPO)))["state_file"] == WHERE, topology


def test_the_schema_states_the_same_default():
    text = (REPO / "infra/backups/_schema.yaml").read_text(encoding="utf-8")
    assert f"default: {WHERE}" in text
