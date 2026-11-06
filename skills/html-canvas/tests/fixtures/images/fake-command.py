#!/usr/bin/env python3
"""A stand-in for a user-configured image command in the gen-images tests.

Usage: fake-command.py --out FILE --prompt-file FILE [--ratio R] [--size WxH] [--ref FILE]
Env: FAKE_CMD_LOG (a JSON line per call), FAKE_CMD_MODE ok | fail | no-file | empty-file.
"""
import argparse
import json
import os
import struct
import sys
import zlib


def png(width=12, height=8):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes((x * 3 + y * 7) % 256 for x in range(width * 3)) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--prompt-file", required=True)
ap.add_argument("--ratio")
ap.add_argument("--size")
ap.add_argument("--ref")
args = ap.parse_args()
prompt = open(args.prompt_file, encoding="utf-8").read()
log = os.environ.get("FAKE_CMD_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt, "ratio": args.ratio, "size": args.size,
                            "ref": args.ref, "out": args.out}) + "\n")
mode = os.environ.get("FAKE_CMD_MODE", "ok")
if mode == "fail":
    print("the tool failed", file=sys.stderr)
    sys.exit(2)
if mode == "no-file":
    sys.exit(0)
if mode == "empty-file":
    open(args.out, "wb").close()
    sys.exit(0)
with open(args.out, "wb") as f:
    f.write(png())
