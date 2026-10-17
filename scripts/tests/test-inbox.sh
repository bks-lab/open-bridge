#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Thin wrapper for the inbox pytest suites: the inbox itself, the agent approver
# that files held answers into it, the workplace plan and the task.py STATUS.md
# writes it launches with, the briefing advice and the briefing profiles with
# their tracker adapters, the briefing view and its dashboard pages, the
# activity and commits sections, and the upstream rows.
#
# Run: bash scripts/tests/test-inbox.sh   (from repo root; non-zero on failure)
set -u
cd "$(dirname "$0")/../.."

exec python3 -m pytest -q scripts/tests/test_inbox.py scripts/tests/test_inbox_approve.py scripts/tests/test_inbox_mute.py \
    scripts/tests/test_workplace.py scripts/tests/test_task.py scripts/tests/test_task_review.py \
    skills/briefing/tests/test_advise.py \
    scripts/tests/test_briefing.py scripts/tests/test_briefing_providers.py \
    scripts/tests/test_briefing_view.py scripts/tests/test_briefing_activity.py \
    scripts/tests/test_briefing_pages.py skills/briefing/tests/test_upstream_items.py
