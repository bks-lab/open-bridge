---
summary: "How to stand up a representative agent — a persistent, addressable A2A endpoint that fronts one persona to the outside world, safely, on any bridge."
type: doc
last_updated: 2026-07-12
related:
  - ../agents/README.md
---

# The Representative Agent

A **representative agent** is a persistent, addressable A2A endpoint that fronts
**one persona** to the outside world. It answers questions about that persona,
reveals availability, and takes in requests — always under hard human gates, never
acting on its own. This guide explains the *pattern* so any bridge can stand one up.
The engine that runs it is generic (`agents/_runtime/`, CORE); everything specific
to a persona lives in a per-agent instance folder (`agents/<name>/`, USER).

The runtime code is the source of truth. Where this guide describes behaviour, it
matches `agents/_runtime/{server,executor,runner,card,config}.py` and the instance
contract in `agents/_template/agent.yaml`.

## 1. What it is

### Bridge-Agent, not sub-agent

The word "agent" means two different things in this repo. A **sub-agent**
(`.claude/agents/`) is ephemeral, inward-facing machinery: it runs one task inside
your session and returns a summary — a function with tools. A **Bridge-Agent**
(`agents/`) is a persistent, addressable *entity* that faces outward: its body is a
runnable instance under `agents/<name>/`, its self is the persona in the system
prompt, and its interface is a published A2A **AgentCard**. A representative agent is
the outward-facing kind. (Full disambiguation table: `agents/README.md`.)

### Two faces, one self

A Bridge-Agent has two faces over the same machinery:

- **Outer face** — the world: anonymous visitors, foreign agents, a website widget.
  This is the *representative* face. It discloses only public, grounded facts about
  the persona and captures requests for a human to act on. This guide is about the
  outer face.
- **Inner face** — the peer mesh: your own fleet and trusted peer bridges talking
  agent-to-agent. Same runtime, same self, opposite direction and a very different
  trust boundary.

The safety model below is written for the outer face, where every request is
assumed hostile. An inner-face deployment relaxes the caps but keeps the same shape.

## 2. Instance anatomy

Copy the template to start an instance:

```bash
cp -r agents/_template agents/<name>
```

Each instance is fully declarative — three parts under `agents/<name>/`:

- **`agent.yaml`** — the card spec plus every runtime knob. It carries the AgentCard
  fields (`name`, `description`, `version`, `provider`, `skills`), the network
  binding (`host`, `port`, `public_url`), the model and per-turn `timeout`, the
  `grounding_dir`, the scoped `allowed_tools`, and the public-endpoint caps
  (`max_concurrency`, `max_input_chars`, `max_turns`, `max_contexts`). Any field can
  be overridden by an environment variable at launch (`PUBLIC_AGENT_URL`,
  `AGENT_HOST`, `AGENT_PORT`, `CLAUDE_MODEL`, `GROUNDING_DIR`, `CLAUDE_BINARY`,
  `ENVIRONMENT`, `CORS_ALLOWED_ORIGINS`) so the same files run in dev and on the host.
- **`system-prompt.md`** — the persona. It is appended to the model's base prompt
  (`--append-system-prompt`), so the model keeps its capabilities and gains the
  persona's voice, facts, and disclosure boundary. This file defines *who the agent
  is* and *what it may reveal*. Optionally, declared grounding files can be embedded
  straight into this prompt at load (`inline_grounding:`) so the agent answers from
  context instead of paying a file-read round-trip per question.
- **`tools/`** — instance-specific scoped tools, written as small argparse CLIs. The
  runtime never invokes them by name from the working directory; it invokes them by
  **absolute path**. In `agent.yaml` you reference them with a `${tools_dir}`
  placeholder that the loader substitutes for the resolved absolute path of
  `agents/<name>/tools` (and `${instance_dir}` for the instance root). The same
  substitution is applied inside `system-prompt.md`, so the prompt tells the agent to
  call the exact absolute path that `allowed_tools` permits — necessary because the
  agent's working directory is the grounding dir, not the instance folder.

Run it and probe the card:

```bash
cd agents && uv run python -m _runtime.server --agent <name> --port 8011
curl -s localhost:8011/.well-known/agent-card.json | head
curl -s localhost:8011/health
```

## 3. The runtime

### One subprocess per turn

The brain is `claude -p`. For every turn the runner spawns a fresh subprocess
(`SubprocessClaudeRunner`), feeds it the assembled prompt, and reads back exactly one
answer. `claude -p` is stateless, and the A2A SDK creates a new task per message, so
conversation memory is kept by the executor keyed on the client's stable
`context_id` and folded into each prompt as a short transcript. The persona is
injected with `--append-system-prompt`; the grounding dir is the subprocess `cwd`;
extra read-only mounts are added with `--add-dir`; the tool footprint is whatever
`allowed_tools` permits (default read-only `Read,Glob,Grep`).

### Plain Starlette + a2a-sdk 1.x

The server is a **plain Starlette app**, not an `A2AStarletteApplication` wrapper —
a2a-sdk 1.x has no such wrapper. `build_app(cfg)` composes the SDK's JSON-RPC routes
and agent-card routes into a Starlette app, wired to a `DefaultRequestHandler` over
an `InMemoryTaskStore`, with the `ClaudeAgentExecutor` as the agent executor. A CORS
middleware restricts origins to the configured list. Two small correctness shims live
here: `enable_v0_3_compat=True` keeps 0.3-dialect clients working, and a route wrapper
restores the A2A-spec error codes that a2a-sdk 1.x otherwise flattens to the generic
JSON-RPC `InternalError`.

### Discovery and endpoints

- **AgentCard** is served at the modern **`/.well-known/agent-card.json`**, with a
  legacy alias at **`/.well-known/agent.json`** for older clients. In a2a-sdk 1.x the
  single `url` field is gone; the card advertises a list of `supported_interfaces`,
  each an `AgentInterface` with the public URL and a JSON-RPC transport binding
  (`protocol_binding=TransportProtocol.JSONRPC`). The card separately carries
  `capabilities=AgentCapabilities(streaming=True, push_notifications=False)`.
- **`message/send`** returns a single completed task; **`message/stream`** returns the
  same turn as Server-Sent Events, so a visitor sees the answer build up.
- **`tasks/*`** (get, cancel, …) are handled by the SDK request handler.
  `tasks/cancel` actually aborts the in-flight `claude -p` run: the executor cancels
  the asyncio task, whose `finally` kills the subprocess, and emits `CANCELLED`.
- **`/health`** is a plain GET returning `{"status":"ok","agent":<instance>}`.

The final answer is delivered both as a durable Task **artifact** and in the completed
status message, so a widget that reads either surface renders one bubble.

## 4. The safety model

A public endpoint is assumed hostile on every request. Several independent layers
enforce that a visitor can never make the agent read private files, exfiltrate
secrets, or act on anyone's behalf.

### Read-confinement: cwd = grounding_dir

The single most important control. The subprocess runs with its **working directory
set to the grounding dir** — the folder of *public* content the agent is allowed to
know. That cwd confines the read-only file tools (`Read`, `Glob`, `Grep`) to public
content: they cannot reach the bridge's private tree (`identity/`, `work/`, memory,
customer data). Scoped instance tools still resolve because they are invoked by
absolute path, not relative to cwd.

### Scoped allowed_tools

`allowed_tools` grants read-only file access plus **only** the intended instance
tools, each by absolute path — no generic shell, no write tool, no arbitrary send.
The default is `Read,Glob,Grep`; an intake CLI is added explicitly, e.g.
`Read,Glob,Grep,Bash(python3 ${tools_dir}/book_request.py:*)`.

### The read-only-shell denylist (backstop)

There is a structural gap in the permission layer. The runner launches with
`--permission-mode acceptEdits` so a headless `-p` agent never hangs on an interactive
prompt — but `acceptEdits` **auto-allows any shell command the engine classifies as
read-only, independent of `allowed_tools`**. A prompt-injected visitor could otherwise
have the agent run a read-classified binary (`cat`, `security`, `sqlite3`, `git`, …)
by absolute path and fold the output — a keychain secret, the intake log, a file
outside the grounding dir — into its answer. Because cwd-confinement binds only the
`Read/Glob/Grep` file tools and **not** `Bash`, the runtime ships a broad **denylist**
(`--disallowedTools`) of the known file-reader, search, stream-editor, hashing,
archiver, VCS, secret-store, and network-egress binaries; deny rules override the
read-only auto-allow. `python3` is intentionally **left allowed** because the scoped
instance tools are `python3 <abs>/tool.py` (and `python3 -c …` is not classified
read-only, so it is not auto-run). This denylist is a **backstop, never the control** —
it raises the bar but can never be complete. The real read-confinement is the cwd
above plus, ideally, an OS sandbox (below).

### Project-only settings

The runner passes `--setting-sources project`, so it loads **only** the project's
settings — never the host user's `~/.claude` allowlist or hooks. A host preference can
therefore never silently widen this internet-facing agent.

### Fixed-recipient intake

An intake tool captures requests for the persona **alone** — no recipient argument, so
the agent cannot be steered into messaging a third party. Intake is durable-first: it
persists the request and exits 0 even if a later push notification fails, so a request
is never lost to a downstream hiccup. No booking or reply is ever sent autonomously;
every outward action goes through a human gate.

### Public-endpoint caps

An ungated endpoint will be hit. The executor enforces `max_concurrency` (shed load
with a friendly "busy" message rather than spawning unbounded subprocesses),
`max_input_chars` (reject overlong input), `max_turns` (transcript depth per context),
and `max_contexts` (an LRU bounded in both dimensions — turns per context and number
of contexts — so a stream of unique session IDs cannot grow memory without bound). Add
a per-IP edge rate-limit at your CDN.

### Honest card

Advertise only skills the prompt and tools actually implement. The AgentCard is the
agent's self-description; it must not claim a capability the instance cannot deliver.

### OS sandbox — the named real fix

The layers above are defense-in-depth on top of the model's own refusal. The **real**
fix for read-confinement is an OS sandbox that confines reads to the grounding dir and
blocks network and secret-store access with the mechanism the host supports — a
container running as an unprivileged user on Linux, or a `sandbox-exec` profile /
dedicated low-privilege user on the host OS. Name it as the goal; the denylist buys
time until it is in place.

## 5. The answer contract

The runtime upholds one hard contract on every turn: **exactly one non-empty answer,
delivered within `timeout` — never a hang, never a blank bubble.** A public visitor
must never watch "…working" forever or receive an empty reply. Three mechanisms hold
that line, all in the runner:

1. **Raised line buffer.** `claude -p --output-format stream-json` emits each event as
   one NDJSON line, and a single `Read` tool result can embed a whole grounding file
   on one line — easily past asyncio's default 64 KiB `StreamReader` limit, which
   would raise `LimitOverrunError` and turn the turn into a textless FAILED. The runner
   raises the subprocess pipe limit (`limit=_STREAM_LIMIT`, 64 MiB) so big events parse.
2. **Overall deadline.** A `StreamReader` has no total timeout, so the runner wraps
   line reads in an overall deadline. If the subprocess streams continuously past
   `timeout`, the turn still ends — with the configured "try again" text, never a hang.
3. **Accumulated-text fallback.** If no terminal `result` event ever arrives, the
   runner synthesises the answer from the assistant text it accumulated during the
   stream; if even that is empty, it returns a plain "no answer" message. A dropped or
   late partial delta self-corrects because the terminal result is authoritative.

Two production incidents bought this contract; it is locked by a hermetic regression
net (`agents/tests/test_runner.py`, stubbed — no real `claude`, no network) run in CI
on every PR to `main` (and every `main` push) that touches `agents/**`. Don't weaken
these paths without keeping the tests green.

**Latency is a knob, not a bug.** A broad question that makes the model read the whole
grounding and reason a full answer can take roughly a minute or two on a mid-tier
model. That is fine over a tunnel: SSE keepalive pings hold the connection open across
the silent reasoning gap, and on expiry `timeout` returns text rather than a blank —
so give `timeout` generous headroom. To make a turn *fast*, pull the levers that
remove work: keep the **grounding small**, or **inject the public content straight into
`system-prompt.md`** (`inline_grounding:`) so the agent answers from context and skips
the per-turn `Read` and its big-line cost, or run a **faster model** (trading some
depth for latency on pure Q&A).

## 6. Deploy

Host the runtime on a remote as a managed service (launchd on the host OS, systemd on
Linux), behind a **tunnel that maps the `public_url` hostname to the local port** the
process binds. Bind the process to loopback and let the tunnel be the only public
ingress. Set the persona-facing env overrides (`PUBLIC_AGENT_URL`, `GROUNDING_DIR`,
model, CORS) at the service level so the tracked instance files stay host-agnostic.

Track the deployment two ways: as an `infra/channels/<name>.yaml` entry (what the
endpoint is, where it lives, how to reach it) and in the hosting remote's service
list. Per the deploy-reconciliation rule, **the declared `status:` is never trusted** —
verify the live service manager and probe `/health` and the AgentCard endpoint. A
config that says "running" proves nothing; the service manager and a live request do.
