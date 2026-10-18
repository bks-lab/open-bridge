# SPDX-License-Identifier: MIT
"""The news ticker of the start page: feeds the owner configured, and Claude Haiku as editor on a click.

The config (cockpit.ticker) says what a Bridge shows; the settings page changes that on top, kept in
.bridge/cockpit/ticker.json, so the page never writes bridge-config.yaml. Everything is off until
`enabled`. Feeds are read by the server only (the page's CSP allows no other origin), one after the
other on a thread of its own, and only while a page is open and the last read is older than
refresh_minutes. The page builds the status items itself from its own store; the server sends the feed
items, the editor's result and a small `perf` block (the collect passes and the token outliers).

The selection without a model (`smart`) runs on every refresh and settings change: muted terms drop an
item, an item older than max_age_hours drops, and one story told by several feeds becomes one item that
names the others (`sources`). The page marks what is new since the viewer's last visit itself.

The editor (Claude Haiku through the allowlisted model_route.haiku_argv) runs ONLY when someone presses
the button: never at startup, in the refresh loop or from state(). Its pick applies while the interests,
max_picks and shorten it was made with are still the settings. The interest profile is proposed on a
click too, from the titles of the open tasks: as keywords without a model, or written by Haiku. It is a
proposal the owner saves or drops, never a setting by itself. Safety notes: docs/bridge-cockpit.md.
"""
from __future__ import annotations

import copy
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Callable
from xml.parsers import expat

from .. import model_route as mr
from . import net
from .store import atomic_write_json, read_json

FILE = "ticker.json"                 # the settings page's overrides (only keys differing from the config)
CACHE_FILE = "ticker-cache.json"     # items per feed, feed status, the editor's last pick
FETCH_TIMEOUT = 8
MAX_BYTES = 2_000_000
TITLE_MAX = 200
SHORT_MAX = 90
URL_MAX = 500
USER_AGENT = "bridge-cockpit/ticker"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml"
EDITOR_TIMEOUT = 60
PROMPT_BUDGET = 7600                 # below model_route.HAIKU_PROMPT_MAX: a longer prompt is refused, not cut
LOOP_STEP_S = 5
PASSES_KEEP = 10
MAX_FEEDS = 20
MUTE_MAX = 30
MUTE_TERM_MAX = 40
CLUSTER_MIN_SHARED = 3               # two titles tell one story when they share this many words ...
CLUSTER_MIN_OVERLAP = 0.6            # ... and that many of the shorter title's words
PROFILE_TASKS_MAX = 60
PROFILE_KEYWORDS = 14

SPEEDS = ("slow", "normal", "fast")
STATUS_KINDS = ("running", "waiting", "slow", "failing", "quota", "offline", "notes")
FEED_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}\Z")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
CONTROL_BUT_NEWLINE_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")
TAG_RE = re.compile(r"<[^>]*>")
SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[\w][\w.+#-]*[\w+#]|[\w]{2,}", re.UNICODE)
# words that say nothing about a story, in the two languages the feeds and tasks come in
STOP_WORDS = frozenset("""
a an and are as at be by for from has have how in into is it its new of on or our the their this to was
what when why will with you your about after all also can more not now one over than that them they up
use using via vs we who
der die das den dem des ein eine einen einem einer und oder ist sind mit für fuer von zu zum zur im in
auf aus bei nach über ueber unter wie was wer wird werden noch auch nicht neu neue neuer neues so als an
am beim vom bis seit nur sich es er sie wir ihr man kann soll mehr jetzt heute
""".split())

DEFAULT_FEEDS = [
    {"id": "openai", "name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "enabled": True},
    {"id": "deepmind", "name": "Google DeepMind", "url": "https://deepmind.google/blog/rss.xml", "enabled": True},
    {"id": "google-ai", "name": "Google AI", "url": "https://blog.google/technology/ai/rss/", "enabled": True},
    {"id": "huggingface", "name": "Hugging Face", "url": "https://huggingface.co/blog/feed.xml", "enabled": True},
    {"id": "techreview-ai", "name": "MIT Technology Review AI",
     "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "enabled": True},
    {"id": "simonwillison", "name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "enabled": True},
]

DEFAULTS: dict[str, Any] = {
    "enabled": False, "max_items": 30, "per_feed": 8, "refresh_minutes": 30, "speed": "normal",
    "feeds": DEFAULT_FEEDS,
    "status": {"enabled": True, "kinds": list(STATUS_KINDS)},
    "editor": {"enabled": True, "interests": "", "max_picks": 12, "shorten": True},
    "smart": {"cluster": True, "max_age_hours": 72, "mark_new": True, "mute": []},
}
KEYS = tuple(DEFAULTS)
RANGES = {"max_items": (5, 100), "per_feed": (1, 30), "refresh_minutes": (5, 1440)}
MAX_AGE_HOURS = 720                  # 0 keeps every item, however old


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


class TickerSettingsError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field, self.message = field, message


class TickerError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


FeedError = net.FetchError   # a feed that cannot be read; the message is short and shown beside the feed


# ------------------------------------------------------------------ settings

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def url_ok(url: Any) -> bool:
    """http or https, a host, no userinfo, no whitespace or control character, at most URL_MAX."""
    return net.url_ok(url, ("http", "https"), URL_MAX)


def _feed(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise TickerSettingsError(where, "must be an object with id, name and url")
    fid, name, url = value.get("id"), value.get("name"), value.get("url")
    if not isinstance(fid, str) or not FEED_ID_RE.match(fid):
        raise TickerSettingsError(f"{where}.id", "lower case letters, digits and hyphens, at most 40")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or CONTROL_RE.search(name):
        raise TickerSettingsError(f"{where}.name", "a name of 1 to 60 characters")
    if not url_ok(url):
        raise TickerSettingsError(f"{where}.url", "an http or https address without user or password")
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise TickerSettingsError(f"{where}.enabled", "must be true or false")
    return {"id": fid, "name": name.strip(), "url": url, "enabled": enabled}


def _feeds(value: Any) -> list[dict]:
    if not isinstance(value, list):
        raise TickerSettingsError("feeds", "must be a list")
    if len(value) > MAX_FEEDS:
        raise TickerSettingsError("feeds", f"at most {MAX_FEEDS} feeds")
    out, seen = [], set()
    for i, entry in enumerate(value):
        feed = _feed(entry, f"feeds[{i}]")
        if feed["id"] in seen:
            raise TickerSettingsError(f"feeds[{i}].id", "this id is taken by an earlier feed")
        seen.add(feed["id"])
        out.append(feed)
    return out


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise TickerSettingsError(field, "must be true or false")
    return value


def normalize(value: Any, base: dict | None = None) -> dict:
    """value on top of base (the defaults when None), strictly: a bad value raises with its field.
    Unknown keys are dropped; `feeds` replaces the old list as a whole, `status` and `editor` merge."""
    if not isinstance(value, dict):
        raise TickerSettingsError("settings", "must be an object")
    out = copy.deepcopy(base) if base is not None else defaults()
    for key, v in value.items():
        if key == "enabled":
            out["enabled"] = _bool(v, "enabled")
        elif key in RANGES:
            lo, hi = RANGES[key]
            number = _is_int(v) or (key == "refresh_minutes" and isinstance(v, float))
            if not number or not lo <= v <= hi:
                raise TickerSettingsError(key, f"a number from {lo} to {hi}")
            out[key] = v
        elif key == "speed":
            if v not in SPEEDS:
                raise TickerSettingsError("speed", "slow, normal or fast")
            out["speed"] = v
        elif key == "feeds":
            out["feeds"] = _feeds(v)
        elif key == "status":
            if not isinstance(v, dict):
                raise TickerSettingsError("status", "must be an object")
            status = dict(out["status"])
            if "enabled" in v:
                status["enabled"] = _bool(v["enabled"], "status.enabled")
            if "kinds" in v:
                kinds = v["kinds"]
                if not isinstance(kinds, list) or not all(isinstance(k, str) and k in STATUS_KINDS for k in kinds):
                    raise TickerSettingsError("status.kinds", "a list of " + ", ".join(STATUS_KINDS))
                status["kinds"] = [k for k in STATUS_KINDS if k in kinds]
            out["status"] = status
        elif key == "editor":
            if not isinstance(v, dict):
                raise TickerSettingsError("editor", "must be an object")
            editor = dict(out["editor"])
            for name, x in v.items():
                if name in ("enabled", "shorten"):
                    editor[name] = _bool(x, f"editor.{name}")
                elif name == "interests":
                    if not isinstance(x, str) or len(x) > 500 or CONTROL_BUT_NEWLINE_RE.search(x):
                        raise TickerSettingsError("editor.interests", "at most 500 characters")
                    editor["interests"] = x
                elif name == "max_picks":
                    if not _is_int(x) or not 1 <= x <= 40:
                        raise TickerSettingsError("editor.max_picks", "a number from 1 to 40")
                    editor["max_picks"] = x
            out["editor"] = editor
        elif key == "smart":
            if not isinstance(v, dict):
                raise TickerSettingsError("smart", "must be an object")
            smart = dict(out["smart"])
            for name, x in v.items():
                if name in ("cluster", "mark_new"):
                    smart[name] = _bool(x, f"smart.{name}")
                elif name == "max_age_hours":
                    if not _is_int(x) or not 0 <= x <= MAX_AGE_HOURS:
                        raise TickerSettingsError("smart.max_age_hours", f"a number from 0 to {MAX_AGE_HOURS}")
                    smart["max_age_hours"] = x
                elif name == "mute":
                    smart["mute"] = _mute(x)
            out["smart"] = smart
    return out


def _mute(value: Any) -> list[str]:
    """The muted terms: at most MUTE_MAX, each 1 to MUTE_TERM_MAX characters, once each ignoring case."""
    if not isinstance(value, list) or len(value) > MUTE_MAX:
        raise TickerSettingsError("smart.mute", f"a list of at most {MUTE_MAX} terms")
    out, seen = [], set()
    for x in value:
        term = SPACE_RE.sub(" ", x).strip() if isinstance(x, str) else ""
        if not 1 <= len(term) <= MUTE_TERM_MAX or CONTROL_RE.search(term):
            raise TickerSettingsError("smart.mute", f"each term 1 to {MUTE_TERM_MAX} characters")
        if term.casefold() not in seen:
            seen.add(term.casefold())
            out.append(term)
    return out


def lenient(value: Any, base: dict | None = None) -> dict:
    """The same rules key by key: a bad value keeps the base's for that key and never raises. For feeds a
    bad entry is skipped (a later duplicate id too); with no valid feed left the base's list stays."""
    out = copy.deepcopy(base) if base is not None else defaults()
    if not isinstance(value, dict):
        return out
    for key, v in value.items():
        if key == "feeds":
            if not isinstance(v, list):
                continue
            feeds, seen = [], set()
            for entry in v[:MAX_FEEDS]:
                try:
                    feed = _feed(entry, "feed")
                except TickerSettingsError:
                    continue
                if feed["id"] not in seen:
                    seen.add(feed["id"])
                    feeds.append(feed)
            if feeds:
                out["feeds"] = feeds
        elif key in ("status", "editor", "smart") and isinstance(v, dict):
            for name, x in v.items():
                try:
                    out = normalize({key: {name: x}}, out)
                except TickerSettingsError:
                    continue
        else:
            try:
                out = normalize({key: v}, out)
            except TickerSettingsError:
                continue
    return out


def ticker_of(value: Any) -> dict:
    """cockpit.ticker on top of the defaults (config.py)."""
    return lenient(value, defaults())


# ------------------------------------------------------------------ parsing

def clean_text(value: Any, cap: int = TITLE_MAX) -> str:
    text = html.unescape(value or "")
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = CONTROL_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text if len(text) <= cap else text[:cap - 1].rstrip() + "…"


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text_of(el: ET.Element | None) -> str:
    return "".join(el.itertext()) if el is not None else ""


def _link(raw: str, base: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        url = urllib.parse.urljoin(base, raw)
    except ValueError:
        return None
    return url if url_ok(url) else None


def _rss_date(text: str) -> int | None:
    try:
        when = email.utils.parsedate_to_datetime(text.strip())
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return int(when.timestamp() * 1000)


def _iso_date(text: str) -> int | None:
    text = text.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return int(when.timestamp() * 1000)


def _item_id(feed_id: str, url: str) -> str:
    return hashlib.sha1(f"{feed_id}\n{url}".encode("utf-8")).hexdigest()[:16]


def sort_newest(items: list[dict]) -> list[dict]:
    """Dated items newest first, undated after them in their order (a stable sort)."""
    return sorted(items, key=lambda i: (0, -i["published_ms"]) if i.get("published_ms") is not None else (1, 0))


def _refuse_doctype(*_args: Any) -> None:
    raise FeedError("doctype")


def _no_doctype(data: bytes) -> None:
    """Scan the body with expat itself, so the rule holds in every encoding expat reads (a UTF-16 body
    hides `<!DOCTYPE` from a byte search) and at any offset: a DOCTYPE, an entity or a notation
    declaration raises at its start, before any entity is expanded. Text in CDATA is not a declaration."""
    scanner = expat.ParserCreate()
    scanner.StartDoctypeDeclHandler = _refuse_doctype
    scanner.EntityDeclHandler = _refuse_doctype
    scanner.UnparsedEntityDeclHandler = _refuse_doctype
    scanner.NotationDeclHandler = _refuse_doctype
    scanner.ExternalEntityRefHandler = _refuse_doctype
    try:
        scanner.Parse(bytes(data), True)
    except expat.ExpatError:
        raise FeedError("not XML") from None


def parse_feed(data: bytes, feed: dict, per_feed: int = DEFAULTS["per_feed"]) -> list[dict]:
    """RSS 2.0, RSS 1.0 (RDF) or Atom as ticker items, newest first, at most per_feed. A body with a
    DOCTYPE or an ENTITY declaration is refused by a first expat pass before the tree is built
    (expat expands internal entities)."""
    if not isinstance(data, (bytes, bytearray)):
        raise FeedError("not bytes")
    if len(data) > MAX_BYTES:
        raise FeedError("too_large")
    _no_doctype(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise FeedError("not XML") from None
    base = feed.get("url") or ""
    out = []
    for el in root.iter():
        kind = _local(el.tag)
        if kind == "item":
            link = _link(_text_of(_child(el, "link")), base)
            if not link:
                guid = _child(el, "guid")
                if guid is not None and (guid.get("isPermaLink") or "true").lower() != "false":
                    link = _link(_text_of(guid), base)
            date = _child(el, "pubDate")
            if date is None:
                date = _child(el, "date")      # dc:date of RSS 1.0
            published = None
            if date is not None:
                published = _rss_date(_text_of(date)) or _iso_date(_text_of(date))
        elif kind == "entry":
            link = None
            for c in el:
                if _local(c.tag) == "link" and c.get("rel") in (None, "alternate"):
                    link = _link(c.get("href") or "", base)
                    if link:
                        break
            date = _child(el, "published")
            if date is None:
                date = _child(el, "updated")
            published = _iso_date(_text_of(date)) if date is not None else None
        else:
            continue
        title = clean_text(_text_of(_child(el, "title")))
        if not title or not link:
            continue
        out.append({"id": _item_id(feed["id"], link), "feed": feed["id"], "source": feed.get("name") or feed["id"],
                    "title": title, "url": link, "published_ms": published})
    return sort_newest(out)[:max(1, per_feed)]


def _url_key(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    query.sort()
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                                    urllib.parse.urlencode(query), ""))


def title_words(title: str) -> frozenset[str]:
    """The words of a title that can tell two stories apart: lower case, no stop word, no single letter."""
    return frozenset(w for w in (m.group(0).casefold() for m in WORD_RE.finditer(title or ""))
                     if w not in STOP_WORDS and len(w) > 1)


def same_story(a: frozenset[str], b: frozenset[str]) -> bool:
    shared = len(a & b)
    return shared >= CLUSTER_MIN_SHARED and shared >= CLUSTER_MIN_OVERLAP * min(len(a), len(b))


def muted(title: str, terms: list[str]) -> bool:
    """A muted term is found in the title ignoring case; a term of letters only matches whole words."""
    low = (title or "").casefold()
    for term in terms:
        t = term.casefold()
        if re.fullmatch(r"\w+", t):
            if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", low):
                return True
        elif t in low:
            return True
    return False


def _join(hit: dict, it: dict) -> None:
    """it tells hit's story: hit takes the newer date and names its feed once (never its own)."""
    if it.get("published_ms") is not None and (hit.get("published_ms") is None
                                               or it["published_ms"] > hit["published_ms"]):
        hit["published_ms"] = it["published_ms"]
    if it["feed"] != hit["feed"] and all(x["feed"] != it["feed"] for x in hit["sources"]):
        hit["sources"].append({"feed": it["feed"], "source": it.get("source") or it["feed"], "url": it["url"]})


def merge_items(groups: list[list[dict]], max_items: int, smart: dict | None = None,
                now_ms: int | None = None) -> list[dict]:
    """Every feed's items in feed order, one per story: the same address (without fragment and utm_
    parameters) or the same title ignoring case always, and with smart.cluster also a title of another
    feed sharing most of its words. The first one stays, takes the newest date and names the other feeds
    in `sources`. Muted titles and items older than smart.max_age_hours (dated ones only) drop first.
    When more remain than max_items, every feed takes its turn: each feed's newest, then each one's second
    newest and so on, so a feed that writes every hour cannot push out one that writes every week. The
    items kept stand newest first."""
    smart = smart or {}
    terms = list(smart.get("mute") or [])
    hours = smart.get("max_age_hours") or 0
    cutoff = now_ms - hours * 3_600_000 if hours and now_ms is not None else None
    cluster = smart.get("cluster", False)
    kept: list[dict] = []
    words: list[frozenset[str]] = []
    by_key: dict[str, dict] = {}
    for items in groups:
        for it in items:
            if terms and muted(it["title"], terms):
                continue
            if cutoff is not None and it.get("published_ms") is not None and it["published_ms"] < cutoff:
                continue
            keys = (f"u:{_url_key(it['url'])}", f"t:{it['title'].casefold()}")
            hit = next((by_key[k] for k in keys if k in by_key), None)
            mine = title_words(it["title"]) if cluster else frozenset()
            if hit is None and cluster:
                hit = next((k for k, w in zip(kept, words) if k["feed"] != it["feed"] and same_story(w, mine)), None)
            if hit is not None:
                _join(hit, it)
                for k in keys:
                    by_key.setdefault(k, hit)
                continue
            entry = {**it, "sources": []}
            kept.append(entry)
            words.append(mine)
            for k in keys:
                by_key[k] = entry
    if len(kept) > max_items:
        rank: dict[str, int] = {}
        turns = []
        for entry in sort_newest(kept):
            rank[entry["feed"]] = rank.get(entry["feed"], -1) + 1
            turns.append((rank[entry["feed"]], entry))
        # a stable sort: within one turn the newer first, as sort_newest had them
        kept = [e for _, e in sorted(turns, key=lambda t: t[0])][:max_items]
    return sort_newest(kept)


# ------------------------------------------------------------------ fetching

# what net.fetch gets for a feed: http or https, the feed media types, MAX_BYTES, FETCH_TIMEOUT
FEED_FETCH = {"schemes": ("http", "https"), "accept": ACCEPT, "user_agent": USER_AGENT,
              "max_bytes": MAX_BYTES, "timeout": FETCH_TIMEOUT}


def fetch_feed(url: str) -> bytes:
    """GET one feed through net.fetch (redirects, size cap and wall-clock deadline live there)."""
    return net.fetch(url, **FEED_FETCH)


# ------------------------------------------------------------------ the editor

def edit_key(editor: dict, mute: list[str] | None = None) -> str:
    raw = f"{editor['interests']}\n{editor['max_picks']}\n{editor['shorten']}\n{json.dumps(mute or [])}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def edit_prompt(interests: str, items: list[dict], max_picks: int, shorten: bool,
                mute: list[str] | None = None) -> tuple[str, list[str]]:
    """The editor's prompt and the ids of the items it holds (in prompt order); items are added while the
    prompt stays within PROMPT_BUDGET. An item several feeds tell carries their number ("n")."""
    head = (f"You are the editor of a news ticker. The reader's interests: {interests.strip() or 'general AI news'}.\n"
            f"From the numbered items below pick at most {max_picks} the reader most wants to see, best first.\n"
            "An item with \"n\" is told by that many sources: a weak sign that it matters, never a reason alone.\n")
    if mute:
        head += "Never pick an item about: " + "; ".join(mute) + ".\n"
    if shorten:
        head += ('For each pick write "s": the title shortened to one line of at most 70 characters, '
                 "same language as the title, no quotes.\n")
    head += 'Answer ONLY a JSON array: [{"i": <number>, "s": "<short title>"}]\nItems: ['
    prompt, seen = head, []
    for it in items:
        fields = {"i": len(seen), "t": it["title"][:160], "src": it.get("source") or ""}
        if it.get("sources"):
            fields["n"] = 1 + len(it["sources"])
        entry = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
        candidate = prompt + ("," if seen else "") + entry
        if len(candidate) + 1 > PROMPT_BUDGET:
            break
        prompt = candidate
        seen.append(it["id"])
    return prompt + "]", seen


def parse_edit(stdout: str, n: int, max_picks: int, shorten: bool) -> tuple[list[tuple[int, str | None]], float | None]:
    """Haiku's answer (the claude -p envelope or the bare array) as [(index, short or None)] and the cost."""
    text, cost = _haiku_text(stdout)
    start, end = text.find("["), text.rfind("]")
    try:
        answer = json.loads(text[start:end + 1]) if 0 <= start < end else []
    except ValueError:
        answer = []
    picks: list[tuple[int, str | None]] = []
    taken: set[int] = set()
    for x in answer if isinstance(answer, list) else []:
        i = x.get("i") if isinstance(x, dict) else None
        if not _is_int(i) or not 0 <= i < n or i in taken:
            continue
        taken.add(i)
        s = x.get("s")
        short = clean_text(s, SHORT_MAX) if shorten and isinstance(s, str) else ""
        picks.append((i, short or None))
        if len(picks) >= max_picks:
            break
    return picks, cost


def _haiku_text(stdout: str) -> tuple[str, float | None]:
    """The text of Haiku's answer (the claude -p envelope's result, or the bare text) and the cost."""
    text, cost = stdout or "", None
    try:
        envelope = json.loads(text)
        if isinstance(envelope, dict):
            c = envelope.get("total_cost_usd")
            cost = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None
            if isinstance(envelope.get("result"), str):
                text = envelope["result"]
    except ValueError:
        pass
    return text, cost


# ------------------------------------------------------------------ the interest profile

def profile_keywords(titles: list[str], limit: int = PROFILE_KEYWORDS) -> str:
    """The words the titles share most, without a model: a word in two titles beats one in one, a word
    written with a capital or a digit (a name, a product) beats a plain one, then the first seen. Each
    word in the case it was first written."""
    count: dict[str, int] = {}
    shown: dict[str, str] = {}
    marked: set[str] = set()
    order: list[str] = []
    for title in titles[:PROFILE_TASKS_MAX]:
        for w in dict.fromkeys(m.group(0) for m in WORD_RE.finditer(title or "")):
            low = w.casefold()
            if low in STOP_WORDS or len(low) < 3 or low.isdigit():
                continue
            if low not in count:
                count[low], shown[low] = 0, w
                order.append(low)
            count[low] += 1
            if w[0].isupper() or any(ch.isdigit() for ch in w):
                marked.add(low)
    ranked = sorted(order, key=lambda k: (-count[k], k not in marked, order.index(k)))
    return ", ".join(shown[k] for k in ranked[:limit])


def profile_prompt(titles: list[str], current: str) -> str:
    """Haiku's prompt for the interest profile: the open task titles, the interests written so far."""
    head = ("You write the interest profile for the news ticker of a person whose open work items follow.\n"
            "Name the technologies, products, companies and topics news about which would matter to them, "
            "most important first, as one line of comma separated terms, at most 400 characters, in the "
            "language most titles are in. No people's names, no customer names, no explanation.\n")
    if current.strip():
        head += f"Their interests so far (keep what still fits): {current.strip()[:500]}\n"
    prompt = head + "Work items:\n"
    for title in titles[:PROFILE_TASKS_MAX]:
        line = f"- {clean_text(title, 160)}\n"
        if len(prompt) + len(line) > PROMPT_BUDGET:
            break
        prompt += line
    return prompt


# ------------------------------------------------------------------ the ticker

class Ticker:
    def __init__(self, app: Any, fetch: Callable[[str], bytes] = fetch_feed):
        self.app = app
        self.fetch = fetch
        self.path = app.state_dir / FILE
        self.cache_path = app.state_dir / CACHE_FILE
        self.lock = threading.Lock()
        self.refreshing = False
        self.editor_running: dict | None = None
        self.editor_error: str | None = None
        self._outliers: list = []
        self.feed_items: dict[str, list[dict]] = {}
        self.feed_status: dict[str, dict] = {}
        self.items: list[dict] = []
        self.fetched_ms = 0
        self.edit: dict | None = None
        # the last interest profile proposed (profile_start), kept until the next proposal or a restart
        self.profile: dict | None = None
        self.profile_running: dict | None = None
        # raised under self.lock on every change of the state; the page keeps the newer of two states by it
        # (logic.js newerTicker), since an action's answer and the event of a later change may cross
        self.rev = 0
        self._load_cache()

    # ------------------------------------------------------------ settings

    def defaults(self) -> dict:
        return copy.deepcopy(getattr(self.app.cfg, "ticker", None) or DEFAULTS)

    def overrides(self) -> dict:
        """The settings page's changes; a stale or hand-edited value falls back to the config's."""
        data = read_json(self.path)
        if not isinstance(data, dict):
            return {}
        base = self.defaults()
        merged = lenient(data, base)
        return {k: merged[k] for k in KEYS if k in data and merged[k] != base[k]}

    def settings(self) -> dict:
        return {**self.defaults(), **copy.deepcopy(self.overrides())}

    def save(self, change: Any) -> dict:
        if not isinstance(change, dict) or not change:
            raise TickerError(400, "invalid_argument", "must be an object of settings", "settings")
        with self.lock:
            before = self.settings()
            try:
                after = normalize(change, before)
            except TickerSettingsError as error:
                raise TickerError(400, "invalid_argument", error.message, error.field) from None
            base = self.defaults()
            atomic_write_json(self.path, {k: after[k] for k in KEYS if after[k] != base[k]})
            if after["smart"] != before["smart"]:
                self._rebuild(after)
            self.rev += 1
        if after["enabled"] and (after["feeds"] != before["feeds"] or after["per_feed"] != before["per_feed"]
                                 or after["max_items"] != before["max_items"]
                                 or after["refresh_minutes"] != before["refresh_minutes"] or not before["enabled"]):
            self.request_refresh()
        return self.state()

    def reset(self) -> dict:
        with self.lock:
            atomic_write_json(self.path, {})
            self._rebuild(self.settings())
            self.rev += 1
        if self.settings()["enabled"]:
            self.request_refresh()
        return self.state()

    # ------------------------------------------------------------ cache

    def _load_cache(self) -> None:
        data = read_json(self.cache_path)
        if not isinstance(data, dict):
            return
        by_feed = data.get("feed_items")
        if isinstance(by_feed, dict):
            self.feed_items = {k: [i for i in v if isinstance(i, dict) and isinstance(i.get("id"), str)
                                   and isinstance(i.get("title"), str) and url_ok(i.get("url"))]
                               for k, v in by_feed.items() if isinstance(k, str) and isinstance(v, list)}
        status = data.get("feeds")
        if isinstance(status, dict):
            self.feed_status = {k: v for k, v in status.items() if isinstance(k, str) and isinstance(v, dict)}
        items = data.get("items")
        if isinstance(items, list):
            self.items = [i for i in items if isinstance(i, dict) and isinstance(i.get("id"), str)
                          and isinstance(i.get("title"), str) and url_ok(i.get("url"))]
        if _is_int(data.get("fetched_ms")):
            self.fetched_ms = data["fetched_ms"]
        if isinstance(data.get("edit"), dict):
            self.edit = data["edit"]

    def _save_cache(self) -> None:
        """Under self.lock."""
        try:
            atomic_write_json(self.cache_path, {"v": 1, "fetched_ms": self.fetched_ms, "items": self.items,
                                                "feed_items": self.feed_items, "feeds": self.feed_status,
                                                "edit": self.edit})
        except OSError as exc:
            self.app.log_error(f"ticker cache: {exc!r}")

    def _rebuild(self, s: dict) -> None:
        """Under self.lock: the items again from what the feeds last gave, after a change of the selection
        (smart), so muting a term or switching clustering acts at once and fetches nothing."""
        feeds = [f for f in s["feeds"] if f["enabled"]]
        self.items = merge_items([self.feed_items.get(f["id"], []) for f in feeds], s["max_items"], s["smart"],
                                 int(self.app.clock()))
        self._save_cache()

    # ------------------------------------------------------------ fetching

    def refresh_sync(self) -> None:
        """Read every enabled feed, one after the other. A failing feed keeps its earlier items."""
        s = self.settings()
        if not s["enabled"]:
            return
        feeds = [f for f in s["feeds"] if f["enabled"]]
        results: dict[str, tuple[list[dict] | None, str | None]] = {}
        for feed in feeds:
            try:
                results[feed["id"]] = (parse_feed(self.fetch(feed["url"]), feed, s["per_feed"]), None)
            except FeedError as error:
                results[feed["id"]] = (None, str(error)[:120] or "failed")
            except Exception as error:  # noqa: BLE001 (one broken feed never stops the others)
                results[feed["id"]] = (None, type(error).__name__)
        try:
            outliers = self.app.usage.view().get("outliers") or []
        except Exception:  # noqa: BLE001 (the token view is an extra)
            outliers = []
        now = int(self.app.clock())
        with self.lock:
            ids = {f["id"] for f in s["feeds"]}
            self.feed_items = {k: v for k, v in self.feed_items.items() if k in ids}
            self.feed_status = {k: v for k, v in self.feed_status.items() if k in ids}
            for fid, (items, error) in results.items():
                if items is not None:
                    self.feed_items[fid] = items
                self.feed_status[fid] = {"ok": error is None, "error": error, "fetched_ms": now,
                                         "count": len(items) if items is not None else len(self.feed_items.get(fid, []))}
            self.items = merge_items([self.feed_items.get(f["id"], []) for f in feeds], s["max_items"], s["smart"], now)
            self.fetched_ms = now
            self._outliers = outliers if isinstance(outliers, list) else []
            self._save_cache()
            self.rev += 1
        errors = [e for _, e in results.values() if e]
        if results and len(errors) == len(results):
            self.app.note(self.app.tx["ticker_refresh_failed"].format(err=errors[0]), "bad")
        self.app.broadcast("ticker", self.state())

    def request_refresh(self) -> bool:
        with self.lock:
            if self.refreshing:
                return False
            self.refreshing = True
            self.rev += 1
        threading.Thread(target=self._refresh, name="bridge-cockpit-ticker", daemon=True).start()
        return True

    def _refresh(self) -> None:
        try:
            self.refresh_sync()
        except Exception as exc:  # noqa: BLE001 (a failed refresh must never leave `refreshing` set)
            self.app.log_error(f"ticker: {exc!r}")
        finally:
            with self.lock:
                self.refreshing = False
                self.rev += 1
            self.app.broadcast("ticker", self.state())

    def due(self, now: float) -> bool:
        s = self.settings()
        return bool(s["enabled"] and self.app.client_count() > 0
                    and now - self.fetched_ms >= s["refresh_minutes"] * 60000)

    def loop(self) -> None:
        """Started by App.start() only: reads the feeds while a page is open and they are old. Never edits."""
        while not self.app.stopping:
            try:
                if self.due(self.app.clock()):
                    self.request_refresh()
            except Exception as exc:  # noqa: BLE001 (the ticker never takes the server down)
                self.app.log_error(f"ticker loop: {exc!r}")
            time.sleep(LOOP_STEP_S)

    # ------------------------------------------------------------ the editor

    def edit_start(self) -> bool:
        s = self.settings()
        if getattr(self.app.runner, "claude", None) is None:
            raise TickerError(409, "not_applicable", "claude is not available")
        if not s["editor"]["enabled"]:
            raise TickerError(409, "not_applicable", "the editor is switched off (cockpit.ticker.editor)")
        with self.lock:
            if not self.items:
                raise TickerError(409, "not_applicable", "there are no items to edit")
            if self.editor_running:
                return False
            self.editor_running = {"started_ms": int(self.app.clock())}
            self.editor_error = None
            self.rev += 1
            items = [dict(i) for i in self.items]
        threading.Thread(target=self._edit, args=(items, s["editor"], s["smart"]["mute"]), name="bridge-cockpit-ticker-edit",
                         daemon=True).start()
        self.app.broadcast("ticker", self.state())
        return True

    def _edit(self, items: list[dict], editor: dict, mute: list[str]) -> None:
        app = self.app
        started = app.clock()
        try:
            prompt, prompted = edit_prompt(editor["interests"], items, editor["max_picks"], editor["shorten"], mute)
            if len(prompt) > mr.HAIKU_PROMPT_MAX:
                raise RuntimeError("prompt too long")
            run = app.run(mr.haiku_argv(app.runner.claude, prompt), EDITOR_TIMEOUT)
            if not run.ok:
                err = (run.err or "").strip().splitlines()[-1:] or [f"exit {run.code}"]
                raise RuntimeError(app.scrub(err[0])[:200])
            picks, cost = parse_edit(run.out, len(prompted), editor["max_picks"], editor["shorten"])
            if not picks:
                raise RuntimeError("no usable pick in the answer")
            order = [prompted[i] for i, _ in picks]
            # `seen` is every item there was when the edit started, also those the prompt budget left
            # out: only an item fetched after the edit counts as fresh. `of` is what the editor read.
            with self.lock:
                self.edit = {"key": edit_key(editor, mute), "at_ms": int(app.clock()), "order": order,
                             "short": {prompted[i]: s for i, s in picks}, "of": len(prompted),
                             "seen": [i["id"] for i in items],
                             "duration_ms": int(app.clock() - started), "cost_usd": cost}
                self._save_cache()
            app.note(app.tx["ticker_edit_done"].format(n=len(order), of=len(prompted)), "ok")
        except Exception as exc:  # noqa: BLE001 (a failed edit must never leave `running` set)
            message = str(exc)[:200] or type(exc).__name__
            with self.lock:
                self.editor_error = message
            app.note(app.tx["ticker_edit_failed"].format(err=message), "bad")
            app.log_error(f"ticker edit: {exc!r}")
        finally:
            with self.lock:
                self.editor_running = None
                self.rev += 1
            app.broadcast("ticker", self.state())

    # ------------------------------------------------------------ the interest profile

    def task_titles(self) -> list[str]:
        collector = getattr(self.app, "collector", None)
        tasks = list(getattr(collector, "tasks", None) or [])
        return [t.get("title") or t.get("label") or "" for t in tasks if isinstance(t, dict)][:PROFILE_TASKS_MAX]

    def profile_start(self, llm: bool) -> bool:
        """Propose interests from the open tasks: keywords at once, or Haiku's line on a thread. False when
        a proposal is already being written."""
        s = self.settings()
        titles = [t for t in self.task_titles() if t.strip()]
        if not titles:
            raise TickerError(409, "not_applicable", "there are no open tasks to read interests from")
        if llm:
            if getattr(self.app.runner, "claude", None) is None:
                raise TickerError(409, "not_applicable", "claude is not available")
            if not s["editor"]["enabled"]:
                raise TickerError(409, "not_applicable", "the editor is switched off (cockpit.ticker.editor)")
        with self.lock:
            if self.profile_running:
                return False
            if not llm:
                self.profile = {"text": profile_keywords(titles), "llm": False, "at_ms": int(self.app.clock()),
                                "from": len(titles), "error": None, "cost_usd": None}
                self.rev += 1
                return True
            self.profile_running = {"started_ms": int(self.app.clock())}
            self.rev += 1
        threading.Thread(target=self._profile, args=(titles, s["editor"]["interests"]),
                         name="bridge-cockpit-ticker-profile", daemon=True).start()
        return True

    def _profile(self, titles: list[str], current: str) -> None:
        app = self.app
        try:
            prompt = profile_prompt(titles, current)
            if len(prompt) > mr.HAIKU_PROMPT_MAX:
                raise RuntimeError("prompt too long")
            run = app.run(mr.haiku_argv(app.runner.claude, prompt), EDITOR_TIMEOUT)
            if not run.ok:
                err = (run.err or "").strip().splitlines()[-1:] or [f"exit {run.code}"]
                raise RuntimeError(app.scrub(err[0])[:200])
            text, cost = _haiku_text(run.out)
            first = text.strip().splitlines()[0] if text.strip() else ""
            line = clean_text(first.strip().strip('"\'').strip(), 500)
            if not line:
                raise RuntimeError("no usable profile in the answer")
            with self.lock:
                self.profile = {"text": line, "llm": True, "at_ms": int(app.clock()), "from": len(titles),
                                "error": None, "cost_usd": cost}
        except Exception as exc:  # noqa: BLE001 (a failed proposal must never leave `running` set)
            message = str(exc)[:200] or type(exc).__name__
            with self.lock:
                self.profile = {"text": "", "llm": True, "at_ms": int(app.clock()), "from": len(titles),
                                "error": message, "cost_usd": None}
            app.log_error(f"ticker profile: {exc!r}")
        finally:
            with self.lock:
                self.profile_running = None
                self.rev += 1
            app.broadcast("ticker", self.state())

    # ------------------------------------------------------------ the page

    def pass_recorded(self) -> None:
        """Called by the collector after each collect pass: the status band's slow-pass and token-outlier
        items read perf, so a pass sends it at once instead of waiting for the next feed refresh. The token view
        is the last one known: scanning the transcripts here would hold up the collector (usage.latest)."""
        if not self.settings()["enabled"]:
            return
        try:
            known = self.app.usage.latest()
            outliers = (known.get("outliers") or []) if known is not None else None
        except Exception:  # noqa: BLE001 (the token view is an extra)
            outliers = None
        with self.lock:
            if isinstance(outliers, list):
                self._outliers = outliers
            self.rev += 1
        self.app.broadcast("ticker", self.state())

    def perf(self) -> dict:
        collector = getattr(self.app, "collector", None)
        return {"passes": list(getattr(collector, "passes", ()) or ()), "outliers": list(self._outliers)}

    def state(self) -> dict:
        s = self.settings()
        base = self.defaults()
        claude = getattr(self.app.runner, "claude", None)
        from .collector import COLLECT_TIMEOUT
        with self.lock:
            edit = self.edit if self.edit and self.edit.get("key") == edit_key(s["editor"], s["smart"]["mute"]) else None
            if not s["enabled"]:
                items = []
            elif edit:
                by_id = {i["id"]: i for i in self.items}
                seen = set(edit.get("seen") or [])
                short = edit.get("short") or {}
                items = [{**by_id[k], "short": short.get(k), "fresh": False}
                         for k in edit.get("order") or [] if k in by_id]
                items += [{**i, "short": None, "fresh": True} for i in self.items if i["id"] not in seen]
            else:
                items = [{**i, "short": None, "fresh": False} for i in self.items]
            feeds = []
            for f in s["feeds"]:
                st = self.feed_status.get(f["id"]) or {}
                feeds.append({"id": f["id"], "name": f["name"], "ok": st.get("ok"), "error": st.get("error"),
                              "fetched_ms": st.get("fetched_ms"), "count": st.get("count", 0)})
            last = None
            if edit:
                last = {"at_ms": edit.get("at_ms"), "picked": len(edit.get("order") or []), "of": edit.get("of"),
                        "duration_ms": edit.get("duration_ms"), "cost_usd": edit.get("cost_usd")}
            editor = {"available": claude is not None and s["editor"]["enabled"],
                      "running": dict(self.editor_running) if self.editor_running else None,
                      "error": self.editor_error, "last": last}
            profile = {"running": dict(self.profile_running) if self.profile_running else None,
                       "last": dict(self.profile) if self.profile else None,
                       "tasks": len([t for t in self.task_titles() if t.strip()])}
            refreshing, fetched, rev = self.refreshing, self.fetched_ms or None, self.rev
        return {"rev": rev, "enabled": s["enabled"], "settings": s, "defaults": base,
                "overridden": sorted(k for k in KEYS if s[k] != base[k]),
                "items": items, "feeds": feeds, "fetched_ms": fetched, "refreshing": refreshing,
                "editor": editor, "profile": profile, "perf": self.perf(), "limits": {"timeout_ms": COLLECT_TIMEOUT * 1000}}
