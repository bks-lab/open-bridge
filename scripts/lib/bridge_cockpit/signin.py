# SPDX-License-Identifier: MIT
"""Who a request of a served cockpit is: the signed token of the sign-in gateway in front of it (Cloudflare Access).

`cockpit.served.access` turns this on. The gateway signs an assertion for every request it lets through; only that
counts here, never the plain address header it also sends, which anyone reaching the port could write.

RS256 needs no library: a signature is checked by raising it to the public exponent and comparing the whole padded
result with what it must be. The comparison covers every byte, so the old forgery of checks that parse the padding
has nothing to hold on to. Verifying needs no secret, so nothing here depends on timing.

The keys come from the team's certs address and are kept. A token naming an unknown key fetches once, no more often
than FETCH_GAP_S, so a stranger's made-up key ids cannot drive the fetching. A failed fetch keeps the keys known so
far for KEEP_S, longer than a retired key stays good at the gateway's side, and then there are none: no keys, nobody.
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import hmac
import json
import re
import threading
import urllib.request
from typing import Any, Callable

MAX_TOKEN = 8192
MAX_CERTS = 256 * 1024
MIN_KEY_BITS = 2048
SKEW_S = 30                # clocks differ a little
REFRESH_S = 3600           # how long fetched keys count as fresh
FETCH_GAP_S = 60           # the least time between two fetches
KEEP_S = 7 * 24 * 3600     # how long known keys outlive a silent certs address
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
HOST_RE = re.compile(r"^(?=.{1,253}\Z)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+\Z")
AUD_RE = re.compile(r"^[a-f0-9]{32,128}\Z")


@dataclasses.dataclass(frozen=True)
class Settings:
    team_domain: str
    aud: str
    host: str


def settings_problem(block: Any) -> str | None:
    """What is wrong with `cockpit.served.access`. A half block must stop the start, never open the server."""
    if not isinstance(block, dict):
        return "must be a mapping"
    extra = sorted(set(block) - {"team_domain", "aud", "host"})
    if extra:
        return f"has unknown keys: {', '.join(extra)}"
    for name in ("team_domain", "host"):
        if not isinstance(block.get(name), str) or not HOST_RE.match(block[name]) or block[name].rsplit(".", 1)[-1].isdigit():
            return f"{name} must be a plain host name"
    if not isinstance(block.get("aud"), str) or not AUD_RE.match(block["aud"]):
        return "aud must be the application's audience tag"
    return None


def fetch_certs(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bridge-cockpit"}), timeout=5) as resp:
        return json.loads(resp.read(MAX_CERTS + 1)[:MAX_CERTS])


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii") + b"=" * (-len(text) % 4), altchars=b"-_", validate=True)


def key_of(jwk: Any) -> tuple[int, int] | None:
    """(n, e) of a usable public key"""
    if not isinstance(jwk, dict) or jwk.get("kty") != "RSA" or jwk.get("alg", "RS256") != "RS256":
        return None
    try:
        n, e = int.from_bytes(unb64(jwk["n"]), "big"), int.from_bytes(unb64(jwk["e"]), "big")
    except (KeyError, TypeError, ValueError, AttributeError, binascii.Error):
        return None
    return (n, e) if n.bit_length() >= MIN_KEY_BITS and e >= 3 and e % 2 else None


def rs256_ok(message: bytes, signature: bytes, n: int, e: int) -> bool:
    size = (n.bit_length() + 7) // 8
    value = int.from_bytes(signature, "big")
    if len(signature) != size or value >= n:
        return False
    info = SHA256_PREFIX + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(info) - 3) + b"\x00" + info
    return hmac.compare_digest(pow(value, e, n).to_bytes(size, "big"), expected)


class SignIn:
    def __init__(self, settings: Settings, clock: Callable[[], float], fetch: Callable[[str], dict] = fetch_certs):
        self.settings = settings
        self.clock = clock                     # milliseconds, like the server's
        self.fetch = fetch
        self.lock = threading.Lock()
        self.keys: dict[str, tuple[int, int]] = {}
        self.fetched_s: float | None = None    # when keys last arrived
        self.tried_s: float | None = None      # when a fetch was last tried

    def now_s(self) -> float:
        return self.clock() / 1000

    def refresh(self, now: float) -> None:
        self.tried_s = now
        try:
            found = {k["kid"]: key for k in (self.fetch(f"https://{self.settings.team_domain}/cdn-cgi/access/certs") or {}).get("keys", [])
                     if isinstance(k, dict) and isinstance(k.get("kid"), str) and (key := key_of(k))}
        except Exception:      # the network, a bad answer: the keys known so far stay until KEEP_S
            return
        if found:
            self.keys, self.fetched_s = found, now

    def key(self, kid: str) -> tuple[int, int] | None:
        now = self.now_s()
        with self.lock:
            stale = self.fetched_s is None or now - self.fetched_s >= REFRESH_S
            may = self.tried_s is None or now - self.tried_s >= FETCH_GAP_S
            if may and (stale or kid not in self.keys):
                self.refresh(now)
            if self.fetched_s is None or now - self.fetched_s >= KEEP_S:
                self.keys = {}
            return self.keys.get(kid)

    def claims(self, assertion: str | None) -> dict | None:
        """The claims of a token this gateway signed for this application, right now. None for anything else."""
        if not assertion or len(assertion) > MAX_TOKEN:
            return None
        head, sep, rest = assertion.partition(".")
        body, sep2, sig = rest.partition(".")
        if not (sep and sep2) or "." in sig:
            return None
        try:
            header, claims, signature = json.loads(unb64(head)), json.loads(unb64(body)), unb64(sig)
        except (ValueError, binascii.Error, UnicodeError, RecursionError):
            return None
        if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "RS256" \
                or not isinstance(header.get("kid"), str):
            return None
        key = self.key(header["kid"])
        if not key or not rs256_ok(f"{head}.{body}".encode("ascii"), signature, *key):
            return None
        now = self.now_s()
        aud, exp, nbf = claims.get("aud"), claims.get("exp"), claims.get("nbf", 0)
        if claims.get("iss") != f"https://{self.settings.team_domain}" \
                or self.settings.aud not in (aud if isinstance(aud, list) else [aud]) \
                or not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp + SKEW_S <= now \
                or not isinstance(nbf, (int, float)) or isinstance(nbf, bool) or nbf - SKEW_S > now \
                or claims.get("type", "app") != "app":
            return None
        return claims

    def address(self, assertion: str | None) -> str | None:
        """The address a good token names, in lower case"""
        claims = self.claims(assertion)
        email = claims.get("email") if claims else None
        return email.strip().lower() if isinstance(email, str) and email.strip() else None
