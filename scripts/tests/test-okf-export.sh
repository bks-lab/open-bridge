#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Thin wrapper for the scripts/okf-export.py pytest suite.
#
# Run: bash scripts/tests/test-okf-export.sh   (from repo root; non-zero on failure)
set -u
cd "$(dirname "$0")/../.."

exec python3 -m pytest scripts/tests/test_okf_export.py -q
