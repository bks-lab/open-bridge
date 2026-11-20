# Setup: held answers on your phone, in six steps

Everything below runs on the machine that holds the inbox and the signal-cli account.
Replace `signal` with another slug if you want one, and use it in every step.

## 0. Prerequisites

- `signal-cli` 0.14.5 or newer on PATH, registered with its own number or linked as a
  secondary device (`signal-cli link`). Polls exist from 0.14.5; older versions reject
  `sendPollCreate`. The account should be a *separate* number or a linked device of the
  Bridge, never the person's own primary phone: the engine is this account's only reader.
- The recipient's Signal username (`u:name.12`) or number. A username is the better
  handle: it is not a phone number, so it may stand in a file.
- Python 3.10+ with PyYAML (the inbox needs it anyway).

## 1. Channel file

```bash
cp skills/inbox-notify/assets/channel.yaml infra/channels/signal.yaml
```

Fill `transport.account` (the signal-cli number) and `transport.recipient` (who votes).
Both are handles, not secrets; a channel file is USER tier and never promotes. If the
number must still stay out of git, write `file:///path/to/file` or `env://NAME` instead
and keep the value there (`chmod 600`).

Name the channel in `bridge-config.yaml`:

```yaml
inbox:
  notify_via: signal
```

## 2. Prove the channel

```bash
python3 skills/inbox-notify/scripts/inbox_notify.py test
```

One text and one two-option poll arrive on the phone. If the text arrives and the poll
does not, the signal-cli is older than 0.14.5 or the recipient handle is a group.
`sendPollCreate` takes `-u <name>` for a username; the engine does that translation.

## 3. See what a tick would send

```bash
python3 skills/inbox-notify/scripts/inbox_notify.py tick --dry-run
```

It lists every open item with urgency `now` and a non-empty `actions` list, with the text
and the poll options it would send. Nothing is sent. If the list is longer than you want
on your phone, narrow it in the channel file: `notify.sources: [agent-approval/]` rings
only for held answers of Bridge-Agents; `notify.urgencies` changes the urgency filter.

## 4. Declare the run

```bash
cp skills/inbox-notify/assets/workload.yaml workflow/workloads/inbox-notify.yaml
```

Replace `/usr/bin/python3` with the interpreter that has PyYAML (`python3 -c 'import yaml,
sys; print(sys.executable)'`) and `/path/to/bridge` with this checkout's absolute path. A
launchd unit expands nothing. Set the time zone. Then:

```bash
bash skills/workload/workload.sh validate inbox-notify --strict
bash skills/workload/workload.sh provision inbox-notify --yes --enable
```

The unit is `<label_prefix>.inbox-notify`; put that label into `runtime.service_label`
of the channel file so `/channel health` finds it. Flip the channel's `status` to `active`.

## 5. Let the approver kick it

A held answer is filed by `scripts/inbox-approve.py`. Two minutes is the normal latency
(the workload's `every_sec`). An approver that wants the phone to ring at once can run
`launchctl kickstart gui/$(id -u)/<label>` after filing; the a2a-bks org skill's
`approve.py` does that through `A2A_APPROVAL_WATCHER`.

## 6. Live test

File a test item and vote on the phone:

```bash
python3 scripts/inbox.py add --from agent-approval/test --kind draft --gate only-you --urgency now \
  --summary "Test: answer to test waits for your release" --detail $'Question:\nping?\n\nDrafted answer:\npong.' \
  --action approve --action reject --expires-at "$(date -v+1H +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || date -d '+1 hour' +%Y-%m-%dT%H:%M:%S%z)"
```

Within two minutes the phone shows the text and the poll. Vote. The next tick runs the
verb, terminates the poll, confirms with one line, and `python3 scripts/inbox.py show
<id>` lists the `approve` (or `reject`) event by `inbox-notify` and the two notes. Close
the test item afterwards.

## Traps

- **Two readers.** Anything else running `signal-cli receive` on this account (a shell,
  an older watcher, a daemon) eats the votes. One account, one reader. Retire the old
  one before provisioning this one.
- **close is reject.** `scripts/inbox-approve.py` maps a `close` event on a held answer to
  reject. "Mark done" in the cockpit on a held answer therefore rejects the answer. The
  poll offers the item's real verbs; use those.
- **The text arrives, the poll does not.** The next tick sends both again (twice beats
  never). If it keeps happening, run `test` and read the engine's log line.
- **`u:name` as a positional argument.** `send` accepts it, `sendPollCreate` does not
  ("No recipients given"). The engine passes `-u name`; a hand-written script must too.
- **A quoted reply is an edit.** Quoting the poll with your own text releases that text
  as the answer (`approve --text`), when the item offers `approve`. A plain text message
  without a quote does nothing.
- **Latency.** The tick runs every two minutes and listens `receive_timeout_sec` for
  votes. A vote cast between ticks is executed on the next one.
