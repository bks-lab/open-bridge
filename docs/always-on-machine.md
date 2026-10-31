---
summary: "Turn a machine that is always on into the arm of your Bridge: register it, reach it, keep a clone fresh, give it a push identity for the inbox only, prove one probe run, then add watchers that file what needs you into the inbox."
type: guide
last_updated: 2026-10-04
related:
  - docs/inbox.md
  - docs/workloads.md
  - docs/remotes.md
  - rules/push-guard.md
  - examples/portfolio/README.md
---

# Turn an always-on machine into the arm of your Bridge

Your laptop is asleep half the day. Something that is on all the time can look
at the world while you are not: is the sync still running, did the PR go green,
is the backup fresh. What it finds has to land somewhere you will read it, and
that place is the [inbox](inbox.md). The machine is the arm, the inbox is what
the arm hands you.

You do not need this to use the inbox. Without an always-on machine, the same
runs happen while your laptop is on, and the inbox is identical. A machine only
moves the watching to times you are not there.

## 1. What qualifies

Anything that stays on, can reach the internet and can run `git`, `python3` and
a scheduler: a mini PC in a cupboard, a home server, an old laptop with the lid
open, a small VM you rent. It does not need to be fast. A watcher spends a few
seconds every few minutes.

It does need to be yours to trust. The clone on it holds your Bridge, so treat
the machine like the laptop.

## 2. Register it

One file per machine under `infra/remotes/`, from
[`_template.yaml`](../infra/remotes/_template.yaml): name, how to reach it, what
it is for. The `remote` skill reads it for "which machine", wake, status and
service checks. See [remotes.md](remotes.md). A worked example is
[`examples/portfolio/infra/remotes/homebox.yaml`](../examples/portfolio/infra/remotes/homebox.yaml).

Add `arm` to its `capabilities` list. That one word is how the rest of the Bridge
knows the machine exists for this: the briefing offers "should <machine> watch
this?" only when some remote carries it, so the offer never appears where nobody
could keep it.

```yaml
capabilities: [ssh, git, services, arm]
```

## 3. Make it reachable

Plain `ssh` is enough. Put the host, user and port in the remote file and make
`ssh <name> true` work from the laptop with a key, not a password.

A private network such as Tailscale is one convenient option: the machine gets a
stable name that works from anywhere without opening a port on your router. It
is not required. A LAN address, a dynamic DNS name or a jump host does the same
job. Whatever you pick, never expose the machine's login to the open internet
with a password.

## 4. A clone of the Bridge, kept fresh

On the machine, clone your Bridge (your private origin, on your `user/*`
branch) to a stable path. Then declare a **puller** as the first workload: an
interval run that fetches and fast-forwards the clone every few minutes. Without
it the machine would watch with yesterday's config and yesterday's inbox.

```yaml
id: bridge-puller
purpose: "Keeps the Bridge clone on this machine current so watchers read today's config"
persona_ref: _infrastructure
placement: {host: <machine>, kind: interval, runtime: systemd, owner: bridge}
schedule: {every_sec: 300}
execution:
  command: ["git", "-C", "/home/<user>/bridge", "pull", "--ff-only"]
  timeout_sec: 120
  single_flight: true
  on_timeout: report
```

Fill in the rest from [`_template.yaml`](../workflow/workloads/_template.yaml);
the `workload` skill renders the unit from it. If the puller cannot fast-forward
(someone left local edits in the clone), it fails loudly instead of merging. Fix
the clone by hand once, and keep the machine's clone free of hand edits.

## 5. A git identity that may push only the inbox

The machine writes back through git. Give it its own identity, not yours: its
own name and email in the clone's git config, and its own credential (a deploy
key or a token scoped to this one private repository). Two reasons:

- **History says who wrote.** Every inbox event carries the author, so "homebox
  filed this" is visible and a leaked credential can be revoked without touching
  yours.
- **The push is conflict-free by construction.** An inbox item is written once,
  and every later change is a new file under its `events/` folder. Two machines
  and you can all write the same inbox and never touch the same file.
  `python3 scripts/inbox.py sync` commits only `work/inbox/`, rebases and pushes,
  and refuses to push when the clone holds other unpushed commits, so a watcher
  cannot push half-finished work. A rebase that fails is aborted, never left
  half-done.
- **Make this machine the runner.** Set `inbox.runner: <machine>` in
  `bridge-config.yaml` so only the arm executes approved actions; the laptop's
  briefing then lists what is ready instead of running it a second time.
- **The puller must not reset over an unpushed inbox commit.** If your puller
  resets the clone to the upstream (`git reset --hard`), a sync whose push failed
  loses its commit on the next pull. Rebase commits that touch only
  `work/inbox/` onto the upstream and push them instead; stop on anything else.

"Only the inbox" is what `sync` does, not something the credential enforces: a
deploy key writes the whole repository. If your git host can restrict a
credential to paths or to a branch, use that as the second lock.

### A cockpit on this machine

`python3 scripts/bridge-cockpit.py serve --served` runs the cockpit for the people named in a workspace's `members:`
on this machine: no model, no terminal driver, no daily triage, no relay, still bound to 127.0.0.1. Run it with the
Python that has PyYAML, under whatever keeps your services alive.

A puller may reset this clone, so a person's entry must not stay uncommitted. After each of their actions the
cockpit compares `work/` before and after, keeps the changed paths in `work-sync.jsonl` beside its state and has
`scripts/work-sync.py` commit exactly those and push them. Only `work/tasks/`, `work/done/`, `work/inbox/` and
`work/log.md` are accepted. Files another session left open stay out. Without a network the commit waits locally,
so the puller must rebase and push such commits as it does for the inbox, extended to the same paths.

Two machines now append to `work/log.md`. Put `work/log.md merge=union` into the instance's `.gitattributes`, or
every rebase over a log row conflicts.

The [push guard](../rules/push-guard.md) is unchanged. The machine pushes to your
private origin. A `user/*` branch still never reaches a public upstream, and the
pre-push hook on the machine's clone (`git config core.hooksPath scripts/hooks`)
enforces that there too. Arm it when you clone.

To reach it from outside, put a sign-in gateway in front and set `cockpit.served.access`: the cockpit then takes a person
only from the gateway's signed token and has no owner login at all ([`docs/bridge-cockpit.md`](bridge-cockpit.md#2-open-it),
"Behind a sign-in gateway"). Never open a tunnel to a served cockpit without that block.

## 6. A first probe: declare, run, inspect, retire

Before any real watcher, prove the whole loop with one harmless run. Declare a
oneshot or hourly workload that files a single inbox item and closes itself:

```bash
python3 scripts/inbox.py add --from <machine>/probe --kind result --key arm-probe \
    --gate free --urgency later --summary "The arm on <machine> reached the inbox" \
    --closes-when-json '{"after": "<one hour from now, ISO>"}'
python3 scripts/inbox.py sync
```

Then walk the four verbs with the `workload` skill: **declare** it in
`workflow/workloads/arm-probe.yaml`, **provision** it, **inspect** it (`reconcile`
asks the live scheduler, never a status field, and the item shows up on your
laptop after a pull), and **retire** it with a dated reason. If all four work,
every later watcher is the same shape with a different probe.

## 7. Starter watchers

Each one is a small workload with `reports_to: inbox` (see
[workloads.md](workloads.md)) and an item that carries a `closes_when`, so it
ends when the live source says it is solved. Use a stable `--key`: a watcher
that fires every five minutes is then one item, not a pile. A run that finds
nothing wrong files nothing.

**An issue or PR moves.** Waiting on a reply or a review:

```bash
python3 scripts/inbox.py add --from <machine>/watch --kind finding --key pr-70-review \
    --urgency today --summary "PR 70 has a review waiting" \
    --closes-when-json '{"gh_pr": "org/repo#70", "state": "merged"}'
```

For an issue use `{"gh_issue": "org/repo#12", "state": "closed"}`.

**PR green, then a conditional yes.** File the decision with the action, and
approve it with a condition. `inbox.py run` on a schedule executes approved
`your-yes` actions once the condition holds. Only the configured runner
executes, so a single machine acts on each yes:

```bash
python3 scripts/inbox.py add --from <machine>/watch --kind decision --gate your-yes \
    --key pr-70-merge --summary "Merge PR 70 once it is green" \
    --action-json '{"argv": ["gh", "pr", "merge", "70", "-R", "org/repo", "--squash"]}' \
    --closes-when-json '{"gh_pr": "org/repo#70", "state": "merged"}'
python3 scripts/inbox.py approve <id> --when-json '{"gh_pr": "org/repo#70", "state": "green"}'
```

Your yes is a person's decision, recorded once. An `only-you` item (send,
publish, pay) is never executed by the script, whatever was recorded.

**A service is still alive.** Probe the live thing, not a file about it:

```bash
curl -fsS https://service.example/health >/dev/null || \
python3 scripts/inbox.py add --from <machine>/alive --kind finding --key service-down \
    --urgency now --summary "service.example does not answer" \
    --closes-when-json '{"command": ["curl", "-fsS", "https://service.example/health"]}'
```

**A backup is fresh.** Same shape, with a probe on the newest file or marker:

```bash
python3 scripts/inbox.py add --from <machine>/backup --kind finding --key backup-stale \
    --urgency today --summary "Last backup is older than 26 hours" \
    --closes-when-json '{"command": ["sh", "-c", "test -n \"$(find /srv/backup/last-ok -mmin -1560)\""]}'
```

The probe wraps `find` in `test -n` because `find` exits 0 even when it
matches nothing.

**A mailbox or a sender to watch.** A run that reads a mailbox (through a
channel you have set up) and files one item per sender or thread you care
about. Key it on the sender or thread id, close it when the mail is answered or
a task reaches done: `{"task_status": "<slug>", "status": "done"}`.

## 8. The morning view, and what to push

The machine should not send its own report. A morning run does one thing: pull,
then render the inbox for the place you look.

```bash
python3 scripts/inbox.py check          # close what the live sources say is done
python3 scripts/inbox.py list --short   # one line per item: phone, e-ink, a chat
```

Send that output to a phone or an e-ink screen instead of composing a summary.
Push only what is red, in one line: what happened and what to do. A digest that
talks every morning gets muted within a week, and the one line that mattered
goes with it. Everything else waits in the inbox until you open it.

## Where to read next

[inbox.md](inbox.md) for the model and gates, [workloads.md](workloads.md) for the
declaration, and [`examples/portfolio/`](../examples/portfolio/README.md) for a
home server that does all of this.
