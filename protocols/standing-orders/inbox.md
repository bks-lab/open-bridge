---
name: inbox
scope: always
enforcement: advisory
applies_to: []   # empty = every dispatched sub-agent
load: eager   # fires without its own vocabulary: an open thing is left in a log sentence unasked, or not at all
fires_unprompted: true   # --check refuses on-trigger for this order
---
# Inbox

Anything still open at the end of a unit of work goes into the inbox, not into a sentence in `work/log.md`.

## Rules

- Needs a person, waits on someone, or must be checked later: file it with `python3 scripts/inbox.py add`.
- Give it a `closes_when` wherever the live source can tell (PR merged, issue closed, file present, task status). Without one it stays open until a person closes it.
- Use `--key` for a finding that can fire again, so it stays one item.
- Before reporting anything as open, run `python3 scripts/inbox.py check` and read `python3 scripts/inbox.py list`. The log says what was needed, never whether it still is.
- Green stays quiet: file an item only when somebody has to act.
- `only-you` items (send, publish, pay) are never executed by the Bridge.

Model and CLI: [`docs/inbox.md`](../../docs/inbox.md).
