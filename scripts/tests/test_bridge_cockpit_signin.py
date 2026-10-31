# SPDX-License-Identifier: MIT
"""A served cockpit behind a sign-in gateway: who a request is comes from a signed token, nothing else.

With `cockpit.served.access` set there is no owner on this server. Every request but the local health probe needs an
assertion signed by the gateway, for this application, unexpired, naming an address a workspace maps to a person.
The test keys are made here from a fixed seed, so no private key lies in the repository.

Run: pytest -q scripts/tests/test_bridge_cockpit_signin.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit_access import MARK, world  # noqa: E402,F401
from test_bridge_cockpit import WebConfigError, load_web_config  # noqa: E402
from lib.bridge_cockpit import signin as si  # noqa: E402
from lib.bridge_cockpit import server as srv  # noqa: E402
import workspace as engine  # noqa: E402

TEAM = "team.example.org"
AUD = "a" * 64
HOST = "cockpit.example.org"
NOW_S = 1_800_000_000


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def is_prime(n: int, rng: random.Random) -> bool:
    if n % 2 == 0:
        return n == 2
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(12):
        x = pow(rng.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def prime(rng: random.Random, bits: int) -> int:
    while True:
        n = rng.getrandbits(bits) | (3 << (bits - 2)) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31)) and is_prime(n, rng):
            return n


class Key:
    def __init__(self, seed: int, kid: str, bits: int = 2048):
        rng = random.Random(seed)
        self.kid, self.e = kid, 65537
        while True:
            p, q = prime(rng, bits // 2), prime(rng, bits // 2)
            phi = (p - 1) * (q - 1)
            if p != q and phi % self.e:
                break
        self.n, self.d = p * q, pow(self.e, -1, phi)

    @property
    def jwk(self) -> dict:
        size = (self.n.bit_length() + 7) // 8
        return {"kid": self.kid, "kty": "RSA", "alg": "RS256", "use": "sig", "e": b64(self.e.to_bytes(3, "big")),
                "n": b64(self.n.to_bytes(size, "big"))}

    def sign(self, message: bytes) -> bytes:
        size = (self.n.bit_length() + 7) // 8
        info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
        em = b"\x00\x01" + b"\xff" * (size - len(info) - 3) + b"\x00" + info
        return pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(size, "big")


KEY = Key(1, "one")
ROTATED = Key(2, "two")
FORGED = Key(3, "one")          # the kid of the real key, a key of its own
SHORT = Key(4, "short", bits=1024)


def token(key: Key = KEY, header: dict | None = None, **claims) -> str:
    body = {"iss": f"https://{TEAM}", "aud": [AUD], "exp": NOW_S + 600, "iat": NOW_S - 10, "nbf": NOW_S - 10,
            "email": "Pat@Example.org", "type": "app", **claims}
    body = {k: v for k, v in body.items() if v is not None}
    head = b64(json.dumps(header or {"alg": "RS256", "kid": key.kid}).encode())
    message = f"{head}.{b64(json.dumps(body).encode())}"
    return f"{message}.{b64(key.sign(message.encode()))}"


class Certs:
    def __init__(self, *keys):
        self.keys, self.calls, self.fail = list(keys), [], False

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        if self.fail:
            raise OSError("no network")
        return {"keys": [k.jwk for k in self.keys]}


def gate(certs: Certs | None = None, now=lambda: NOW_S * 1000.0) -> si.SignIn:
    return si.SignIn(si.Settings(team_domain=TEAM, aud=AUD, host=HOST), clock=now, fetch=certs or Certs(KEY))


@pytest.fixture
def served(world):  # noqa: F811
    """The world behind the gateway: `pat` signs in with an address, the owner's ways stay shut."""
    home = world.root / "workflow" / "workspaces" / "home.yaml"
    home.write_text(home.read_text(encoding="utf-8") + "logins: {pat: pat@example.org}\n", encoding="utf-8")
    world.app.cfg = srv.served_config(world.app.cfg)
    world.certs = Certs(KEY)
    world.app.sign_in = si.SignIn(si.Settings(team_domain=TEAM, aud=AUD, host=HOST),
                                  clock=lambda: NOW_S * 1000.0, fetch=world.certs)
    return world


def outside(w, path="/api/state", assertion=None, extra=None, method="GET", body=None):
    headers = {**({"Cf-Access-Jwt-Assertion": assertion} if assertion else {}), **(extra or {})}
    return w.request(method, path, body=body, headers=headers, host=HOST)


def status(result) -> int:
    return result[0]


# ------------------------------------------------------------ the token


def test_a_good_token_names_the_address_in_lower_case():
    assert gate().address(token()) == "pat@example.org"


def test_a_single_audience_string_counts():
    assert gate().address(token(aud=AUD)) == "pat@example.org"


@pytest.mark.parametrize("bad", [
    None, "", "a.b", "a.b.c.d", "x" * 20000,
    token(FORGED),
    token(aud=["b" * 64]),
    token(aud=None),
    token(iss="https://other.example.org"),
    token(iss=None),
    token(exp=NOW_S - 120),
    token(exp=None),
    token(nbf=NOW_S + 3600),
    token(email=None),
    token(email=""),
    token(email=7),
    token(header={"alg": "none", "kid": "one"}),
    token(header={"alg": "HS256", "kid": "one"}),
    token(header={"alg": "RS256", "kid": "unknown"}),
    token(header={"alg": "RS256"}),
    token(type="org"),
], ids=["none", "empty", "two-parts", "four-parts", "huge", "forged", "wrong-aud", "no-aud", "wrong-issuer", "no-issuer",
        "expired", "no-exp", "not-yet", "no-email", "blank-email", "number-email", "alg-none", "alg-hs256", "unknown-kid",
        "no-kid", "wrong-type"])
def test_a_bad_token_names_nobody(bad):
    assert gate().address(bad) is None


def test_a_changed_payload_breaks_the_signature():
    head, _, sig = token().split(".")
    other = b64(json.dumps({"iss": f"https://{TEAM}", "aud": [AUD], "exp": NOW_S + 600, "email": "boss@example.org",
                            "type": "app"}).encode())
    assert gate().address(f"{head}.{other}.{sig}") is None


def test_a_signature_with_loose_padding_is_refused():
    """The forgery of RSA signature checks that parse the padding instead of comparing all of it."""
    size = (KEY.n.bit_length() + 7) // 8
    head = b64(json.dumps({"alg": "RS256", "kid": "one"}).encode())
    message = f"{head}.{b64(json.dumps({'iss': f'https://{TEAM}', 'aud': [AUD], 'exp': NOW_S + 600, 'email': 'x@example.org', 'type': 'app'}).encode())}"
    info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message.encode()).digest()
    em = b"\x00\x01\xff\x00" + info + b"\x01" * (size - len(info) - 4)
    sig = pow(int.from_bytes(em, "big"), KEY.d, KEY.n).to_bytes(size, "big")
    assert gate().address(f"{message}.{b64(sig)}") is None


def test_a_deeply_nested_token_is_just_a_bad_token():
    deep = b64(b"[" * 5000)
    assert gate().address(f"{deep}.{deep}.{deep}") is None


def test_a_key_below_2048_bits_is_not_used():
    assert gate(Certs(SHORT)).address(token(SHORT)) is None


def test_the_keys_come_from_the_team_and_are_kept():
    certs = Certs(KEY)
    g = gate(certs)
    assert g.address(token()) and g.address(token())
    assert certs.calls == [f"https://{TEAM}/cdn-cgi/access/certs"]


def test_a_new_key_is_fetched_when_a_token_names_it():
    certs = Certs(KEY)
    now = [NOW_S * 1000.0]
    g = gate(certs, now=lambda: now[0])
    assert g.address(token())
    certs.keys = [KEY, ROTATED]
    now[0] += 120_000
    assert g.address(token(ROTATED)) == "pat@example.org"
    assert len(certs.calls) == 2


def test_unknown_keys_cannot_drive_the_fetching():
    certs = Certs(KEY)
    g = gate(certs)
    g.address(token())
    for n in range(20):
        assert g.address(token(header={"alg": "RS256", "kid": f"k{n}"})) is None
    assert len(certs.calls) == 1


def test_known_keys_outlive_a_failed_fetch():
    certs = Certs(KEY)
    now = [NOW_S * 1000.0]
    g = gate(certs, now=lambda: now[0])
    assert g.address(token())
    certs.fail = True
    now[0] += 2 * 3600 * 1000.0
    assert g.address(token(exp=NOW_S + 3 * 3600)) == "pat@example.org"


def test_no_keys_means_nobody():
    certs = Certs(KEY)
    certs.fail = True
    assert gate(certs).address(token()) is None


def test_keys_past_their_end_are_dropped_when_the_team_stays_silent():
    certs = Certs(KEY)
    now = [NOW_S * 1000.0]
    g = gate(certs, now=lambda: now[0])
    assert g.address(token())
    certs.fail = True
    now[0] += 8 * 24 * 3600 * 1000.0
    assert g.address(token(exp=NOW_S + 9 * 24 * 3600)) is None


# ------------------------------------------------------------ the config


def test_without_the_block_nothing_changes(tmp_path):
    assert load_web_config(tmp_path, {"cockpit": {"enabled": True}}).served_access is None


def test_the_block_is_read(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"served": {"access": {"team_domain": TEAM, "aud": AUD, "host": HOST}}}})
    assert (cfg.served_access.team_domain, cfg.served_access.aud, cfg.served_access.host) == (TEAM, AUD, HOST)
    assert not cfg.config_warnings


@pytest.mark.parametrize("block", [
    {"aud": AUD, "host": HOST}, {"team_domain": TEAM, "host": HOST}, {"team_domain": TEAM, "aud": AUD},
    {"team_domain": "https://x.example.org/", "aud": AUD, "host": HOST}, {"team_domain": TEAM, "aud": "short", "host": HOST},
    {"team_domain": TEAM, "aud": AUD, "host": "127.0.0.1"},
    {"team_domain": TEAM, "aud": AUD, "host": "127.0.0.1:80"}, {"team_domain": TEAM, "aud": AUD, "host": "localhost"},
    {"team_domain": TEAM, "aud": AUD, "host": HOST, "owner": True}, "yes"])
def test_a_half_block_stops_the_start_instead_of_opening_it(tmp_path, block):
    with pytest.raises(WebConfigError):
        load_web_config(tmp_path, {"cockpit": {"served": {"access": block}}})


# ------------------------------------------------------------ the mapping


def test_a_workspace_maps_an_address_to_its_member(served):
    assert served.app.access.person_of("pat@example.org") == "pat"
    assert served.app.access.person_of("nobody@example.org") is None


def test_one_address_on_two_people_opens_for_neither(served):
    job = served.root / "workflow" / "workspaces" / "job.yaml"
    job.write_text(job.read_text(encoding="utf-8") + "members: [sam]\nlogins: {sam: pat@example.org}\n", encoding="utf-8")
    assert served.app.access.person_of("pat@example.org") is None


def test_a_login_needs_a_member():
    defs = {"x": {"id": "x", "area": "X", "members": ["pat"], "logins": {"sam": "sam@example.org"}}}
    assert any("logins" in p for p in engine.rule_problems(defs, "x"))


# ------------------------------------------------------------ the requests


def test_a_signed_person_gets_their_own_cut(served):
    code, _, data = outside(served, assertion=token())
    assert code == 200 and MARK.encode() not in data


@pytest.mark.parametrize("name,assertion,code", [
    ("none", None, 403), ("forged", token(FORGED), 403), ("expired", token(exp=NOW_S - 120), 403),
    ("wrong-aud", token(aud=["b" * 64]), 403), ("wrong-issuer", token(iss="https://o.example.org"), 403),
    ("unknown-address", token(email="nobody@example.org"), 403)])
def test_nothing_opens_without_a_good_token(served, name, assertion, code):
    for path in ("/", "/api/state", "/api/bootstrap", "/app.js", "/favicon.ico", "/api/health", "/api/events"):
        assert status(outside(served, path, assertion)) == code, path


def test_the_address_header_alone_counts_for_nothing(served):
    got = outside(served, extra={"Cf-Access-Authenticated-User-Email": "pat@example.org"})
    assert status(got) == 403
    got = outside(served, assertion=token(email="nobody@example.org"),
                  extra={"Cf-Access-Authenticated-User-Email": "pat@example.org"})
    assert status(got) == 403


def test_an_unknown_address_gets_a_page_that_says_so(served):
    code, _, data = outside(served, "/", token(email="nobody@example.org"))
    assert code == 403 and b"<html" in data and b"nobody@example.org" not in data


def test_the_owner_cookie_opens_nothing(served):
    cookie = served.cookie
    assert status(outside(served, extra=cookie)) == 403
    assert status(served.request("GET", "/api/state", headers=cookie)) == 403
    got = outside(served, assertion=token(), extra=cookie)
    assert status(got) == 200 and MARK.encode() not in got[2]


def test_a_person_cookie_alone_opens_nothing(served):
    cookie = {"Cookie": f"{served.app.cookie_name}={served.app.session_value(person='pat')}"}
    assert status(outside(served, extra=cookie)) == 403


def test_a_login_code_does_not_work_here(served):
    code = srv.login_code(served.app.token, served.clock())
    got = outside(served, f"/?code={code}", token())
    assert b"set-cookie" not in repr(got[1]).lower().encode()
    assert status(outside(served, f"/?code={code}")) == 403
    assert status(served.request("GET", f"/?code={code}")) == 403


def test_a_token_needs_the_public_name(served):
    assert status(served.request("GET", "/api/state", headers={"Cf-Access-Jwt-Assertion": token()})) == 403


def test_the_local_probe_stays_and_says_little(served):
    code, _, data = served.request("GET", "/api/health")
    assert code == 200 and json.loads(data)["ok"] is True
    assert status(served.request("GET", "/")) == 403


def test_no_other_name_is_answered(served):
    assert status(served.request("GET", "/api/state", headers={"Cf-Access-Jwt-Assertion": token()}, host="evil.example.org")) == 403


def test_nothing_sets_a_cookie(served):
    for path in ("/", "/api/bootstrap", "/api/state"):
        assert "set-cookie" not in {k.lower() for k in dict(outside(served, path, token())[1])}


def post(w, path, payload, assertion, origin=f"https://{HOST}", csrf="own"):
    csrf = w.app.csrf_of("pat") if csrf == "own" else csrf
    extra = {"Content-Type": "application/json", **({"Origin": origin} if origin else {}), **({"X-Bridge-Token": csrf} if csrf else {})}
    return outside(w, path, assertion, extra, "POST", json.dumps(payload).encode())


def error_of(result) -> str:
    return json.loads(result[2])["error"]["code"]


ACTION = {"verb": "priority", "args": {"key": "task:home-task", "value": "P1"}}


def test_a_post_of_a_signed_person_passes(served):
    got = post(served, "/api/action", ACTION, token())
    assert got[0] == 200, got[2]


@pytest.mark.parametrize("kw,code", [
    ({"origin": "http://127.0.0.1:1"}, "forbidden_origin"), ({"origin": f"http://{HOST}"}, "forbidden_origin"),
    ({"origin": "https://evil.example.org"}, "forbidden_origin"), ({"origin": None}, "forbidden_origin"),
    ({"csrf": None}, "unauthorized"), ({"csrf": "wrong"}, "unauthorized")], ids=str)
def test_a_post_keeps_its_checks(served, kw, code):
    assert error_of(post(served, "/api/action", ACTION, token(), **kw)) == code


def test_a_post_needs_a_token(served):
    assert error_of(post(served, "/api/action", ACTION, None)) == "not_signed_in"
    assert error_of(post(served, "/api/action", ACTION, token(FORGED))) == "not_signed_in"


def test_the_owners_csrf_does_nothing_for_a_person(served):
    assert error_of(post(served, "/api/action", ACTION, token(), csrf=served.app.csrf)) == "unauthorized"


def test_an_address_taken_off_a_workspace_is_out_at_once(served):
    assert status(outside(served, assertion=token())) == 200
    home = served.root / "workflow" / "workspaces" / "home.yaml"
    home.write_text(home.read_text(encoding="utf-8").replace("logins: {pat: pat@example.org}\n", ""), encoding="utf-8")
    assert status(outside(served, assertion=token())) == 403


def test_the_live_channel_is_cut_for_the_signed_person(served):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", served.port, timeout=5)
    conn.request("GET", "/api/events", headers={"Host": HOST, "Cf-Access-Jwt-Assertion": token()})
    resp = conn.getresponse()
    assert resp.status == 200
    buf = b""
    while b"event: state" not in buf or not buf.endswith(b"\n\n"):
        buf += resp.read1(65536)
    conn.close()
    assert MARK.encode() not in buf


def test_no_address_reaches_a_person_or_the_page(served):
    for path in ("/api/state", "/api/bootstrap"):
        assert b"@example.org" not in outside(served, path, token())[2]


def test_the_server_builds_the_gate_from_a_served_config(tmp_path, world):  # noqa: F811
    block = {"cockpit": {"served": {"access": {"team_domain": TEAM, "aud": AUD, "host": HOST}}}}
    cfg = load_web_config(tmp_path, block)
    assert srv.App(world.root, cfg, world.runner, tmp_path / "plain", world.clock, "k" * 43).sign_in is None
    served = srv.App(world.root, srv.served_config(cfg), world.runner, tmp_path / "served", world.clock, "k" * 43)
    assert served.sign_in.settings.host == HOST


def test_without_the_gate_the_owner_stays_as_he_was(world):  # noqa: F811
    assert world.app.sign_in is None
    assert world.request("GET", "/api/state", headers=world.cookie)[0] == 200
    assert world.request("GET", "/api/state", headers={"Cf-Access-Jwt-Assertion": token()})[0] in (401, 403)


def test_a_person_cookie_still_works_without_the_gate(world):  # noqa: F811
    cookie = {"Cookie": f"{world.app.cookie_name}={world.app.session_value(person='pat')}"}
    assert world.request("GET", "/api/state", headers=cookie)[0] == 200
