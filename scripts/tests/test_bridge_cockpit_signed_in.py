# SPDX-License-Identifier: MIT
"""Contract for staying signed in to the cockpit (docs/bridge-cockpit.md, Open it by its address).

- a session cookie lasts COOKIE_AGE_S (30 days); a page in use gets a fresh one at most once per COOKIE_RENEW_S
  (a day), with the same attributes, for the same owner or the same person;
- a refused cookie is never renewed, and a renewal never sticks to the next answer of a kept-alive connection;
- the page a browser without a session sees tells "your sign-in has expired" (a cookie made with this key that ran
  out) from "not signed in yet", in the cockpit's language, styled without inline style under the same CSP;
- behind a sign-in gateway nothing is renewed: there the gateway's token decides, never a cookie.

Run: pytest -q scripts/tests/test_bridge_cockpit_signed_in.py
"""
from __future__ import annotations

import http.client
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import RELAY_OFF, World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import server as srv  # noqa: E402

DAY = 86400


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


def cookie_at(world, age_days: float, person: str | None = None) -> dict:
    issued = world.app.now_s() - int(age_days * DAY)
    return {"Cookie": f"{world.app.cookie_name}={world.app.session_value(issued, person=person)}"}


def set_cookie_value(headers: dict) -> str:
    return headers["Set-Cookie"].split(";")[0].partition("=")[2]


def test_the_ages_are_thirty_days_and_one_day():
    assert srv.COOKIE_AGE_S == 30 * DAY and srv.COOKIE_RENEW_S == DAY


def test_a_session_lasts_thirty_days(world):
    assert world.request("GET", "/api/bootstrap", headers=cookie_at(world, 29))[0] == 200
    assert world.request("GET", "/api/bootstrap", headers=cookie_at(world, 31))[0] == 401


def test_a_used_session_is_renewed_once_a_day_at_most(world):
    assert "Set-Cookie" not in world.request("GET", "/api/bootstrap", headers=cookie_at(world, 0.5))[1]
    status, headers, _ = world.request("GET", "/api/bootstrap", headers=cookie_at(world, 2))
    assert status == 200
    value = set_cookie_value(headers)
    assert world.app.session_ok(value) and value == world.app.session_value()
    for part in ("HttpOnly", "SameSite=Strict", "Path=/", f"Max-Age={30 * DAY}"):
        assert part in headers["Set-Cookie"]


def test_the_login_link_sets_the_same_cookie(world):
    code = srv.login_code(world.app.token, world.clock())
    status, headers, _ = world.request("GET", f"/?code={code}")
    assert status == 303 and f"Max-Age={30 * DAY}" in headers["Set-Cookie"]


def test_a_persons_session_is_renewed_as_that_person(world):
    status, headers, _ = world.request("GET", "/", headers=cookie_at(world, 2, person="pat"))
    assert "Set-Cookie" in headers, status
    value = set_cookie_value(headers)
    assert world.app.session_person(value) == "pat" and not world.app.session_ok(value)


def test_a_refused_session_is_not_renewed(world):
    status, headers, _ = world.request("GET", "/api/bootstrap", headers=cookie_at(world, 31))
    assert status == 401 and "Set-Cookie" not in headers
    forged = {"Cookie": f"{world.app.cookie_name}={world.app.now_s() - 2 * DAY}.{'0' * 40}"}
    status, headers, _ = world.request("GET", "/api/bootstrap", headers=forged)
    assert status == 401 and "Set-Cookie" not in headers


def test_a_renewal_does_not_stick_to_the_next_request_on_the_same_connection(world):
    conn = http.client.HTTPConnection("127.0.0.1", world.port, timeout=5)
    host = {"Host": f"127.0.0.1:{world.port}"}
    conn.request("GET", "/api/bootstrap", headers={**host, **cookie_at(world, 2)})
    first = conn.getresponse()
    first.read()
    conn.request("GET", "/api/bootstrap", headers={**host, **cookie_at(world, 0)})
    second = conn.getresponse()
    second.read()
    conn.close()
    assert first.getheader("Set-Cookie") and not second.getheader("Set-Cookie")


def test_the_sign_in_page_tells_expired_from_never_signed_in(world):
    never = world.request("GET", "/")
    expired = world.request("GET", "/", headers=cookie_at(world, 31))
    assert never[0] == expired[0] == 401
    assert b"Sign in" in never[2] and b"expired" not in never[2]
    assert b"expired" in expired[2] and b"nothing is broken" in expired[2]
    for page in (never[2], expired[2]):
        assert b"/cockpit" in page and b"bridge-cockpit.py url" in page


def test_a_persons_run_out_cookie_also_reads_as_expired(world):
    assert b"expired" in world.request("GET", "/", headers=cookie_at(world, 31, person="pat"))[2]


def test_a_forged_old_cookie_reads_as_never_signed_in(world):
    other = {"Cookie": f"{world.app.cookie_name}=1000.{'0' * 40}"}
    assert b"expired" not in world.request("GET", "/", headers=other)[2]


def test_the_sign_in_page_speaks_the_language_of_the_cockpit(tmp_path):
    w = World(tmp_path, config=RELAY_OFF.replace("language: en", "language: de"))
    try:
        page = w.request("GET", "/", headers=cookie_at(w, 31))[2].decode("utf-8")
        assert 'lang="de"' in page and "abgelaufen" in page and "nichts ist kaputt" in page
    finally:
        w.close()


def test_the_sign_in_page_gets_its_look_without_a_session_and_keeps_the_policy(world):
    status, headers, page = world.request("GET", "/")
    assert status == 401 and "style=" not in page.decode("utf-8") and b"<style" not in page
    assert "style-src 'self'" in headers["Content-Security-Policy"]
    real = (ROOT / "scripts" / "web" / "signin.css").read_bytes()
    (world.root / "scripts" / "web" / "signin.css").write_bytes(real)      # the test Bridge serves its own web folder
    got = world.request("GET", "/signin.css")
    assert got[0] == 200 and b".signin" in got[2]
    assert world.request("GET", "/colors.css")[0] != 401  # the Bridge's colours, so the page wears its brand
    assert world.request("GET", "/app.js")[0] == 401      # the rest of the page stays behind the sign-in
