# A peer endpoint (trust: peer)

For Bridges you know but do not trust with your repo: a colleague's or a partner's
Bridge asking yours. Runtime support: `agents/_runtime/auth.py` (`trust: peer`,
bearer per peer, optional binding to the network identity a proxy asserts).

## 1. Scaffold

```bash
skills/a2a/a2a.sh new-agent <name> --trust peer --port 8015 \
  --peer alice:AGENT_PEER_TOKEN_ALICE:alice@example.org
```

`--peer ID:ENV:LOGIN`: the caller's id (in logs), the environment variable its token
arrives in, and its tailnet login (empty to skip the binding). Repeat per caller.

## 2. Fill in what the scaffold cannot know

- `agent.yaml`: description, provider, `public_url`, the skill. Keep skill examples
  generic: the card is readable without a token.
- `system-prompt.md`: which topics are in, which are closed, the fixed refusal
  sentence.
- `share/`: the only files the agent may read and pass on. A file there is a release.

## 3. Tokens

One per caller, 32 characters or more:

```bash
security add-generic-password -a "$USER" -s <name>-peer-alice -w "$(openssl rand -hex 32)"
```

Hand it over on a channel without history. The agent refuses to start when a token
is missing, short, or written into agent.yaml.

## 4. Launch

`agents/<name>/launch.sh` reads the tokens into the environment and starts the
server. Run it under launchd or systemd. On macOS not over ssh: the keychain is not
readable there, and `claude` is not logged in.

## 4a. Approval by the owner (recommended)

With an `approval:` block the runtime holds every finished answer, reports the task
as WORKING ("waits for its owner's approval"), streams nothing of it, and frees the
concurrency slot while it waits. It then runs your approver command: JSON in on
stdin, one decision out on stdout (`approve`, `edit` with `text`, `reject`,
`timeout`). A crash, garbage or silence past `timeout_sec` sends nothing. The
approver is yours to write: a messenger note with a quoted reply, a push button, a
page. Callers should ask with `a2a.sh ask <peer> "..." --wait <seconds>`, which sends
without blocking and polls.

## 4b. Requests: a peer asks for something to be DONE (optional)

A question is answered from `share/`. Some asks are not questions: "give Alice
DNS rights on that zone". With a `requests:` block (it needs `approval:` and
`auth:`) a peer can send those as requests, and you stay the one who decides:

```yaml
requests:
  enabled: true
  # rules: "policy/rules.yaml"       # default, inside agents/<name>/
  # ledger: "policy/ledger.jsonl"    # default
  # execute:                         # optional, see below
  #   command: ["python3", "${tools_dir}/execute.py"]
  #   timeout_sec: 900
```

What happens to a request:

1. **The model never sees it.** The runtime records it in the ledger and looks for
   one of your rules for that peer and subject (deny wins over allow).
2. **No rule: you are asked**, through the same approver command as answers, with
   `"kind": "request"`, the peer, the subject and the text. An approver that only
   knows answers still works: `answer` then holds a readable summary.
3. **You decide, and may decide for the future.** `approve` or `reject`, optionally
   with `text` (a note for the peer) and a `rule`:
   `{"decision": "approve", "rule": {"effect": "allow", "note": "...", "expires": "2027-01-01"}}`.
   `allow` means this peer gets the same subject without asking, `deny` means never.
   The rule's subject defaults to the request's; a trailing `*` covers a prefix,
   and only you can write one: a peer's subject is letters, digits and `. _ : @ / -`,
   no spaces, no wildcard, so it can neither widen your rule nor fake lines in what
   you read. A rule must agree with the decision (allow with a yes, deny with a no),
   otherwise nothing is done. An `edit` from an approver that only knows answers
   counts as a no, with your text as the reply.
4. **After a yes**, your `execute.command` runs with the request as JSON on stdin and
   answers `{"status": "done"|"failed", "text": "..."}`. It runs with your rights,
   so it decides what a yes may really do: the subject is a label the peer chose,
   not a guarantee. Without an execute command the peer is told you carry it out
   yourself.
5. **Everything is recorded** in `policy/ledger.jsonl`: requested, refused,
   decided (by you or by which rule), executed, cancelled, rule added, failed or
   revoked, each with time and peer. A peer may have three requests waiting on you
   at once; more are refused.

You keep the power over the rules: edit `policy/rules.yaml` by hand (read fresh on
every request; if it does not parse, no rule applies, every request comes to you,
and nothing is written over it until you fix it), or use the CLI from `agents/`:

```bash
python3 -m _runtime.policy <name> list
python3 -m _runtime.policy <name> history --peer <id>
python3 -m _runtime.policy <name> add --peer <id> --subject <s> --effect allow --note "..."
python3 -m _runtime.policy <name> revoke <rule-id>
```

A revoked rule stays in the file with `revoked_at`, so what was allowed when stays
readable. A peer reads the rules and history that concern it with
`a2a.sh rules <peer>`; it never sees another peer's. The card names the two extra
skills, `owner_request` and `owner_policy`, so a caller knows before it asks.

Callers: `a2a.sh request <peer> "<what>" --subject <area/target/action>`, then
`a2a.sh get <peer> <task_id>` to see the decision.

## 4c. What each peer may read, and topics on request (optional)

Without this, every peer reads the same `grounding_dir`. With `access:`, each peer
reads only its own folder, and the owner can keep topics "on request":

```yaml
access:
  peers_dir: "share/peers"      # one folder per auth.peers id; the agent will not start without them
  grant:
    command: ["python3", "<repo>/skills/a2a/scripts/share_build.py", "grant",
              "--config", "<instance>/access.yaml", "--root", "<repo>", "--out", "<instance>/share"]
    timeout_sec: 120
inline_grounding: ["index.md"]   # read from the asking peer's folder, fresh per request
allowed_tools: "Read(/${grounding_dir}/**),Glob(/${grounding_dir}/**),Grep(/${grounding_dir}/**)"
```

The agent refuses to start unless the folder really is the boundary: `allowed_tools`
holds only `Read`/`Glob`/`Grep` written exactly as `Tool(/${grounding_dir}/**)` (the
extra slash makes Claude Code's absolute `//path` form), no `extra_read_dirs`, a
folder for every peer, plain peer ids, and `grant` only together with `approval`. A
per-peer turn loads no settings and no memory files (`--setting-sources ""`): its
cwd lies inside the instance repo, and `project` would load the repo's CLAUDE.md
chain into every peer's context. Conversation memory is kept per peer and context.

The folders are built from an access file by `scripts/share_build.py build` (rules
per peer: `none`, `on_request`, `status`, `details`, `files`; format in the script's
docstring). Rebuild it whenever the sources change, for example after every pull.
Every level masks addresses, references, home paths, phone numbers, bank details, tax
ids and token shapes; YAML keys that name an address, an account or a secret are
dropped; a section marked `<!-- share: private -->` never leaves; symlinks are never
followed; a topic whose frontmatter cannot be read, or whose `share:` override is
wrong, is hidden and named on stderr instead of stopping the build.

Options in the access file (format in the script's docstring):

| Option | Where | Effect |
|---|---|---|
| `redact_terms: [..]` | per peer | drops every paragraph, list item, table row or heading section naming a term, also in text attachments and YAML items |
| `keep_email_domains: [..]` | top level | emails of these domains stay readable (colleagues) |
| `next_step_headings: [..]` | top level | the heading `status` carries, in the instance's language |
| `group: ".."` | per rule | index section for the topics the rule matches |
| `fields: [a, b.c]` | per rule | frontmatter fields shown in the topic (sensitive names never) |
| `summary: "{a}[[, {b[c]}]]"` | per rule | index line from the frontmatter; `[[ ]]` only when all its fields are set |
| `only:` / `exclude:` | per rule, YAML files | keep just these keys, drop list items with these values |

Long topics are cut to about 25 KB, keeping the opening, the next-step section and the
newest dated sections. Each peer folder carries `.on_request`, the ids the runtime may
ask the owner about; a card for any other id is never sent, and `grant.max_per_hour`
(default 5) caps the cards per peer. Check a build by reading the folder before
the first peer does: masking is a backstop for what slipped into a source, not a
reason to put secrets there.

When an answer needs a topic listed as on request, the agent asks the owner about
the TOPIC, not about a refusal: the approval command gets `"kind": "access"` with
`topic` and answers `approve` plus `"grant": "once"` or `"always"`, or `reject`. A
plain `approve` without `grant` counts as no, so an approver written before this
existed cannot open a topic by accident. On a yes the question is answered again
with the topic opened and sent without a second approval; afterwards the approval
command gets a `"kind": "notice"` with the text (its answer is ignored, so an
approver must recognise a notice instead of showing a new card for it).
`always` is recorded in `access.grants.yaml` next to the access file; delete an
entry to revoke it. Mechanics and failure behaviour: `agents/_runtime/access.py`.

The owner's approval card should say what it releases. A card that shows only a
finished answer reads as "may the peer have this?" while it means "may this text
leave?"; when the text is a refusal, approving it releases the refusal.

## 5. Publish on a private network only

```bash
tailscale serve --bg --https=8445 127.0.0.1:8015
```

Never `tailscale funnel` and never a public tunnel: the endpoint is for known
callers. `tailscale serve` adds `Tailscale-User-Login`, which the token is bound to.

## 6. Let a caller in

Share the machine with the caller (Tailscale admin console, "Share"). Restrict what
shared users reach to the one port in the tailnet policy, for example
`{"action": "accept", "src": ["autogroup:shared"], "dst": ["<machine>:8445"]}`.
Verify both after the share: the login header for a shared-in user, and that no
other port answers.

## 7. Probe

With a peer file on the calling side: `a2a.sh card <peer>` and `a2a.sh probe <peer>
--prompts <your prompts>`. Expected: 401 without and with a wrong token, 403 from a
wrong identity, fixed refusal on closed topics, an answer on open ones.
