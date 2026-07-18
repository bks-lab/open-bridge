"""Async subprocess runner for ``claude -p`` — the Bridge-Agent brain.

One subprocess per turn. The agent's persona is injected with
``--append-system-prompt`` (so the model keeps its base capabilities); its
grounding content is mounted read-only with ``--add-dir``; its tool footprint is
whatever ``allowed_tools`` permits (default read-only ``Read,Glob,Grep``).

Generic by design — nothing here knows about a specific agent. The instance
supplies system_prompt / content_dir / allowed_tools via the config.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# claude -p ``--output-format stream-json`` emits each event as ONE NDJSON line.
# A ``Read`` tool_result embeds the whole file as a single line (the grounding CV
# is ~104 KiB), which blows past asyncio's DEFAULT 64 KiB StreamReader line limit
# → ``readline()`` raises ``LimitOverrunError`` (re-wrapped as ``ValueError``) and,
# being uncaught, turns the turn into a textless FAILED. Give the subprocess pipes
# a large line buffer so big events parse instead of crashing the turn.
_STREAM_LIMIT = 64 * 1024 * 1024  # 64 MiB

# Throttle for partial-message text deltas: forward a growing snapshot of the answer
# only after it has grown by at least this many characters, so the executor emits a
# handful of incremental updates rather than one A2A event per token.
_DELTA_MIN_CHARS = 48

# Public-endpoint hardening. ``--permission-mode acceptEdits`` auto-allows commands
# the engine classifies as read-only — independent of ``--allowedTools`` — and a
# headless ``-p`` agent has no human to gate them. A prompt-injected public visitor
# could otherwise have the agent run a read-classified ``cat``/``security``/``sqlite3``
# and fold the output (keychain secret, the request-intake PII log, a file outside the
# grounding dir) into its answer. Deny rules OVERRIDE the read-only auto-allow, so we
# explicitly deny the known read-only/recon/secret binaries. ``python3`` stays ALLOWED
# (the scoped instance tools are ``python3 <abs>/tool.py``; ``python3 -c …`` is not
# classified read-only, so it is not auto-run). Defense-in-depth on top of the model's
# own refusal + the cwd-confined file tools; the stronger control is a future sandbox.
# A denylist is a BACKSTOP, not the control. ``acceptEdits`` auto-allows ANY
# engine-read-only shell command, so every file-reading / scripting / archiver /
# egress binary NOT listed here is a potential read-out of arbitrary user-readable
# files via an absolute path (cwd-confinement binds only the Read/Glob/Grep file
# tools, not Bash). This list raises the bar but can never be complete — the real
# fix is an OS sandbox (sandbox-exec/Seatbelt or a dedicated low-priv user) that
# confines reads to the grounding dir. Keep this list broad. (2026-06-08 review:
# expanded from ~40 to cover awk/sed/perl/git/base64/tar/diff/… after a live
# jailbreak probe — the model refused, but the permission-layer gap is structural.)
_DISALLOWED_TOOLS = ",".join(
    f"Bash({_b}:*)"
    for _b in (
        # file readers / dumpers / formatters
        "cat", "ls", "head", "tail", "less", "more", "tac", "nl", "rev", "fold",
        "fmt", "pr", "col", "expand", "unexpand", "cut", "tr", "paste", "join",
        "comm", "look", "sort", "uniq", "wc", "xxd", "od", "hexdump", "strings", "vis",
        # search
        "grep", "egrep", "fgrep", "zgrep", "bzgrep", "xzgrep", "rg", "ag", "ack",
        "find", "mdfind", "pcregrep", "pcre2grep",
        # stream editors / scripting interpreters (arbitrary file read) — python3 stays ALLOWED (scoped tools)
        "sed", "awk", "gawk", "mawk", "perl", "ruby", "php", "node", "lua",
        "tclsh", "expect", "python", "python2", "m4", "xargs",
        # editors (read any file into a buffer / shell-out)
        "ed", "ex", "vi", "vim", "view", "nano", "emacs", "pico",
        # hashing / encoding (exfil-confirm + base64 read-out)
        "base64", "base32", "basenc", "shasum", "md5", "md5sum", "sha1sum",
        "sha256sum", "cksum", "sum", "openssl",
        # archivers (read files out)
        "tar", "cpio", "pax", "zip", "unzip", "gzip", "gunzip", "zcat", "bzip2",
        "bzcat", "xz", "xzcat", "ditto",
        # diff / compare (reveals content)
        "diff", "colordiff", "sdiff", "diff3", "cmp", "vimdiff",
        # VCS (read files + remote exfil)
        "git", "hg", "svn",
        # secret / config stores + macOS recon
        "security", "sqlite3", "defaults", "plutil", "dscl", "dscacheutil",
        "networksetup", "ioreg", "system_profiler", "scutil", "sysctl", "profiles",
        "tmutil", "log", "lsof", "id", "whoami", "ps", "env", "printenv", "set",
        "export", "last", "who", "w",
        # network egress
        "curl", "wget", "nc", "ncat", "socat", "ssh", "scp", "sftp", "ftp",
        "telnet", "rsync", "mail", "mailx", "sendmail",
        # misc side effects / clipboard / app launch
        "osascript", "open", "launchctl", "pbpaste", "pbcopy", "tee", "dd", "say",
    )
)


def _build_env(context_id: str | None) -> dict[str, str] | None:
    """Build the subprocess env, adding ``AGENT_CONTEXT_ID`` when ``context_id`` is set.

    Instance tools (argparse CLIs invoked via Bash, or anything reading its inherited
    env) have no other way to learn which A2A session is calling them — e.g. an
    intake/concern-notification tool wants the real session id instead of "unknown".
    Returns ``None`` (→ the subprocess inherits the parent's env unchanged, asyncio's
    default) when there is no context_id, so we never export an empty-string
    placeholder that a consumer could mistake for a real id.
    """
    if not context_id:
        return None
    return {**os.environ, "AGENT_CONTEXT_ID": context_id}


class SubprocessClaudeRunner:
    """Run ``claude -p <prompt> --output-format json ...`` and return the answer."""

    def __init__(
        self,
        *,
        binary: str,
        model: str,
        system_prompt: str,
        working_dir: str,
        extra_read_dirs: list[str] | None = None,
        timeout: float = 90.0,
        allowed_tools: str = "Read,Glob,Grep",
        timeout_message: str = "The request could not be processed in time. Please try again.",
        empty_message: str = "No answer received from the model.",
        spawn_error_message: str = "The agent is briefly overloaded. Please try again in a moment.",
    ) -> None:
        self._binary = binary
        self._model = model
        self._system_prompt = system_prompt
        # cwd = the agent's grounding dir. This CONFINES the read-only file tools
        # (Read/Glob/Grep) to public content — a public endpoint must never be
        # able to read the host repo's private files. Instance tools are invoked
        # by ABSOLUTE path (see allowed_tools), so they still resolve from here.
        self._working_dir = working_dir
        self._extra_read_dirs = list(extra_read_dirs or [])
        self._timeout = timeout
        self._allowed_tools = allowed_tools
        self._timeout_message = timeout_message
        self._empty_message = empty_message
        self._spawn_error_message = spawn_error_message

    def _build_cmd(self, prompt: str, *, stream: bool) -> list[str]:
        """Assemble the ``claude -p`` argv shared by ``__call__`` and ``stream``.

        ``stream`` toggles NDJSON streaming (``stream-json`` + ``--verbose``) vs a
        single buffered JSON document. ``acceptEdits`` stops interactive prompts so
        the subprocess never hangs; ``--setting-sources project`` loads ONLY project
        settings — never the host user's ``~/.claude`` allowlist/hooks, which would
        silently widen this internet-facing agent.
        """
        cmd = [self._binary, "-p", prompt, "--model", self._model]
        if stream:
            # ``--include-partial-messages`` adds ``stream_event`` frames carrying the
            # model's text deltas AS THEY GENERATE, so the executor can forward them and
            # the visitor sees the answer build up within a few seconds instead of all at
            # once at the end. The terminal ``result`` event still arrives — it stays the
            # authoritative answer, so partial frames are purely additive.
            cmd += ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
        else:
            cmd += ["--output-format", "json"]
        cmd += ["--append-system-prompt", self._system_prompt]
        for extra in self._extra_read_dirs:
            cmd += ["--add-dir", extra]
        cmd += [
            "--allowedTools", self._allowed_tools,
            "--disallowedTools", _DISALLOWED_TOOLS,
            "--permission-mode", "acceptEdits",
            # Public agent: load ONLY project settings, never the host user's
            # allowlist/hooks — those would silently widen this internet-facing agent.
            "--setting-sources", "project",
        ]
        return cmd

    async def __call__(self, prompt: str, *, context_id: str | None = None) -> str:
        """Invoke claude -p and return the assistant's answer text.

        ``context_id`` (the A2A session id), when present, is exported into the
        subprocess env as ``AGENT_CONTEXT_ID`` — see ``_build_env`` for why.
        """
        cmd = self._build_cmd(prompt, stream=False)
        logger.debug("claude_runner: spawning %s", " ".join(cmd[:6]))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._working_dir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT,
                env=_build_env(context_id),
            )
        except OSError:
            logger.exception("claude_runner: spawn failed (buffered)")
            return self._spawn_error_message
        try:
            out_bytes, err_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.error("claude_runner: timeout after %.0fs", self._timeout)
            return self._timeout_message

        stderr = err_bytes.decode("utf-8", "replace").strip()
        if stderr:
            logger.debug("claude_runner stderr: %s", stderr[:500])

        raw = out_bytes.decode("utf-8", "replace").strip()
        if not raw:
            logger.warning("claude_runner: empty stdout (rc=%s)", proc.returncode)
            return self._empty_message

        try:
            data = json.loads(raw)
            result = data.get("result") or data.get("text") or ""
            if result:
                return result
            logger.warning("claude_runner: json has no .result field: %s", list(data.keys()))
            return raw
        except json.JSONDecodeError:
            logger.warning("claude_runner: stdout was not JSON, using raw")
            return raw

    async def stream(self, prompt: str, *, context_id: str | None = None) -> AsyncIterator[dict]:
        """Run with ``--output-format stream-json --verbose`` and yield events.

        Yields ``{"kind":"step", "tool":..., "label":...}`` per tool_use block and
        exactly one ``{"kind":"answer", "text":...}`` from the terminal result
        event (or synthesised from accumulated assistant text if none arrives).

        ``context_id`` (the A2A session id), when present, is exported into the
        subprocess env as ``AGENT_CONTEXT_ID`` — see ``_build_env`` for why.
        """
        cmd = self._build_cmd(prompt, stream=True)
        logger.debug("claude_runner: streaming %s", " ".join(cmd[:6]))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._working_dir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT,
                env=_build_env(context_id),
            )
        except OSError:
            logger.exception("claude_runner: spawn failed (stream)")
            yield {"kind": "answer", "text": self._spawn_error_message}
            return

        answer = ""
        text_fallback: list[str] = []
        answer_yielded = False
        streamed = ""        # text accumulated from partial-message deltas
        emitted_len = 0      # length of ``streamed`` at the last delta yield (throttle)
        try:
            async for raw_line in _readlines_with_timeout(proc.stdout, self._timeout):
                line = raw_line.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = evt.get("type")
                if etype == "result":
                    answer = evt.get("result") or evt.get("text") or ""
                    yield {"kind": "answer", "text": answer or self._empty_message}
                    answer_yielded = True
                elif etype == "stream_event":
                    # Partial-message text delta (``--include-partial-messages``). Accumulate
                    # and emit the running total, throttled so we forward a handful of growing
                    # snapshots rather than one event per token. The widget renders each as the
                    # answer-so-far; the terminal ``result`` remains authoritative.
                    delta = _text_delta_from_stream_event(evt)
                    if delta:
                        streamed += delta
                        if len(streamed) - emitted_len >= _DELTA_MIN_CHARS:
                            emitted_len = len(streamed)
                            yield {"kind": "delta", "text": streamed}
                elif etype == "assistant":
                    for step in _steps_from_assistant_event(evt):
                        yield step
                    for block in (evt.get("message", {}) or {}).get("content", []) or []:
                        if isinstance(block, dict) and block.get("type") == "text":
                            txt = block.get("text") or ""
                            if txt:
                                text_fallback.append(txt)
        except asyncio.TimeoutError:
            logger.error("claude_runner: stream timeout after %.0fs", self._timeout)
        except (asyncio.LimitOverrunError, ValueError) as exc:
            # A single NDJSON line exceeded even the raised buffer limit. Degrade to
            # whatever assistant text we accumulated instead of crashing to FAILED.
            logger.error("claude_runner: stream line exceeded buffer (%s)", exc)
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

        if not answer_yielded:
            fallback = "\n".join(text_fallback).strip()
            yield {"kind": "answer", "text": fallback or self._empty_message}


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

async def _readlines_with_timeout(stream, timeout: float) -> AsyncIterator[bytes]:
    """Yield lines from ``stream`` under an overall deadline (StreamReader has none)."""
    if stream is None:
        return
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        line = await asyncio.wait_for(stream.readline(), timeout=remaining)
        if not line:  # EOF
            return
        yield line


def _text_delta_from_stream_event(evt: dict) -> str:
    """Return the text of a partial-message ``content_block_delta``, else "".

    ``--include-partial-messages`` wraps raw Anthropic streaming events as
    ``{"type":"stream_event","event":{...}}``. We only want assistant *text* deltas
    (``content_block_delta`` with a ``text_delta``); tool-argument deltas
    (``input_json_delta``) and lifecycle frames (start/stop) carry no answer text and
    are ignored. Shape-tolerant: any unexpected structure yields "".
    """
    event = evt.get("event") or {}
    if event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta") or {}
    if delta.get("type") != "text_delta":
        return ""
    return delta.get("text") or ""


def _steps_from_assistant_event(evt: dict) -> list[dict]:
    """Extract ``{"kind":"step", ...}`` dicts from an ``assistant`` NDJSON event."""
    steps: list[dict] = []
    content = (evt.get("message", {}) or {}).get("content", []) or []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool, label = _label_from_tool_use(block.get("name") or "", block.get("input") or {})
        steps.append({"kind": "step", "tool": tool, "label": label})
    return steps


def _label_from_tool_use(name: str, tool_input: dict) -> tuple[str, str]:
    """Map a ``tool_use`` (name + input) to a (tool, short activity label) pair."""
    if name == "Read":
        path = tool_input.get("file_path") or ""
        return "Read", "Reading " + (os.path.basename(path) if path else "a file")
    if name == "Glob":
        return "Glob", "Searching files " + (tool_input.get("pattern") or "")
    if name == "Grep":
        return "Grep", "Searching content for “" + (tool_input.get("pattern") or "") + "”"
    if name == "Bash":
        command = tool_input.get("command") or ""
        if "book_request" in command:
            return "Bash", "Recording your request"
        if "availability" in command:
            return "Bash", "Checking availability"
        return "Bash", "Running a command"
    return "Other", "Working…"
