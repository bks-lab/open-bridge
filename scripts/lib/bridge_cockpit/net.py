# SPDX-License-Identifier: MIT
"""The one outbound fetcher of the cockpit: a GET for a remote document someone configured.

The ticker reads its feeds with it, the agents page the peers' agent cards. Each caller passes its
own settings (accepted schemes, Accept header, user agent, size cap, timeout); the protection is the
same for both: the scheme allowlist also holds for every redirect, a redirect may not lead into the
owner's own network unless the configured address is there, the body stops at max_bytes (a gzip body
too, once unpacked) and the whole fetch at a wall-clock deadline, so a server dripping bytes cannot
keep a thread busy.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Callable

URL_MAX = 500
MAX_REDIRECTS = 3
CHUNK = 65536


class FetchError(Exception):
    """A document that cannot be read; the message is short and shown beside what it belongs to."""


def url_ok(url: Any, schemes: tuple[str, ...] = ("http", "https"), max_len: int = URL_MAX) -> bool:
    """One of `schemes`, a host, no userinfo, no whitespace or control character, at most max_len."""
    if not isinstance(url, str) or not url or len(url) > max_len or re.search(r"[\s\x00-\x1f\x7f]", url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme in schemes and bool(host) and "@" not in parts.netloc


def _addresses(host: str) -> list[str]:
    """Every address the host resolves to; an empty list when it does not resolve."""
    try:
        return [info[4][0] for info in socket.getaddrinfo(host, None)]
    except (OSError, UnicodeError):
        return []


def host_private(host: str | None) -> bool:
    """True when the host is, or resolves to, a loopback, private, link-local, multicast, reserved or
    unspecified address (any one of its addresses is enough)."""
    if not host:
        return False
    try:
        candidates = [ipaddress.ip_address(host)]
    except ValueError:
        candidates = []
        for raw in _addresses(host):
            try:
                candidates.append(ipaddress.ip_address(raw.split("%", 1)[0]))
            except ValueError:
                continue
    # not is_global catches what the flags above miss, the shared space of 100.64.0.0/10 a tailnet uses
    return any(a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved
               or a.is_unspecified or not a.is_global for a in candidates)


class Redirects(urllib.request.HTTPRedirectHandler):
    """A redirect keeps to the caller's schemes and may not lead into the owner's own network unless
    the configured address lives there: the owner chose that address, the server did not choose the
    next one."""
    max_redirections = MAX_REDIRECTS

    def __init__(self, schemes: tuple[str, ...] = ("http", "https"), allow_private: bool = False):
        super().__init__()
        self.schemes = schemes
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not url_ok(newurl, self.schemes):
            raise FetchError("bad redirect")
        if not self.allow_private and host_private(urllib.parse.urlsplit(newurl).hostname):
            raise FetchError("bad redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_body(response: Any, deadline: float, max_bytes: int, now: Callable[[], float] = time.monotonic) -> bytes:
    """Read the body in chunks until the end, the wall-clock deadline or max_bytes, whichever comes
    first. read1 returns after one socket read, so a server dripping bytes cannot stretch a call."""
    read = getattr(response, "read1", None) or response.read
    chunks, total = [], 0
    while True:
        if now() > deadline:
            raise FetchError("timeout")
        chunk = read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FetchError("too_large")
        chunks.append(chunk)
    if now() > deadline:
        raise FetchError("timeout")
    return b"".join(chunks)


def ungzip(data: bytes, max_bytes: int) -> bytes:
    """A body that is gzip although the request asked for no encoding (a server or CDN may send it anyway),
    unpacked to at most max_bytes; anything else comes back as it was."""
    if data[:2] != b"\x1f\x8b":
        return data
    unpack = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = unpack.decompress(data, max_bytes + 1)
    except zlib.error:
        raise FetchError("bad gzip") from None
    if len(out) > max_bytes or unpack.unconsumed_tail:
        raise FetchError("too_large")
    return out


def fetch(url: str, *, schemes: tuple[str, ...], accept: str, user_agent: str, max_bytes: int,
          timeout: float) -> bytes:
    """GET one document: only `schemes`, at most MAX_REDIRECTS redirects (none into a private network
    unless the address is there), `timeout` seconds of wall clock for the whole body, max_bytes."""
    if not url_ok(url, schemes):
        raise FetchError("bad address")
    deadline = time.monotonic() + timeout
    allow_private = host_private(urllib.parse.urlsplit(url).hostname)
    opener = urllib.request.build_opener(Redirects(schemes=schemes, allow_private=allow_private))
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": accept})
    try:
        with opener.open(request, timeout=timeout) as response:
            data = ungzip(read_body(response, deadline, max_bytes), max_bytes)
    except FetchError:
        raise
    except urllib.error.HTTPError as error:
        raise FetchError(f"HTTP {error.code}") from None
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", "")
        raise FetchError("timeout" if isinstance(reason, TimeoutError) else f"unreachable: {str(reason)[:80]}") from None
    except TimeoutError:
        raise FetchError("timeout") from None
    except (OSError, ValueError) as error:
        raise FetchError(str(error)[:80] or "failed") from None
    return data
