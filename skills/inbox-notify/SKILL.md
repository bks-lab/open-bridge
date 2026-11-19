---
name: inbox-notify
description: >-
  Puts an inbox item that needs a person now on that person's phone as a Signal
  poll whose options are the item's own actions, and executes the vote through
  the inbox. Config in infra/channels/<slug>.yaml, runs as a declared workload.
  Trigger: "/inbox-notify", "notify me about approvals", "held answer on my
  phone", "approve from Signal", "inbox poll", "the approval never reached me".
metadata:
  scope: core
allowed-tools:
  - Bash(python3:*)
  - Bash(bash:*)
  - Read
  - Grep
  - Glob
---

# Inbox notify

The inbox holds what needs a person ([`docs/inbox.md`](../../docs/inbox.md)). Nothing in
it rings. A held answer of a Bridge-Agent, filed by `scripts/inbox-approve.py` with
urgency `now` and the actions `approve` and `reject`, waited unseen until it expired.
This skill is the generic notifier: one text and one poll per item, the poll's options
are the item's `actions`, the vote runs that verb, the result lands on the item.

The engine is `skills/inbox-notify/scripts/inbox_notify.py`. Nothing instance specific
lives in it: the channel comes from `infra/channels/<slug>.yaml`, the slug from
`inbox.notify_via` in `bridge-config.yaml`, the cadence from the workload declaration.
Read the referenced file ONLY when the branch below sends you there.

## Commands

```
python3 skills/inbox-notify/scripts/inbox_notify.py [--channel SLUG] tick [--dry-run] [--all]
python3 skills/inbox-notify/scripts/inbox_notify.py [--channel SLUG] test
python3 skills/inbox-notify/scripts/inbox_notify.py [--channel SLUG] show
```

| Command | Does |
|---|---|
| `tick` | announce every open item that needs a person now and has no poll yet; read the channel; run each vote (`approve`, `reject`, `drop`, `close`, `defer`); terminate the poll of an item decided elsewhere. The workload runs this every two minutes |
| `tick --dry-run` | print the texts and polls a tick would send; send nothing, read nothing, note nothing |
| `tick --all` | announce already announced items again (a new poll), after a lost phone or a changed recipient |
| `test` | one test text and one two-option test poll to the recipient, to prove the channel before the workload exists |
| `show` | the resolved configuration, handles included (they are handles, not secrets) |

Exit `0` after a tick, `2` on a config or usage problem before anything was sent, `1` when
the transport failed.

## Three invariants

1. **One announcement per item.** The poll's timestamp goes onto the item as a note
   (`notify poll <ts> <uuid> via <slug> options approve,reject`). That note is the only
   state: it keeps a second tick from announcing again and maps a vote back to its item.
   An item decided through the poll is noted `notify decided <verb> via <slug>`; one
   decided elsewhere has its poll terminated and is noted `notify closed-elsewhere`.
2. **One reader per account.** `signal-cli receive` consumes. Nothing else may run it on
   this account, or it swallows the votes. The tick holds a lock and the workload runs
   `single_flight: true`; a tick that finds the lock exits `0` and says so.
3. **One voter.** Only a vote from the recipient the poll was sent to counts (its uuid is
   in the note). Anyone else's vote, a vote on an unknown poll, a withdrawn vote and a
   vote on an item already decided do nothing but log a line.

## Decision tree

```
What does the user want?
├── "Tell me on my phone when an answer waits"   → references/setup.md (channel file, test, workload)
├── "The approval never reached me"               → `tick --dry-run` shows what is due; `show` the config;
│                                                   is the workload running? (`/workload reconcile`);
│                                                   does anything else run `receive` on the account?
├── Other wording, other language on the phone    → notify.labels and notify.texts in the channel file
├── Ring for more than held answers               → notify.urgencies / notify.sources in the channel file
├── A second transport (Telegram, Matrix, …)      → one class next to SignalCli in the engine; the
│                                                   contract is send_text, send_poll, terminate_poll, receive
└── What the phone shows and why                  → this file § Three invariants; docs/inbox.md § actions
```

## Files

| File | Holds |
|---|---|
| `scripts/inbox_notify.py` | the engine: selection, texts, the signal-cli transport, vote execution |
| `assets/channel.yaml` | the channel file to copy to `infra/channels/<slug>.yaml` |
| `assets/workload.yaml` | the declaration to copy to `workflow/workloads/inbox-notify.yaml` |
| `references/setup.md` | setting it up on one machine, step by step, and the trap list |
| `tests/test_inbox_notify.py` | hermetic tests with a fake `signal-cli`, `bash skills/inbox-notify/run-tests.sh` |

## Related

- [`docs/inbox.md`](../../docs/inbox.md) § What a person can do: `actions` and `expires_at`, which this skill renders
- [`scripts/inbox-approve.py`](../../scripts/inbox-approve.py): files the held answers this skill most often announces; note that it maps `close` to reject
- [`skills/workload/SKILL.md`](../workload/SKILL.md): provisions the tick as a declared run
- [`skills/channel/SKILL.md`](../channel/SKILL.md): inventory and health of the channel file
