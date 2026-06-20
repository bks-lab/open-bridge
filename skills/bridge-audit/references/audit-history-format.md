---
summary: "JSON schema and write rules for work/_learning/audit-history/*.json — the Phase 3 persistence layer of /bridge-audit findings."
type: reference
last_updated: 2026-05-13
---

# Audit-History JSON Format

`/bridge-audit` writes one JSON per run to
`work/_learning/audit-history/<YYYY-MM-DD-HHMM>.json` when
`bridge-config.yaml.learning.enabled` is true and `--no-history` is not set.

## File-naming

```
work/_learning/audit-history/2026-05-13-1530.json
                              YYYY  MM  DD HHMM
```

UTC time. Two writes in the same minute (rare) append `-2`, `-3` suffix:
`2026-05-13-1530-2.json`.

## Full JSON schema

```json
{
  "ran_at": "2026-05-13T15:30:00Z",
  "repo": "the-bridge",
  "branch": "user/<name>",
  "args": ["--check", "all"],
  "duration_ms": 4321,
  "checks": {
    "<check_name>": {
      "ran": true,
      "skipped": false,
      "skip_reason": null,
      "p0": 0, "p1": 2, "p2": 1, "p3": 0,
      "findings": [
        {
          "id": "<check_name>/<short-slug>/<seq>",
          "severity": "P1",
          "fingerprint": "sha256:abc123...",
          "target_path": "README.md",
          "target_line": 142,
          "summary": "README lists 'voice-clone' skill but skills/voice-clone/ does not exist",
          "details": "Full prose of finding with surrounding context.",
          "suggested_fix": {
            "type": "edit",
            "target": "README.md",
            "diff": "..."
          },
          "auto_fixable": false
        }
      ]
    }
  },
  "totals": {
    "p0": 0,
    "p1": 2,
    "p2": 1,
    "p3": 0,
    "total": 3
  },
  "recurring_detected": [
    {
      "fingerprint": "sha256:abc123...",
      "first_seen": "2026-05-03T08:00:00Z",
      "consecutive_runs": 4,
      "proposal_id": "2026-05-13-audit-recurring-abc12345"
    }
  ]
}
```

## Field definitions

| Field | Type | Description |
|---|---|---|
| `ran_at` | ISO 8601 UTC | When the audit started |
| `repo` | string | Repo name (e.g. `the-bridge`, `<your-bridge>`, `open-bridge`) |
| `branch` | string | Git branch at run-time |
| `args` | array | CLI args passed (for replay/debug) |
| `duration_ms` | integer | Wall-clock duration of the audit |
| `checks` | object | One key per check (license, skill-tree, …) |
| `checks.<name>.ran` | bool | True if check executed (false if --check filter excluded it) |
| `checks.<name>.skipped` | bool | True if check was attempted but skipped (e.g. missing data file) |
| `checks.<name>.skip_reason` | string\|null | Why skipped |
| `checks.<name>.p<0-3>` | integer | Count of findings at that severity |
| `checks.<name>.findings` | array | One object per finding |
| `findings[].id` | string | Stable-ish within run; format `<check>/<slug>/<seq>` |
| `findings[].severity` | enum P0-P3 | Severity from the check's rule |
| `findings[].fingerprint` | string | SHA-256 (see § Fingerprint) — stable across runs |
| `findings[].target_path` | string | Repo-relative path the finding refers to |
| `findings[].target_line` | integer\|null | Optional line number |
| `findings[].summary` | string | Single-line human summary |
| `findings[].details` | string | Multi-line context/explanation |
| `findings[].suggested_fix` | object\|null | When the check can propose a fix |
| `findings[].auto_fixable` | bool | True if `--fix` would apply this without ambiguity |
| `totals` | object | Aggregated counts across all checks |
| `recurring_detected` | array | Findings present in ≥3 consecutive prior runs |

## Fingerprint computation

```python
import hashlib, re

def normalize_summary(s: str) -> str:
    s = s.lower()
    s = re.sub(r'\s+', ' ', s).strip()
    # Strip line numbers ±5 (so README.md:142 matches README.md:144)
    s = re.sub(r':\d+', ':NUM', s)
    # Strip ISO timestamps
    s = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:?\d{2})?', 'TS', s)
    return s

def fingerprint(check_name: str, target_path: str, summary: str) -> str:
    payload = f"{check_name}\n{target_path}\n{normalize_summary(summary)}"
    return "sha256:" + hashlib.sha256(payload.encode('utf-8')).hexdigest()
```

The fingerprint is intentionally lossy — small wording changes don't break it.
But it IS sensitive to `check_name` + `target_path`, so a real shift in either
produces a new fingerprint (correctly).

## Recurring-detection algorithm

After writing the current run's JSON, look back:

```python
import json
from pathlib import Path
from collections import defaultdict

history = sorted(Path('work/_learning/audit-history').glob('*.json'),
                 reverse=True)[:10]  # last 10 runs, newest first

# Build fingerprint -> [run_timestamps in order from newest to oldest]
fp_to_runs = defaultdict(list)
for h in history:
    data = json.loads(h.read_text())
    seen_in_this_run = set()
    for check_name, check_data in data['checks'].items():
        for f in check_data.get('findings', []):
            fp = f['fingerprint']
            if fp not in seen_in_this_run:  # dedupe within run
                fp_to_runs[fp].append(data['ran_at'])
                seen_in_this_run.add(fp)

# Find fingerprints with ≥3 consecutive most-recent runs
recurring = []
for fp, runs in fp_to_runs.items():
    # runs is newest-first; check that the streak from index 0 is ≥3
    streak = 1
    for i in range(1, len(runs)):
        if i < 3:  # only count if it's in the most-recent 3 runs
            streak += 1
        else:
            break
    if streak >= 3:
        recurring.append({
            'fingerprint': fp,
            'first_seen': runs[-1],   # oldest in the streak
            'consecutive_runs': streak,
        })
```

Then for each `recurring` entry: check if a proposal already exists with
matching `source.fingerprint`, and write one if not (see SKILL.md §
Recurring-findings auto-proposal).

## Retention

- Default: keep all JSON files indefinitely (~2-10KB each, ~1-3MB/year).
- If `work/_learning/audit-history/` exceeds 365 files OR 50MB:
  - Roll up files older than 90 days into monthly aggregates
    (`<YYYY-MM>-monthly.json`)
  - Per-month aggregate keeps: `min`, `max`, `median` counts per severity,
    plus list of fingerprints seen with `first_seen` / `last_seen` dates.
  - Original per-run JSONs in that month deleted post-rollup.

Roll-up is a maintenance task, not real-time. Run manually with
`/bridge-audit history rollup` (future).

## Read access

The audit-history is read by:

- `/bridge-learn trends` — surfaces recurring findings and per-check severity
  evolution
- `/bridge-audit` itself — when checking for recurring patterns in current run
- `bridge-dashboard` (optional, Phase 4) — could chart severity-over-time

Files are JSON for stable parsing. **Do not modify by hand** — append-only
from `/bridge-audit`.

## Privacy / Scope

- USER scope (per work/_learning/README.md).
- `.gitignore`'d for OSS variants (open-bridge, your org overlay).
- The personal/seed Bridge instance keeps everything for full trend analysis.

## Example: minimal valid file

```json
{
  "ran_at": "2026-05-13T15:30:00Z",
  "repo": "the-bridge",
  "branch": "user/<name>",
  "args": [],
  "duration_ms": 1234,
  "checks": {
    "license": {"ran": true, "skipped": false, "skip_reason": null,
                "p0": 0, "p1": 0, "p2": 0, "p3": 0, "findings": []},
    "skill-tree": {"ran": true, "skipped": false, "skip_reason": null,
                   "p0": 0, "p1": 0, "p2": 0, "p3": 0, "findings": []}
  },
  "totals": {"p0": 0, "p1": 0, "p2": 0, "p3": 0, "total": 0},
  "recurring_detected": []
}
```

A "clean" run still writes the file — it's how /bridge-learn trends can
see "trend going down".
