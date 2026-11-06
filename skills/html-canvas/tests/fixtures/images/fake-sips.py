#!/usr/bin/env python3
"""A stand-in for macOS sips in the gen-images tests: logs argv, writes a small output.

Usage as the tests call it: sips [--resampleWidth N] [-s format F] [-s formatOptions X] IN --out OUT
Env: FAKE_SIPS_LOG (a JSON line per call).
"""
import json
import os
import struct
import sys
import zlib

args = sys.argv[1:]
log = os.environ.get("FAKE_SIPS_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": args}) + "\n")
out = args[args.index("--out") + 1]
if "format" in args and args[args.index("format") + 1] == "jpeg":
    data = b"\xff\xd8\xff\xe0" + b"fake-sips-jpeg" + b"\xff\xd9"
else:
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x10\x20\x30\x40" * 10 for _ in range(5))
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 10, 5, 8, 6, 0, 0, 0))
            + chunk(b"tEXt", b"tag\x00fake-sips") + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
with open(out, "wb") as f:
    f.write(data)
