#!/usr/bin/env python3
"""A stand-in for the codex CLI in the gen-images tests. It never touches the network.

Answers `features list`, `login status` and `exec`; the tests copy it to a bin
folder as `codex` with the interpreter line rewritten.

Env knobs:
  FAKE_CODEX_LOG    append one JSON line per call (argv, stdin prompt, cwd, key vars)
  FAKE_CODEX_COUNT  file that counts exec calls (for the *-after:N modes)
  FAKE_CODEX_MODE   ok (default) | no-image-feature | logged-out | api-key-login
                    | fail | no-file | usage-limit | usage-limit-after:N
                    | fail-on:TEXT (fail when the prompt contains TEXT) | hang
"""
import json
import os
import re
import struct
import sys
import time
import zlib


def png(width=12, height=8):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes((x * 5 + y * 11) % 256 for x in range(width * 3)) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def log(entry):
    path = os.environ.get("FAKE_CODEX_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


mode = os.environ.get("FAKE_CODEX_MODE", "ok")
args = sys.argv[1:]
log({"argv": args})

if args[:2] == ["features", "list"]:
    print("unified_exec                             stable             true")
    print("image_generation                         stable             %s" % ("false" if mode == "no-image-feature" else "true"))
    sys.exit(0)

if args[:2] == ["login", "status"]:
    if mode == "logged-out":
        print("Not logged in", file=sys.stderr)
        sys.exit(1)
    print("Logged in using an API key - sk-...abcd" if mode == "api-key-login" else "Logged in using ChatGPT")
    sys.exit(0)

if args[:1] == ["exec"]:
    prompt = sys.stdin.read()
    workdir = args[args.index("-C") + 1] if "-C" in args else os.getcwd()
    count = 0
    count_path = os.environ.get("FAKE_CODEX_COUNT")
    if count_path:
        count = int(open(count_path).read() or 0) if os.path.exists(count_path) else 0
        open(count_path, "w").write(str(count + 1))
    log({"exec": True, "argv": args, "prompt": prompt, "cwd": os.getcwd(), "workdir": workdir,
         "env_keys": [k for k in ("OPENAI_API_KEY", "CODEX_API_KEY") if k in os.environ]})
    limit = "You've hit your usage limit. Upgrade to Pro or try again later."
    if mode == "usage-limit" or (mode.startswith("usage-limit-after:") and count >= int(mode.split(":")[1])):
        print(limit)
        sys.exit(1)
    if mode == "fail" or (mode.startswith("fail-on:") and mode[len("fail-on:"):] in prompt):
        print("something went wrong")
        sys.exit(1)
    if mode == "hang":
        time.sleep(120)
    if mode == "no-file":
        print("I could not create the image.")
        sys.exit(0)
    name = re.search(r"Save it as (\S+) in the current folder", prompt).group(1)
    with open(os.path.join(workdir, name), "wb") as f:
        f.write(png())
    print(os.path.join(workdir, name))
    sys.exit(0)

print("fake codex: unknown call %r" % args, file=sys.stderr)
sys.exit(64)
