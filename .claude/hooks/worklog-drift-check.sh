#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Compatibility entry point; both clients use the shared implementation.
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec bash "$root/scripts/worklog-drift-check.sh"
