#!/bin/bash
# Hermetic tests for the inbox-notify skill: a fake signal-cli on PATH, no message leaves the machine.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 -m pytest skills/inbox-notify/tests -q -rs "$@"
