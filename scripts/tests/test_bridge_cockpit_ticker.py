# SPDX-License-Identifier: MIT
"""Contract for the news ticker of the cockpit start page (scripts/lib/bridge_cockpit/ticker.py).

The ticker reads feeds the owner configured (cockpit.ticker in bridge-config.yaml, overrides from the
settings page in .bridge/cockpit/ticker.json) and lets Claude Haiku pick and shorten them, but only on a
button press. Hermetic: the feed fetcher is a dict-backed fake, claude is the FakeRunner's, no network.

Run: pytest -q scripts/tests/test_bridge_cockpit_ticker.py
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, fail, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib import model_route as mr  # noqa: E402
from lib.bridge_cockpit import ticker as tk  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

FEED_A = "https://example.org/a.xml"
FEED_B = "https://example.org/b.xml"
FEED_C = "https://example.org/c.xml"

# the fixtures' feeds carry fixed dates in early October: the age filter is off here and tested on its own
TICKER_CFG = ("cockpit:\n  enabled: true\n  language: en\n  relay: true\n  ticker:\n    enabled: true\n"
              "    smart: {{max_age_hours: 0}}\n{more}"
              "workplace:\n  control:\n    name: Control\n")
FEEDS_CFG = ("    feeds:\n"
             f"      - {{id: alpha, name: Alpha, url: \"{FEED_A}\"}}\n"
             f"      - {{id: beta, name: Beta, url: \"{FEED_B}\"}}\n")


def rss(items: list[tuple[str, str, str | None]]) -> bytes:
    body = "".join(f"<item><title>{t}</title><link>{link}</link>"
                   + (f"<pubDate>{d}</pubDate>" if d else "") + "</item>" for t, link, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode()


ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title>
<entry><title>Atom older</title><link rel="alternate" href="https://example.org/atom/1"/>
<updated>2026-10-01T08:00:00Z</updated></entry>
<entry><title type="html">&lt;b&gt;Atom newer&lt;/b&gt;</title><link href="/atom/2"/><link rel="enclosure" href="https://example.org/x.mp3"/>
<published>2026-10-02T08:00:00+00:00</published></entry>
</feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/">
<channel><title>R</title></channel>
<item><title>RDF one</title><link>https://example.org/rdf/1</link></item>
<item><title>RDF two</title><link>https://example.org/rdf/2</link></item>
</rdf:RDF>"""


class FakeFetch:
    def __init__(self, pages: dict | None = None):
        self.pages = dict(pages or {})
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        value = self.pages.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise tk.FeedError("not found")
        return value


def standard_pages() -> dict:
    return {
        FEED_A: rss([("A one", "https://example.org/a/1", "Mon, 05 Oct 2026 10:00:00 GMT"),
                     ("A two", "https://example.org/a/2", "Tue, 06 Oct 2026 10:00:00 GMT")]),
        FEED_B: rss([("B one", "https://example.org/b/1", "Wed, 07 Oct 2026 10:00:00 GMT")]),
    }


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


@pytest.fixture
def tworld(tmp_path, request):
    w = World(tmp_path, config=TICKER_CFG.format(more=getattr(request, "param", FEEDS_CFG)))
    w.app.ticker.fetch = FakeFetch(standard_pages())
    yield w
    w.close()


def wait_for(cond, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def events(client) -> list[tuple[str, dict]]:
    out = []
    while not client.queue.empty():
        name, data = client.queue.get_nowait()
        out.append((name, json.loads(data)))
    return out


# ---------------------------------------------------------------- 1 defaults

def test_without_a_ticker_block_it_is_off_with_the_default_feeds(world):
    state = world.app.state_payload()["ticker"]
    assert state["enabled"] is False and state["items"] == []
    assert len(state["settings"]["feeds"]) == 6 and state["settings"]["feeds"] == tk.DEFAULT_FEEDS
    assert state["overridden"] == []


def test_config_parsing_keeps_the_default_for_a_bad_key_and_skips_a_bad_feed(tmp_path):
    (tmp_path / "bridge-config.yaml").write_text(
        "cockpit:\n  ticker:\n    enabled: true\n    max_items: 4000\n    speed: warp\n    per_feed: 3\n"
        "    feeds:\n      - {id: good, name: Good, url: 'https://example.org/g'}\n"
        "      - {id: bad, name: Bad, url: 'ftp://example.org/x'}\n"
        "      - {id: good, name: Twice, url: 'https://example.org/t'}\n"
        "    editor:\n      max_picks: 0\n      interests: AI agents\n", encoding="utf-8")
    t = load_web_config(tmp_path).ticker
    assert t["enabled"] is True and t["max_items"] == 30 and t["speed"] == "normal" and t["per_feed"] == 3
    assert [f["id"] for f in t["feeds"]] == ["good"]
    assert t["editor"]["max_picks"] == 12 and t["editor"]["interests"] == "AI agents"
    (tmp_path / "bridge-config.yaml").write_text(
        "cockpit:\n  ticker:\n    feeds:\n      - {id: bad, name: Bad, url: 'javascript:alert(1)'}\n", encoding="utf-8")
    assert load_web_config(tmp_path).ticker["feeds"] == tk.DEFAULT_FEEDS


# ---------------------------------------------------------------- 2 strict validation

@pytest.mark.parametrize("change, field", [
    ({"feeds": [{"id": "x", "name": "X", "url": "ftp://example.org/f"}]}, "feeds[0].url"),
    ({"feeds": [{"id": "x", "name": "X", "url": "javascript:alert(1)"}]}, "feeds[0].url"),
    ({"feeds": [{"id": "x", "name": "X", "url": "file:///etc/passwd"}]}, "feeds[0].url"),
    ({"feeds": [{"id": "x", "name": "X", "url": "https://user:pw@example.org/f"}]}, "feeds[0].url"),
    ({"feeds": [{"id": "x", "name": "X", "url": "https://example.org/a b"}]}, "feeds[0].url"),
    ({"feeds": [{"id": "Bad_Id", "name": "X", "url": FEED_A}]}, "feeds[0].id"),
    ({"feeds": [{"id": "x", "name": "X", "url": FEED_A}, {"id": "x", "name": "Y", "url": FEED_B}]}, "feeds[1].id"),
    ({"feeds": [{"id": f"f{i}", "name": "F", "url": FEED_A} for i in range(21)]}, "feeds"),
    ({"feeds": [{"id": "x", "name": "", "url": FEED_A}]}, "feeds[0].name"),
    ({"editor": {"interests": "x" * 501}}, "editor.interests"),
    ({"editor": {"max_picks": 41}}, "editor.max_picks"),
    ({"status": {"kinds": ["running", "bogus"]}}, "status.kinds"),
    ({"max_items": 4}, "max_items"),
    ({"speed": "warp"}, "speed"),
    ({"enabled": "yes"}, "enabled"),
])
def test_normalize_rejects_with_the_field(change, field):
    with pytest.raises(tk.TickerSettingsError) as caught:
        tk.normalize(change, tk.defaults())
    assert caught.value.field == field


def test_normalize_drops_unknown_keys_and_orders_kinds():
    out = tk.normalize({"nope": 1, "status": {"kinds": ["notes", "running", "notes"], "x": 1}}, tk.defaults())
    assert "nope" not in out and out["status"]["kinds"] == ["running", "notes"]
    assert out["feeds"] == tk.DEFAULT_FEEDS


# ---------------------------------------------------------------- 3 settings round trip

def test_ticker_settings_round_trip_writes_only_the_changes_beside_the_config(tworld):
    config = (tworld.root / "bridge-config.yaml").read_bytes()
    client = tworld.app.hub.add()
    r = tworld.act("ticker_settings", settings={"speed": "fast", "max_items": 30, "editor": {"interests": "agents"}})
    saved = json.loads((tworld.state / "ticker.json").read_text(encoding="utf-8"))
    assert set(saved) == {"speed", "editor"} and saved["speed"] == "fast"
    assert saved["editor"]["interests"] == "agents" and saved["editor"]["max_picks"] == 12
    assert r["ticker"]["overridden"] == ["editor", "speed"]
    assert r["ticker"]["settings"]["speed"] == "fast" and r["ticker"]["defaults"]["speed"] == "normal"
    assert any(name == "ticker" for name, _ in events(client))
    assert (tworld.root / "bridge-config.yaml").read_bytes() == config
    # a later change merges with the stored one
    tworld.act("ticker_settings", settings={"editor": {"max_picks": 5}})
    s = tworld.app.ticker.settings()
    assert (s["editor"]["interests"], s["editor"]["max_picks"], s["speed"]) == ("agents", 5, "fast")
    r = tworld.act("ticker_settings_reset")
    assert json.loads((tworld.state / "ticker.json").read_text(encoding="utf-8")) == {}
    assert r["ticker"]["overridden"] == [] and r["ticker"]["settings"]["speed"] == "normal"
    assert (tworld.root / "bridge-config.yaml").read_bytes() == config


def test_ticker_settings_reject_a_bad_value_with_400_and_the_field(tworld):
    with pytest.raises(ActionError) as caught:
        tworld.act("ticker_settings", settings={"feeds": [{"id": "x", "name": "X", "url": "javascript:x"}]})
    assert (caught.value.status, caught.value.code, caught.value.field) == (400, "invalid_argument", "feeds[0].url")
    with pytest.raises(ActionError):
        tworld.act("ticker_settings", settings={})
    assert not (tworld.state / "ticker.json").exists()


def test_a_hand_edited_override_falls_back_to_the_config(tworld):
    (tworld.state / "ticker.json").write_text(json.dumps({"speed": "warp", "max_items": 50}), encoding="utf-8")
    s = tworld.app.ticker.settings()
    assert s["speed"] == "normal" and s["max_items"] == 50


# ---------------------------------------------------------------- 4 parsing

def test_parse_rss_cleans_titles_resolves_links_and_sorts_newest_first():
    data = rss([
        ("&lt;b&gt;Bold&lt;/b&gt; &amp;amp; more", "/rel/1", "Mon, 05 Oct 2026 10:00:00 GMT"),
        ("Evil", "javascript:alert(1)", "Tue, 06 Oct 2026 10:00:00 GMT"),
        ("Newest", "https://example.org/n", "Wed, 07 Oct 2026 10:00:00 +0000"),
        ("No date", "https://example.org/nd", None),
        ("", "https://example.org/empty", None),
    ])
    items = tk.parse_feed(data, {"id": "alpha", "name": "Alpha", "url": "https://example.org/feed/rss.xml"})
    assert [i["title"] for i in items] == ["Newest", "Bold & more", "No date"]
    assert items[1]["url"] == "https://example.org/rel/1"
    assert items[0]["published_ms"] > items[1]["published_ms"] and items[2]["published_ms"] is None
    assert items[0]["feed"] == "alpha" and items[0]["source"] == "Alpha" and len(items[0]["id"]) == 16


def test_parse_atom_and_rdf():
    atom = tk.parse_feed(ATOM, {"id": "at", "name": "At", "url": "https://example.org/feed"})
    assert [(i["title"], i["url"]) for i in atom] == [("Atom newer", "https://example.org/atom/2"),
                                                       ("Atom older", "https://example.org/atom/1")]
    rdf = tk.parse_feed(RDF, {"id": "rd", "name": "Rd", "url": "https://example.org/rdf"})
    assert [i["title"] for i in rdf] == ["RDF one", "RDF two"]


def test_parse_caps_per_feed_and_long_titles():
    data = rss([(f"T{i} " + "x" * 300, f"https://example.org/{i}", f"Mon, 0{1 + i % 9} Oct 2026 10:00:00 GMT")
                for i in range(12)])
    items = tk.parse_feed(data, {"id": "a", "name": "A", "url": FEED_A}, per_feed=4)
    assert len(items) == 4 and all(len(i["title"]) <= tk.TITLE_MAX for i in items)
    assert items[0]["title"].endswith("…")


# ---------------------------------------------------------------- 5 hostile bodies, failing feeds

@pytest.mark.parametrize("body", [
    b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>',
    b'<?xml version="1.0"?><!doctype rss><rss/>',
    b'<rss><channel>' + b' ' * 5000 + b'<!ENTITY x "y"></channel></rss>',
])
def test_a_doctype_or_entity_is_refused(body):
    with pytest.raises(tk.FeedError):
        tk.parse_feed(body, {"id": "a", "name": "A", "url": FEED_A})


def test_a_body_over_the_cap_and_a_failing_feed_keep_the_rest(tworld):
    t = tworld.app.ticker
    t.refresh_sync()
    assert {i["feed"] for i in t.state()["items"]} == {"alpha", "beta"}
    t.fetch.pages[FEED_A] = b"<rss>" + b"x" * (tk.MAX_BYTES + 1)
    t.fetch.pages[FEED_B] = rss([("B fresh", "https://example.org/b/9", "Thu, 08 Oct 2026 10:00:00 GMT")])
    t.refresh_sync()
    state = t.state()
    feeds = {f["id"]: f for f in state["feeds"]}
    assert feeds["alpha"]["ok"] is False and feeds["alpha"]["error"] == "too_large"
    assert feeds["beta"]["ok"] is True and feeds["beta"]["count"] == 1
    titles = [i["title"] for i in state["items"]]
    assert "A one" in titles and "A two" in titles and "B fresh" in titles and "B one" not in titles
    t.fetch.pages[FEED_A] = tk.FeedError("timeout")
    t.refresh_sync()
    assert {f["id"]: f for f in t.state()["feeds"]}["alpha"]["error"] == "timeout"
    assert "A one" in [i["title"] for i in t.state()["items"]]


# ---------------------------------------------------------------- 6 dedup

@pytest.mark.parametrize("tworld", [FEEDS_CFG + f"      - {{id: gamma, name: Gamma, url: \"{FEED_C}\"}}\n"],
                         indirect=True)
def test_dedup_across_feeds_by_url_and_by_title(tworld):
    t = tworld.app.ticker
    t.fetch.pages[FEED_A] = rss([("Same story", "https://example.org/s?utm_source=a&amp;id=1#top",
                                  "Mon, 05 Oct 2026 10:00:00 GMT")])
    t.fetch.pages[FEED_B] = rss([("Other words", "https://example.org/s?id=1&amp;utm_medium=b",
                                  "Tue, 06 Oct 2026 10:00:00 GMT"),
                                 ("Echo", "https://example.org/e1", None)])
    t.fetch.pages[FEED_C] = rss([("ECHO", "https://example.org/e2", None)])
    t.refresh_sync()
    items = t.state()["items"]
    assert len(items) == 2
    same = next(i for i in items if i["feed"] == "alpha")
    assert same["published_ms"] == tk.parse_feed(t.fetch.pages[FEED_B], {"id": "b", "name": "B", "url": FEED_B})[0]["published_ms"]
    assert [i["title"] for i in items].count("Echo") + [i["title"] for i in items].count("ECHO") == 1


# ---------------------------------------------------------------- 7 cache

def test_refresh_writes_the_cache_and_a_new_ticker_shows_it(tworld):
    tworld.app.ticker.refresh_sync()
    cache = json.loads((tworld.state / tk.CACHE_FILE).read_text(encoding="utf-8"))
    assert cache["fetched_ms"] == tworld.clock.now
    again = tk.Ticker(tworld.app, fetch=FakeFetch())
    assert [i["id"] for i in again.state()["items"]] == [i["id"] for i in tworld.app.ticker.state()["items"]]
    assert again.state()["fetched_ms"] == tworld.clock.now


# ---------------------------------------------------------------- 8 loop gating

def test_the_loop_fetches_only_while_a_page_is_open_and_the_data_is_old(tworld):
    t = tworld.app.ticker
    assert t.due(tworld.clock()) is False            # no page open
    client = tworld.app.hub.add()
    assert t.due(tworld.clock()) is True             # never fetched
    t.refresh_sync()
    assert t.due(tworld.clock()) is False
    tworld.clock.advance(29 * 60)
    assert t.due(tworld.clock()) is False
    tworld.clock.advance(60)
    assert t.due(tworld.clock()) is True
    tworld.app.hub.remove(client)
    assert t.due(tworld.clock()) is False
    tworld.app.hub.add()
    tworld.act("ticker_settings", settings={"enabled": False})
    assert t.due(tworld.clock()) is False


def test_disabled_sends_settings_but_no_items_and_fetches_nothing(world):
    world.app.ticker.fetch = FakeFetch(standard_pages())
    world.app.ticker.refresh_sync()
    state = world.app.ticker.state()
    assert world.app.ticker.fetch.calls == [] and state["items"] == []
    assert state["settings"]["feeds"] and "defaults" in state and state["overridden"] == []


# ---------------------------------------------------------------- 9 no claude by itself

def test_nothing_calls_claude_at_startup_in_the_state_or_in_a_refresh(tworld):
    tworld.app.state_payload()
    tworld.app.ticker.refresh_sync()
    tworld.app.ticker.state()
    assert tworld.runner.of("claude.p") == []


# ---------------------------------------------------------------- 10 to 13 the editor

def edited(world) -> dict:
    wait_for(lambda: world.app.ticker.state()["editor"]["running"] is None)
    return world.app.ticker.state()


def test_the_editor_picks_shortens_and_ignores_bad_indices(tworld):
    t = tworld.app.ticker
    t.refresh_sync()
    before = t.state()["items"]
    answer = {"result": '[{"i":1,"s":"Short"},{"i":99},{"i":1}]', "total_cost_usd": 0.001}
    tworld.runner.handlers["claude.p"] = lambda argv: ok(json.dumps(answer))
    r = tworld.act("ticker_edit")
    assert r["ok"] and "ticker" in r          # the thread may already be done: running is checked in the lock test
    state = edited(tworld)
    assert [i["id"] for i in state["items"]] == [before[1]["id"]]
    assert state["items"][0]["short"] == "Short" and state["items"][0]["fresh"] is False
    assert state["editor"]["last"]["picked"] == 1 and state["editor"]["last"]["of"] == 3
    assert state["editor"]["last"]["cost_usd"] == 0.001 and state["editor"]["error"] is None
    (argv,) = tworld.runner.of("claude.p")
    assert argv == mr.haiku_argv(tworld.runner.claude, argv[12]) and len(argv[12]) <= mr.HAIKU_PROMPT_MAX
    assert before[1]["title"] in argv[12]
    # other interests: the edit no longer matches, every item shows again
    tworld.act("ticker_settings", settings={"editor": {"interests": "robots"}})
    state = tworld.app.ticker.state()
    assert state["editor"]["last"] is None and len(state["items"]) == 3
    assert all(i["short"] is None for i in state["items"])


def test_the_prompt_stays_within_the_budget():
    items = [{"id": f"{i:016x}", "title": "word " * 60, "source": "Source"} for i in range(200)]
    prompt, seen = tk.edit_prompt("x" * 500, items, 40, True)
    assert len(prompt) <= tk.PROMPT_BUDGET < mr.HAIKU_PROMPT_MAX and 0 < len(seen) < 200


def test_the_edit_does_not_hold_the_write_lock(tworld):
    tworld.app.ticker.refresh_sync()
    gate, entered = threading.Event(), threading.Event()

    def slow(argv):
        entered.set()
        gate.wait(5)
        return ok(json.dumps({"result": '[{"i":0}]'}))
    tworld.runner.handlers["claude.p"] = slow
    tworld.act("ticker_edit")
    assert entered.wait(5)
    try:
        r = tworld.act("ticker_settings", settings={"speed": "slow"})
        assert r["ok"] and r["ticker"]["editor"]["running"] is not None
        with pytest.raises(ActionError) as caught:
            tworld.act("ticker_edit")
        assert (caught.value.status, caught.value.code) == (409, "not_applicable")
    finally:
        gate.set()
    assert len(edited(tworld)["items"]) == 1


def test_every_state_change_raises_the_rev_so_the_page_drops_an_older_state(tworld):
    """logic.js newerTicker keeps the newer of two ticker states by `rev`: each change must raise it."""
    t = tworld.app.ticker
    revs = [t.state()["rev"]]
    assert isinstance(revs[0], int)
    tworld.act("ticker_settings", settings={"speed": "slow"})
    revs.append(t.state()["rev"])
    tworld.act("ticker_settings_reset")
    wait_for(lambda: not t.state()["refreshing"])
    revs.append(t.state()["rev"])
    assert t.request_refresh()
    wait_for(lambda: not t.state()["refreshing"])
    revs.append(t.state()["rev"])
    tworld.runner.handlers["claude.p"] = lambda argv: ok(json.dumps({"result": '[{"i":0}]'}))
    tworld.act("ticker_edit")
    revs.append(edited(tworld)["rev"])
    t.pass_recorded()
    revs.append(t.state()["rev"])
    assert all(a < b for a, b in zip(revs, revs[1:])), revs
    # the event a change sends carries the rev it was read at
    tworld.act("ticker_settings", settings={"speed": "fast"})
    assert t.state()["rev"] > revs[-1]


def test_the_editor_is_not_applicable_without_claude_or_items_and_reports_a_failure(tworld):
    t = tworld.app.ticker
    with pytest.raises(ActionError) as caught:
        tworld.act("ticker_edit")                       # nothing fetched yet
    assert (caught.value.status, caught.value.code) == (409, "not_applicable")
    t.refresh_sync()
    claude = tworld.runner.claude
    tworld.runner.claude = None
    assert t.state()["editor"]["available"] is False
    with pytest.raises(ActionError) as caught:
        tworld.act("ticker_edit")
    assert caught.value.code == "not_applicable"
    tworld.runner.claude = claude
    tworld.runner.handlers["claude.p"] = lambda argv: fail("model down")
    tworld.act("ticker_edit")
    state = edited(tworld)
    assert state["editor"]["error"] and state["editor"]["last"] is None and len(state["items"]) == 3
    assert any(n["tone"] == "bad" and "Ticker editor failed" in n["text"] for n in tworld.app.notes)


def test_items_after_an_edit_are_fresh_and_unpicked_ones_hide(tworld):
    t = tworld.app.ticker
    t.refresh_sync()
    before = t.state()["items"]
    tworld.runner.handlers["claude.p"] = lambda argv: ok(json.dumps({"result": '[{"i":2,"s":"Two"},{"i":0}]'}))
    tworld.act("ticker_edit")
    state = edited(tworld)
    assert [i["id"] for i in state["items"]] == [before[2]["id"], before[0]["id"]]
    assert state["items"][1]["short"] is None
    t.fetch.pages[FEED_B] = rss([("B one", "https://example.org/b/1", "Wed, 07 Oct 2026 10:00:00 GMT"),
                                 ("B new", "https://example.org/b/2", "Fri, 09 Oct 2026 10:00:00 GMT")])
    t.refresh_sync()
    items = t.state()["items"]
    assert [i["title"] for i in items][-1] == "B new" and items[-1]["fresh"] is True
    assert before[1]["id"] not in [i["id"] for i in items]
    assert t.state()["editor"]["last"]["of"] == 3


# ---------------------------------------------------------------- 14 collect passes

def test_every_collect_pass_is_kept_with_its_outcome(tworld):
    passes = list(tworld.app.collector.passes)
    assert [p["kind"] for p in passes] == ["quick", "full"] and all(p["ok"] for p in passes)
    assert all(isinstance(p["took_ms"], int) and isinstance(p["at_ms"], int) for p in passes)
    tworld.runner.handlers["briefing.collect"] = lambda argv: fail("collect broke")
    tworld.app.collector.request("full")
    tworld.app.collector.drain()
    last = tworld.app.ticker.state()["perf"]["passes"][-1]
    assert last["kind"] == "full" and last["ok"] is False
    assert tworld.app.ticker.state()["limits"]["timeout_ms"] == 120000


def test_the_refresh_verb_returns_at_once_and_ends_with_a_ticker_event(tworld):
    client = tworld.app.hub.add()
    r = tworld.act("ticker_refresh")
    assert r["ok"] and "ticker" in r
    wait_for(lambda: not tworld.app.ticker.state()["refreshing"])
    assert len(tworld.app.ticker.state()["items"]) == 3
    assert any(name == "ticker" and not data["refreshing"] for name, data in events(client))


def test_get_api_ticker_returns_the_state(tworld):
    status, _, body = tworld.request("GET", "/api/ticker", headers=tworld.cookie)
    assert status == 200 and json.loads(body)["ticker"]["enabled"] is True


# ---------------------------------------------------------------- review fixes

def test_items_past_the_prompt_budget_are_not_fresh_after_an_edit(tworld):
    t = tworld.app.ticker
    t.refresh_sync()
    many = [{"id": f"{i:016x}", "feed": "alpha", "source": "Alpha", "title": f"Story {i} " + "w" * 150,
             "url": f"https://example.org/m/{i}", "published_ms": 1_000_000 - i} for i in range(100)]
    with t.lock:
        t.items = many
    _, prompted = tk.edit_prompt("", many, 12, True)
    assert len(prompted) < len(many)                     # the budget cuts the prompt short
    tworld.runner.handlers["claude.p"] = lambda argv: ok(json.dumps({"result": '[{"i":0,"s":"First"}]'}))
    tworld.act("ticker_edit")
    state = edited(tworld)
    assert [i["id"] for i in state["items"]] == [many[0]["id"]]
    assert not any(i["fresh"] for i in state["items"])
    assert state["editor"]["last"]["of"] == len(prompted)


def utf16(text: str) -> bytes:
    return text.encode("utf-16")                         # with a BOM


@pytest.mark.parametrize("body", [
    utf16('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE r [<!ENTITY a "AAAAAAAAAA"><!ENTITY b "&a;&a;&a;">]>'
          '<rss><channel><item><title>&b;</title><link>https://example.org/x</link></item></channel></rss>'),
    utf16('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss><rss><channel><item><title>T</title>'
          '<link>https://example.org/x</link></item></channel></rss>'),
    b'<?xml version="1.0"?><!--' + b"c" * 5000 + b'--><!DOCTYPE rss><rss><channel><item><title>T</title>'
    b'<link>https://example.org/x</link></item></channel></rss>',
], ids=["utf16-entity", "utf16-doctype", "doctype-after-4k"])
def test_a_doctype_is_refused_in_any_encoding_and_at_any_offset(body):
    with pytest.raises(tk.FeedError):
        tk.parse_feed(body, {"id": "a", "name": "A", "url": FEED_A})


def test_a_utf16_feed_without_a_doctype_still_parses():
    body = utf16('<?xml version="1.0" encoding="UTF-16"?><rss><channel><item><title>Ünïcode</title>'
                 '<link>https://example.org/u</link></item></channel></rss>')
    assert [i["title"] for i in tk.parse_feed(body, {"id": "a", "name": "A", "url": FEED_A})] == ["Ünïcode"]


def test_a_doctype_inside_cdata_text_is_not_a_declaration():
    body = (b'<rss><channel><item><title>HTML basics</title><link>https://example.org/h</link>'
            b'<description><![CDATA[Start with <!DOCTYPE html> and <!ENTITY>]]></description></item></channel></rss>')
    assert [i["title"] for i in tk.parse_feed(body, {"id": "a", "name": "A", "url": FEED_A})] == ["HTML basics"]


def _redirect(handler, newurl):
    import urllib.request
    req = urllib.request.Request("https://feeds.example.org/rss")
    return handler.redirect_request(req, None, 302, "Found", {}, newurl)


@pytest.mark.parametrize("target", ["http://127.0.0.1:8797/api/state", "http://192.168.1.10/x",
                                    "http://169.254.169.254/latest/meta-data/", "http://[::1]/x",
                                    "http://intranet.example/x", "http://0.0.0.0/x"])
def test_a_redirect_from_a_public_feed_to_a_private_host_is_refused(monkeypatch, target):
    monkeypatch.setattr(tk, "_addresses", lambda host: ["10.0.0.5"] if host == "intranet.example" else ["93.184.216.34"])
    with pytest.raises(tk.FeedError, match="bad redirect"):
        _redirect(tk._Redirects(allow_private=False), target)


def test_a_redirect_to_a_public_host_or_from_a_private_feed_is_followed(monkeypatch):
    monkeypatch.setattr(tk, "_addresses", lambda host: ["93.184.216.34"])
    assert _redirect(tk._Redirects(allow_private=False), "https://cdn.example.org/rss").full_url == "https://cdn.example.org/rss"
    assert _redirect(tk._Redirects(allow_private=True), "http://127.0.0.1:9000/rss").full_url == "http://127.0.0.1:9000/rss"


def test_the_configured_hosts_class_decides(monkeypatch):
    monkeypatch.setattr(tk, "_addresses", lambda host: ["192.168.0.2"] if host == "nas.local" else ["93.184.216.34"])
    assert tk._host_private("nas.local") and tk._host_private("127.0.0.1") and tk._host_private("::1")
    assert not tk._host_private("example.org") and not tk._host_private("93.184.216.34")


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


def test_reading_a_feed_stops_at_the_wall_clock_deadline():
    clock = [0.0]
    with pytest.raises(tk.FeedError, match="timeout"):
        tk._read_body(Drip(clock, 1.0), deadline=tk.FETCH_TIMEOUT, now=lambda: clock[0])
    assert clock[0] <= tk.FETCH_TIMEOUT + 1


def test_reading_a_feed_stops_at_the_size_cap_and_returns_a_small_body():
    clock = [0.0]

    class Big:
        def read1(self, n=-1):
            return b"y" * n
    with pytest.raises(tk.FeedError, match="too_large"):
        tk._read_body(Big(), deadline=10.0, now=lambda: clock[0])
    assert tk._read_body(Drip(clock, 0.0, total=5), deadline=10.0, now=lambda: clock[0]) == b"xxxxx"


def test_a_collect_pass_sends_the_ticker_state_with_the_new_pass_and_outliers(tworld):
    client = tworld.app.hub.add()
    events(client)
    outliers = [{"source": "claude", "today": 900, "usual": 100, "factor": 9.0}]
    tworld.app.usage.view = lambda: {"outliers": outliers}
    tworld.runner.handlers["briefing.collect"] = lambda argv: fail("collect broke")
    tworld.app.collector.request("full")
    tworld.app.collector.drain()
    sent = [data for name, data in events(client) if name == "ticker"]
    assert sent and sent[-1]["perf"]["passes"][-1]["ok"] is False
    assert sent[-1]["perf"]["outliers"] == outliers


def test_a_collect_pass_sends_no_ticker_event_while_the_ticker_is_off(world):
    client = world.app.hub.add()
    events(client)
    world.app.collector.request("full")
    world.app.collector.drain()
    assert not any(name == "ticker" for name, _ in events(client))


# ---------------------------------------------------------------- 12 selection without a model (smart)

@pytest.mark.parametrize("change, field", [
    ({"smart": {"cluster": "yes"}}, "smart.cluster"),
    ({"smart": {"max_age_hours": -1}}, "smart.max_age_hours"),
    ({"smart": {"max_age_hours": 721}}, "smart.max_age_hours"),
    ({"smart": {"mute": "webinar"}}, "smart.mute"),
    ({"smart": {"mute": [""]}}, "smart.mute"),
    ({"smart": {"mute": ["x" * 41]}}, "smart.mute"),
    ({"smart": {"mute": [f"t{i}" for i in range(31)]}}, "smart.mute"),
    ({"smart": []}, "smart"),
])
def test_smart_settings_reject_with_the_field(change, field):
    with pytest.raises(tk.TickerSettingsError) as caught:
        tk.normalize(change, tk.defaults())
    assert caught.value.field == field


def test_smart_defaults_and_muted_terms_once_each_with_blanks_squeezed():
    assert tk.defaults()["smart"] == {"cluster": True, "max_age_hours": 72, "mark_new": True, "mute": []}
    out = tk.normalize({"smart": {"mute": ["  Funding   round ", "funding round", "Webinar"]}}, tk.defaults())
    assert out["smart"]["mute"] == ["Funding round", "Webinar"] and out["smart"]["cluster"] is True


def _it(feed: str, title: str, url: str, ms: int | None = None) -> dict:
    return {"id": tk._item_id(feed, url), "feed": feed, "source": feed.title(), "title": title, "url": url,
            "published_ms": ms}


def test_one_story_from_two_feeds_becomes_one_item_naming_the_other():
    a = [_it("alpha", "OpenAI releases GPT-6 with longer context window", "https://a.example/1", 1000)]
    b = [_it("beta", "GPT-6 released by OpenAI: longer context window and new pricing", "https://b.example/9", 2000),
         _it("beta", "Something else entirely about robots", "https://b.example/2", 500)]
    items = tk.merge_items([a, b], 10, {"cluster": True})
    assert len(items) == 2
    story = next(i for i in items if i["feed"] == "alpha")
    assert story["published_ms"] == 2000
    assert story["sources"] == [{"feed": "beta", "source": "Beta", "url": "https://b.example/9"}]
    # without clustering both stay; an exact duplicate address still joins and names its feed
    assert len(tk.merge_items([a, b], 10, {"cluster": False})) == 3
    dup = [_it("beta", "Different words", "https://a.example/1?utm_source=x", 10)]
    (one,) = tk.merge_items([a, dup], 10, {"cluster": False})
    assert one["sources"][0]["feed"] == "beta"


def test_two_items_of_one_feed_never_join_and_few_shared_words_do_not_either():
    same_feed = [_it("alpha", "heise-Angebot: enterJS Call for Proposals 2027", "https://a.example/1"),
                 _it("alpha", "heise-Angebot: enterJS Call for Papers 2027", "https://a.example/2")]
    assert len(tk.merge_items([same_feed], 10, {"cluster": True})) == 2
    loose = [[_it("alpha", "Claude gets a new memory tool", "https://a.example/3")],
             [_it("beta", "Gemini gets a new memory feature for teams and schools", "https://b.example/3")]]
    assert len(tk.merge_items(loose, 10, {"cluster": True})) == 2


def test_muted_terms_drop_items_a_word_only_as_a_whole_word():
    items = [[_it("alpha", "AI Act enters into force", "https://a.example/1"),
              _it("alpha", "What the CEO said about chips", "https://a.example/2"),
              _it("alpha", "Big funding round for a startup", "https://a.example/3")]]
    titles = [i["title"] for i in tk.merge_items(items, 10, {"mute": ["ai", "Funding Round"]})]
    assert titles == ["What the CEO said about chips"]


def test_items_older_than_max_age_drop_and_undated_ones_stay():
    now = 100 * 3_600_000
    items = [[_it("alpha", "Fresh", "https://a.example/1", now - 3_600_000),
              _it("alpha", "Old", "https://a.example/2", now - 80 * 3_600_000),
              _it("alpha", "Undated", "https://a.example/3")]]
    assert [i["title"] for i in tk.merge_items(items, 10, {"max_age_hours": 72}, now)] == ["Fresh", "Undated"]
    assert len(tk.merge_items(items, 10, {"max_age_hours": 0}, now)) == 3


def test_changing_the_selection_rebuilds_at_once_without_reading_a_feed(tworld):
    t = tworld.app.ticker
    t.refresh_sync()
    calls = len(t.fetch.calls)
    tworld.act("ticker_settings", settings={"smart": {"mute": ["two"]}})
    assert [i["title"] for i in t.state()["items"]] == ["B one", "A one"]
    assert len(t.fetch.calls) == calls
    tworld.act("ticker_settings_reset")
    assert len(t.state()["items"]) == 3


def test_the_editor_prompt_names_muted_terms_and_how_many_feeds_tell_a_story():
    items = [{"id": "x1", "title": "Story", "source": "Alpha", "sources": [{"feed": "b", "source": "B", "url": "u"}]},
             {"id": "x2", "title": "Lonely", "source": "Alpha", "sources": []}]
    prompt, ids = tk.edit_prompt("agents", items, 5, True, ["webinar", "funding"])
    assert ids == ["x1", "x2"]
    assert "Never pick an item about: webinar; funding." in prompt
    assert '"t":"Story","src":"Alpha","n":2' in prompt and '"t":"Lonely","src":"Alpha"}' in prompt
    assert tk.edit_key({"interests": "a", "max_picks": 5, "shorten": True}, ["x"]) != \
        tk.edit_key({"interests": "a", "max_picks": 5, "shorten": True}, [])


# ---------------------------------------------------------------- 13 the interest profile

def test_profile_keywords_rank_shared_and_named_words_first():
    titles = ["Kafka consumer fails on Azure Functions", "Azure Functions cold start", "Claude Code skill for Kafka",
              "write the newsletter"]
    words = tk.profile_keywords(titles, 4).split(", ")
    assert words[:3] == ["Kafka", "Azure", "Functions"] and len(words) == 4
    assert "the" not in [w.lower() for w in tk.profile_keywords(titles).split(", ")]


def test_the_profile_reads_the_titles_of_the_open_tasks(tworld):
    tworld.app.collector.tasks = [{"slug": "a", "title": "One"}, {"slug": "b", "label": "Two"}, "bad"]
    assert tworld.app.ticker.task_titles() == ["One", "Two"]


def test_a_keyword_profile_comes_at_once_and_never_calls_claude(tworld):
    tworld.app.ticker.task_titles = lambda: ["Kafka consumer on Azure", "Azure costs"]
    r = tworld.act("ticker_profile", llm=False)
    last = r["ticker"]["profile"]["last"]
    assert last["llm"] is False and last["text"].startswith("Azure") and last["from"] == 2
    assert r["ticker"]["profile"]["tasks"] == 2
    assert tworld.runner.of("claude.p") == []
    # a proposal is no setting
    assert tworld.app.ticker.settings()["editor"]["interests"] == ""


def test_a_haiku_profile_runs_on_a_thread_with_the_task_titles(tworld):
    tworld.app.ticker.task_titles = lambda: ["Kafka consumer on Azure"]
    answer = {"result": '"Kafka, event streaming, Azure Functions"\nextra line', "total_cost_usd": 0.0004}
    tworld.runner.handlers["claude.p"] = lambda argv: ok(json.dumps(answer))
    tworld.act("ticker_profile", llm=True)
    wait_for(lambda: tworld.app.ticker.state()["profile"]["running"] is None
             and tworld.app.ticker.state()["profile"]["last"] is not None)
    last = tworld.app.ticker.state()["profile"]["last"]
    assert last == {"text": "Kafka, event streaming, Azure Functions", "llm": True, "at_ms": last["at_ms"], "from": 1,
                    "error": None, "cost_usd": 0.0004}
    (argv,) = tworld.runner.of("claude.p")
    assert argv == mr.haiku_argv(tworld.runner.claude, argv[12]) and "- Kafka consumer on Azure" in argv[12]


def test_a_profile_needs_tasks_and_for_haiku_claude_and_the_editor(tworld):
    tworld.app.ticker.task_titles = lambda: []
    with pytest.raises(ActionError) as caught:
        tworld.act("ticker_profile")
    assert caught.value.code == "not_applicable"
    tworld.app.ticker.task_titles = lambda: ["Something"]
    tworld.act("ticker_settings", settings={"editor": {"enabled": False}})
    with pytest.raises(ActionError):
        tworld.act("ticker_profile", llm=True)
    tworld.act("ticker_settings", settings={"editor": {"enabled": True}})
    tworld.runner.claude = None
    with pytest.raises(ActionError):
        tworld.act("ticker_profile", llm=True)
    tworld.runner.handlers["claude.p"] = lambda argv: fail("down")
    assert tworld.act("ticker_profile", llm=False)["ok"]


def test_a_busy_feed_cannot_push_out_a_quiet_one():
    busy = [_it("busy", f"Busy story number {i}", f"https://busy.example/{i}", 10_000 - i) for i in range(8)]
    quiet = [_it("quiet", "The quiet feed's one post", "https://quiet.example/1", 100)]
    items = tk.merge_items([busy, quiet], 4)
    assert [i["feed"] for i in items] == ["busy", "busy", "busy", "quiet"]
    assert [i["published_ms"] for i in items] == [10_000, 9_999, 9_998, 100]


def test_a_gzip_body_sent_unasked_is_unpacked_within_the_cap():
    import gzip
    body = rss([("Packed", "https://example.org/p", None)])
    assert tk.ungzip(gzip.compress(body)) == body
    assert tk.ungzip(body) == body
    with pytest.raises(tk.FeedError, match="too_large"):
        tk.ungzip(gzip.compress(b" " * (tk.MAX_BYTES + 10)))
    with pytest.raises(tk.FeedError, match="bad gzip"):
        tk.ungzip(b"\x1f\x8bnot really")
