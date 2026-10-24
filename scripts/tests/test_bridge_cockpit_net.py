# SPDX-License-Identifier: MIT
"""Contract for the one outbound fetcher of the cockpit (scripts/lib/bridge_cockpit/net.py).

Two callers read a remote document with it: the news ticker its feeds, the agents page the peers'
agent cards. Both get the same protection: a scheme allowlist that also holds for every redirect, no
redirect into the owner's own network unless the configured address is there, a size cap and a
wall-clock deadline for the whole body. The low-level tests run once per caller's settings; the
socket tests use a server on 127.0.0.1, the card tests a fake opener (a card is https only).

Run: pytest -q scripts/tests/test_bridge_cockpit_net.py
"""
from __future__ import annotations

import http.server
import sys
import threading
import time
import tracemalloc
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import a2a_peers, private_key_dir, world  # noqa: E402,F401  (fixtures come along)
from lib.bridge_cockpit import agents as ag  # noqa: E402
from lib.bridge_cockpit import net  # noqa: E402
from lib.bridge_cockpit import ticker as tk  # noqa: E402

CALLERS = {"feed": tk.FEED_FETCH, "card": ag.CARD_FETCH}
TEN_MB = 10 * 1024 * 1024


# ---------------------------------------------------------------- the settings each caller passes

def test_a_card_is_https_only_and_smaller_than_a_feed():
    assert ag.CARD_FETCH["schemes"] == ("https",) and tk.FEED_FETCH["schemes"] == ("http", "https")
    assert ag.CARD_FETCH["max_bytes"] <= 256 * 1024 < tk.FEED_FETCH["max_bytes"]
    assert ag.CARD_FETCH["accept"] == "application/json"


def test_a_feed_error_is_a_fetch_error():
    # the ticker shows any FetchError beside its feed; a card error ends up as the card's status
    assert issubclass(net.FetchError, Exception) and tk.FeedError is net.FetchError


# ---------------------------------------------------------------- redirects

def _redirect(handler, newurl, start="https://feeds.example.org/rss"):
    req = urllib.request.Request(start)
    return handler.redirect_request(req, None, 302, "Found", {}, newurl)


def _handler(caller, allow_private=False):
    return net.Redirects(schemes=CALLERS[caller]["schemes"], allow_private=allow_private)


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("target", ["https://127.0.0.1:8797/api/state", "https://192.168.1.10/x",
                                    "https://169.254.169.254/latest/meta-data/", "https://[::1]/x",
                                    "https://intranet.example/x", "https://0.0.0.0/x"])
def test_a_redirect_from_a_public_address_to_a_private_host_is_refused(monkeypatch, caller, target):
    monkeypatch.setattr(net, "_addresses", lambda host: ["10.0.0.5"] if host == "intranet.example" else ["93.184.216.34"])
    with pytest.raises(net.FetchError, match="bad redirect"):
        _redirect(_handler(caller), target)


@pytest.mark.parametrize("caller", CALLERS)
def test_a_redirect_to_a_public_host_or_from_a_private_address_is_followed(monkeypatch, caller):
    monkeypatch.setattr(net, "_addresses", lambda host: ["93.184.216.34"])
    assert _redirect(_handler(caller), "https://cdn.example.org/x").full_url == "https://cdn.example.org/x"
    assert _redirect(_handler(caller, True), "https://127.0.0.1:9000/x").full_url == "https://127.0.0.1:9000/x"


def test_a_redirect_from_https_to_http_is_refused_for_a_card_and_followed_for_a_feed(monkeypatch):
    monkeypatch.setattr(net, "_addresses", lambda host: ["93.184.216.34"])
    with pytest.raises(net.FetchError, match="bad redirect"):
        _redirect(_handler("card"), "http://peer.example.org/.well-known/agent-card.json")
    assert _redirect(_handler("feed"), "http://cdn.example.org/rss").full_url == "http://cdn.example.org/rss"


@pytest.mark.parametrize("target", ["ftp://example.org/x", "file:///etc/passwd", "https://user:pw@example.org/x"])
def test_a_redirect_to_another_scheme_or_with_userinfo_is_refused(target):
    for caller in CALLERS:
        with pytest.raises(net.FetchError, match="bad redirect"):
            _redirect(_handler(caller), target)


def test_the_configured_hosts_class_decides(monkeypatch):
    monkeypatch.setattr(net, "_addresses", lambda host: ["192.168.0.2"] if host == "nas.local" else ["93.184.216.34"])
    assert net.host_private("nas.local") and net.host_private("127.0.0.1") and net.host_private("::1")
    assert not net.host_private("example.org") and not net.host_private("93.184.216.34")


@pytest.mark.parametrize("caller", CALLERS)
def test_a_redirect_into_the_shared_address_space_of_a_tailnet_is_refused(monkeypatch, caller):
    # 100.64.0.0/10 is neither private nor reserved for ipaddress, yet not global: a tailnet lives there
    monkeypatch.setattr(net, "_addresses", lambda host: ["93.184.216.34"])
    assert net.host_private("100.101.102.103") and not net.host_private("93.184.216.34")
    with pytest.raises(net.FetchError, match="bad redirect"):
        _redirect(_handler(caller), "http://100.101.102.103/")


def test_a_url_outside_the_schemes_is_refused_before_any_connection():
    with pytest.raises(net.FetchError, match="bad address"):
        net.fetch("http://peer.example.org/card.json", **ag.CARD_FETCH)
    assert not net.url_ok("http://x.example", ("https",)) and net.url_ok("http://x.example", ("http", "https"))


# ---------------------------------------------------------------- reading the body

class Drip:
    """A response that hands out one byte per read and moves a fake clock along."""
    def __init__(self, clock: list, step: float, total: int = 10_000):
        self.clock, self.step, self.left = clock, step, total

    def read1(self, n: int = -1) -> bytes:
        self.clock[0] += self.step
        if self.left <= 0:
            return b""
        self.left -= 1
        return b"x"


@pytest.mark.parametrize("caller", CALLERS)
def test_reading_stops_at_the_wall_clock_deadline(caller):
    clock, limit = [0.0], CALLERS[caller]["timeout"]
    with pytest.raises(net.FetchError, match="timeout"):
        net.read_body(Drip(clock, 1.0), deadline=limit, max_bytes=CALLERS[caller]["max_bytes"], now=lambda: clock[0])
    assert clock[0] <= limit + 1


@pytest.mark.parametrize("caller", CALLERS)
def test_reading_stops_at_the_size_cap_and_returns_a_small_body(caller):
    clock, cap = [0.0], CALLERS[caller]["max_bytes"]

    class Big:
        reads = 0

        def read1(self, n=-1):
            Big.reads += 1
            return b"y" * n
    with pytest.raises(net.FetchError, match="too_large"):
        net.read_body(Big(), deadline=10.0, max_bytes=cap, now=lambda: clock[0])
    assert Big.reads * 65536 <= cap + 65536
    assert net.read_body(Drip(clock, 0.0, total=5), deadline=10.0, max_bytes=cap, now=lambda: clock[0]) == b"xxxxx"


@pytest.mark.parametrize("caller", CALLERS)
def test_a_gzip_body_sent_unasked_is_unpacked_within_the_cap(caller):
    import gzip
    cap = CALLERS[caller]["max_bytes"]
    body = b'{"name": "packed"}'
    assert net.ungzip(gzip.compress(body), cap) == body
    assert net.ungzip(body, cap) == body
    with pytest.raises(net.FetchError, match="too_large"):
        net.ungzip(gzip.compress(b" " * (cap + 10)), cap)
    with pytest.raises(net.FetchError, match="bad gzip"):
        net.ungzip(b"\x1f\x8bnot really", cap)


# ---------------------------------------------------------------- against a real socket

class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: ANN002 - quiet
        pass

    def do_GET(self):  # noqa: N802
        try:
            if self.path == "/big":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                block = b" " * 65536
                for _ in range(TEN_MB // len(block)):
                    self.wfile.write(block)
            elif self.path == "/drip":
                self.send_response(200)
                self.end_headers()
                for _ in range(200):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.02)
            else:
                body = b'{"name": "ok"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _local(caller, **over):
    # the socket server speaks http; the caller's other limits stay as they are
    return {**CALLERS[caller], "schemes": ("http", "https"), **over}


@pytest.mark.parametrize("caller", CALLERS)
def test_ten_megabytes_from_a_server_are_cut_at_the_cap_with_bounded_memory(server, caller):
    tracemalloc.start()
    try:
        with pytest.raises(net.FetchError, match="too_large"):
            net.fetch(server + "/big", **_local(caller))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 2 * CALLERS[caller]["max_bytes"] + 1_000_000


@pytest.mark.parametrize("caller", CALLERS)
def test_a_slow_drip_from_a_server_is_cut_at_the_deadline(server, caller):
    start = time.monotonic()
    with pytest.raises(net.FetchError, match="timeout"):
        net.fetch(server + "/drip", **_local(caller, timeout=0.5))
    assert time.monotonic() - start < 2.0


def test_a_small_body_from_a_server_comes_back(server):
    assert net.fetch(server + "/ok", **_local("card")) == b'{"name": "ok"}'


# ---------------------------------------------------------------- the card through the agents page

class _Stream:
    """A response of `total` bytes in 64 KiB chunks, counting what was handed out."""
    def __init__(self, total: int, chunk: bytes = b" " * 65536):
        self.left, self.chunk, self.handed = total, chunk, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read1(self, n=-1):
        if self.left <= 0:
            return b""
        part = self.chunk[:min(n, self.left)]
        self.left -= len(part)
        self.handed += len(part)
        return part


class _Opener:
    """What urllib.request.build_opener returns: the handlers the fetcher chose, and one scripted
    response; `redirect` makes the fake server answer with a 302 first."""
    def __init__(self, handlers, response=None, redirect=None):
        self.handlers, self.response, self.redirect, self.requests = handlers, response, redirect, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if self.redirect:
            for h in self.handlers:
                if isinstance(h, urllib.request.HTTPRedirectHandler):
                    h.redirect_request(req, None, 302, "Found", {}, self.redirect)
        return self.response


def _fake_opener(monkeypatch, **kw):
    made = {}

    def build(*handlers):
        made["opener"] = _Opener(handlers, **kw)
        return made["opener"]
    monkeypatch.setattr(net.urllib.request, "build_opener", build)
    return made


def test_a_ten_megabyte_card_is_a_card_error_and_only_the_cap_is_read(world, monkeypatch):
    monkeypatch.setattr(net, "_addresses", lambda host: ["93.184.216.34"])
    a2a_peers(world, "alpha")
    stream = _Stream(TEN_MB)
    _fake_opener(monkeypatch, response=stream)
    world.app.agents.fetch = ag.fetch_card
    world.app.agents.refresh_cards(block=True)
    peer = world.app.agents.state()["peers"][0]
    assert peer["card_error"] == "too_large" and peer["reach"] == "unreachable" and peer["card"] is None
    assert stream.handed <= ag.CARD_FETCH["max_bytes"] + 65536


@pytest.mark.parametrize("target", ["http://alpha.example/.well-known/agent-card.json",
                                    "https://127.0.0.1/.well-known/agent-card.json",
                                    "https://192.168.1.1/admin"])
def test_a_card_redirect_to_http_or_into_the_local_network_is_refused(world, monkeypatch, target):
    monkeypatch.setattr(net, "_addresses", lambda host: ["93.184.216.34"])
    a2a_peers(world, "alpha")
    _fake_opener(monkeypatch, response=_Stream(10, b'{"name": "admin"}'), redirect=target)
    world.app.agents.fetch = ag.fetch_card
    world.app.agents.refresh_cards(block=True)
    peer = world.app.agents.state()["peers"][0]
    assert peer["card_error"] == "bad redirect" and peer["card"] is None


def test_a_card_is_fetched_with_a_user_agent_of_its_own(monkeypatch):
    # an edge in front of a public agent refuses Python's default user agent (403)
    monkeypatch.setattr(net, "_addresses", lambda host: ["93.184.216.34"])
    made = _fake_opener(monkeypatch, response=_Stream(13, b'{"name": "x"}'))
    assert ag.fetch_card("https://a.example/.well-known/agent-card.json") == {"name": "x"}
    req = made["opener"].requests[0]
    ua = req.get_header("User-agent")
    assert ua and "Python-urllib" not in ua and req.get_header("Accept") == "application/json"
