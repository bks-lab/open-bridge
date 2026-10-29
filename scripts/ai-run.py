#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run a worker's text-only AI request with workflow/ai-services/<service>.yaml.

No file tools, no automatic fallback. Input is a prompt argument or stdin; stdout
is the answer (or a normalized JSON result with --json). --show only reads config.
--list prints the built-in services and the providers each can run (ai_services.SERVICES).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from lib import ai_services as ai


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--service")
    parser.add_argument("--list", action="store_true", help="the built-in services and the providers each can run")
    parser.add_argument("--provider", choices=ai.PROVIDERS, help="explicit override for this invocation")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--show", action="store_true", help="show the selection without calling a model")
    parser.add_argument("prompt", nargs="?")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps({k: {"providers": list(v["providers"]), "code": v["code"]} for k, v in ai.SERVICES.items()})
              if args.json else ai.services_table(), end="" if not args.json else "\n")
        return 0
    if not args.service:
        parser.error("--service is required")
    try:
        choice = ai.select(args.root, args.service, provider=args.provider)
        if args.show:
            print(json.dumps({"service": args.service, "provider": choice.provider, "model": choice.model,
                              "configured": choice.configured}))
            return 0
        if args.timeout < 1:
            raise ValueError("timeout must be positive")
        prompt = args.prompt if args.prompt is not None else sys.stdin.read()
        if not prompt.strip():
            raise ValueError("a prompt is required")
        proc = subprocess.Popen(ai.batch_argv(choice, prompt), cwd=args.root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise ValueError("AI request timed out")
        if proc.returncode:
            raise ValueError(err.strip()[-500:] or f"{choice.provider} exited {proc.returncode}")
        if choice.provider == "codex":
            answer = ai.parse_codex(out)
        else:
            raw = json.loads(out)
            answer = {"text": raw.get("result"), "error": raw.get("is_error", False),
                      "total_usd": raw.get("total_cost_usd"), "model": list(raw.get("modelUsage", {}))}
        if not answer or answer.get("error") or not answer.get("text"):
            raise ValueError((answer or {}).get("text") or "no completed answer")
        if args.json:
            print(json.dumps({"provider": choice.provider, "requested_model": choice.model, **answer}, ensure_ascii=False))
        else:
            print(answer["text"])
        return 0
    except (ValueError, OSError) as exc:
        print(f"ai-run: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
