"""The contact footer, read from a persona and rendered as mail-safe HTML.

A footer is configuration, not code. It lives in
`identity/mail-footers/<id>.yaml`, borrows name, email and phone from the
persona it names (`persona_ref`), and the person who takes over the Bridge
edits that YAML. This module only resolves and renders it.

Building blocks, all optional (identity/mail-footers/_schema.yaml lists them):

    wordmark   two-line text logo left of the contact block
    name, role, org, website, phone, email
    links      a row of small coloured badges, each with a label
    cards      tiles with kicker, title, text and a link; two share a row
    cta        one button ("Book a call"), Outlook-safe
    notice     a dated line ("Out of office until 20 Oct") that hides itself
               outside its from/until window, so a stale notice never ships
    tagline    one line under a rule: what you are working on, with a link
    legal      small print, one entry per line

Styles: `card` shows everything, `compact` is two lines plus badges and legal
(a reply), `minimal` is two lines (a list), `text` is the text rendering in
the HTML part too (a recipient who reads mail as text).

There are no images. Outlook blocks remote images by default and some clients
show embedded ones as attachments, so a footer that depends on a logo arrives
broken for a share of recipients. The wordmark is text for that reason.

Everything is a table cell with hex colours in the tag. HTML copied out of a
browser carries `var(--x)` and `calc()`, which no mail client resolves.
"""

from __future__ import annotations

import datetime as dt
import re
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from .config import ConfigError, load_yaml

# A recipient name is put into a URL only when it is plainly a name: letters,
# spaces, dot, apostrophe, hyphen, at most 40 characters. Anything else (an
# address, a number, markup) leaves the link without a query.
PLAIN_NAME = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'-]){0,39}$")

MAX_EXTENDS = 5


class FooterError(ConfigError):
    pass


# ----------------------------------------------------------------- loading --

FAMILY = ("identity", "mail-footers")
CONTENT_KEYS = ("style", "name", "role", "org", "website", "phone", "email", "sender", "wordmark",
                "links", "cards", "cta", "notice", "tagline", "legal", "visitor_params")


def family_dir(root: Path) -> Path:
    return root.joinpath(*FAMILY)


def available(root: Path) -> dict[str, dict]:
    """id -> raw file content for every footer in this Bridge."""
    out: dict[str, dict] = {}
    d = family_dir(root)
    if d.is_dir():
        for path in sorted(d.glob("*.yaml")):
            if not path.name.startswith("_"):
                out[path.stem] = load_yaml(path)
    return out


def _persona_defaults(root: Path, persona: str) -> dict:
    path = root / "identity" / "personas" / f"{persona}.yaml"
    if not path.is_file():
        raise FooterError(f"persona_ref '{persona}': {path.relative_to(root)} does not exist")
    data = load_yaml(path)
    persons = data.get("persons") or [{}]
    channels = (persons[0] or {}).get("channels") or {}
    found = {"name": data.get("display_name"), "email": channels.get("email"), "phone": channels.get("phone")}
    return {k: v for k, v in found.items() if v}


def _merged(files: dict, fid: str, chain: list[str]) -> dict:
    if fid in chain:
        raise FooterError(f"footer '{fid}': extends loops back ({' -> '.join(chain + [fid])})")
    if len(chain) >= MAX_EXTENDS:
        raise FooterError(f"footer '{fid}': extends is nested deeper than {MAX_EXTENDS}")
    if fid not in files:
        where = f"footer '{chain[-1]}' extends '{fid}'" if chain else f"footer '{fid}'"
        known = ", ".join(sorted(files)) or "none"
        raise FooterError(f"{where}, which is not defined (defined: {known})")
    own = dict(files[fid] or {})
    parent = own.pop("extends", None)
    if not parent:
        return own
    base = _merged(files, parent, chain + [fid])
    # Maps merge (a child's `notice: {text}` keeps the parent's from/until),
    # lists replace (a child's `cards: []` means no cards).
    for key, value in own.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def load(root: Path, fid: str, language: str = "", default_language: str = "en",
         style: str = "", files: dict | None = None) -> dict:
    """The footer `fid`, resolved: extends, persona defaults, language variant, style.

    The result carries `_id` and `_language` for the callers that report.
    """
    files = available(root) if files is None else files
    raw = _merged(files, fid, [])
    cfg: dict = {}
    if raw.get("persona_ref"):
        cfg.update(_persona_defaults(root, str(raw["persona_ref"])))
    cfg.update({k: v for k, v in raw.items() if k in CONTENT_KEYS})
    base_lang = str(raw.get("language") or default_language)
    lang = base_lang
    if language and language != base_lang:
        variant = (raw.get("variants") or {}).get(language)
        if variant is None and "-" in language:
            variant = (raw.get("variants") or {}).get(language.split("-")[0])
        if variant is not None:
            for key, value in variant.items():
                if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    cfg[key] = {**cfg[key], **value}
                else:
                    cfg[key] = value
            lang = language
    if style:
        cfg["style"] = style
    cfg.setdefault("style", "card")
    cfg["_id"] = fid
    cfg["_language"] = lang
    if raw.get("persona_ref"):
        cfg["_persona"] = str(raw["persona_ref"])
    return cfg


def persona_signature(root: Path, persona: str) -> str:
    path = root / "identity" / "personas" / f"{persona}.yaml"
    if not path.is_file():
        raise FooterError(f"persona '{persona}': {path.relative_to(root)} does not exist")
    return str(load_yaml(path).get("signature") or "").strip()


def sender_of(cfg: dict) -> str:
    return str(cfg.get("sender") or cfg.get("email") or "")


# ------------------------------------------------------------- recipients --

def visitor_query(cfg: dict, recipient: str = "", informal: bool = False) -> str:
    """The query a link may carry so the page it opens can greet the reader.

    `{visitor_query}` in a URL becomes `?for=Anna` (parameter names from the
    footer's `visitor_params`), or nothing when there is no plain name.
    """
    name = re.sub(r"\s+", " ", (recipient or "").strip())
    if not name or not PLAIN_NAME.match(name):
        return ""
    params = cfg.get("visitor_params") or {}
    query = {str(params.get("name", "for")): name}
    extra = params.get("informal")
    if informal and extra:
        key, _, value = str(extra).partition("=")
        query[key] = value or "1"
    return "?" + urlencode(query)


SAFE_URL = re.compile(r"^(https?:|mailto:|tel:)", re.I)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _url(url: str, cfg: dict, recipient: str, informal: bool) -> str:
    """The link target, or "#" for anything that is not http(s), mailto or tel.

    A footer is a YAML file, possibly shipped by an org overlay, and compose
    does not trust it to have passed `validate`: a `javascript:` website must
    not become a live link in a recipient's client.
    """
    value = str(url).replace("{visitor_query}", visitor_query(cfg, recipient, informal))
    return value if SAFE_URL.match(value) else "#"


def unsafe_urls(cfg: dict) -> list[str]:
    return [u for u in urls(cfg) if not SAFE_URL.match(u.replace("{visitor_query}", ""))]


def notice_active(notice: dict, today: dt.date) -> bool:
    def day(key):
        value = notice.get(key)
        if not value:
            return None
        return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
    start, end = day("from"), day("until")
    if start and today < start:
        return False
    if end and today > end:
        return False
    return True


def _color(value, theme: dict) -> str:
    """A hex code as written, else a theme role, else a DESIGN.md token, else primary."""
    value = str(value or "primary")
    if value.startswith("#"):
        # Only a real hex code reaches a style attribute; anything else could close it.
        return value if HEX.match(value) else str(theme.get("primary"))
    role = theme.get(value)
    if isinstance(role, str) and role.startswith("#"):
        return role
    return str(getattr(theme, "tokens", {}).get(value) or theme.get("primary"))


def _tel(phone: str) -> str:
    return "tel:" + re.sub(r"[^\d+]", "", phone)


def _bare(url: str) -> str:
    return re.sub(r"^https?://", "", url).rstrip("/")


# -------------------------------------------------------------------- html --

def render_html(cfg: dict, theme: dict, recipient: str = "", informal: bool = False,
                today: dt.date | None = None) -> str:
    """One footer, in the style it asks for (card, compact, minimal, text)."""
    today = today or dt.date.today()
    style = cfg.get("style") or "card"
    if style == "text":
        body = "<br />".join(escape(x) for x in render_text(cfg, recipient, informal, today).splitlines())
        return (f'<p class="e-muted" style="margin:28px 0 0;font-family:{theme["font_body"]};font-size:13px;'
                f'line-height:1.5;color:{theme["text_muted"]};">{body}</p>')
    if style in ("compact", "minimal"):
        return _render_short(cfg, theme, recipient, informal, today, minimal=style == "minimal")
    c = theme
    font = c["font_body"]
    e = escape

    def u(url: str) -> str:
        return e(_url(url, cfg, recipient, informal))

    wm = cfg.get("wordmark") or {}
    website = _url(cfg["website"], cfg, recipient, informal) if cfg.get("website") else ""
    wordmark = ""
    if wm:
        link_open = f'<a href="{e(website)}" style="text-decoration:none;">' if website else ""
        wordmark = (
            f'<td class="e-rule" style="padding-right:16px;border-right:1px solid {c["border"]};'
            f'vertical-align:middle;text-align:center;">{link_open}'
            f'<div class="e-h" style="font-family:{c["font_display"]};font-size:24px;font-weight:bold;'
            f'color:{c["primary"]};letter-spacing:.02em;line-height:1.1;">{e(str(wm.get("top", "")))}</div>'
            f'<div class="e-muted" style="font-family:{font};font-size:9.5px;color:{c["text_muted"]};'
            f'letter-spacing:.2em;">{e(str(wm.get("bottom", "")))}</div>'
            + ("</a>" if website else "") + "</td>")

    small = f"font-family:{font};font-size:12.5px;color:{c['text_muted']};"
    lines = []
    if cfg.get("name"):
        lines.append(f'<div class="e-h" style="font-family:{font};font-size:14px;font-weight:bold;'
                     f'color:{c["primary"]};">{e(cfg["name"])}</div>')
    if cfg.get("role"):
        lines.append(f'<div class="e-muted" style="{small}">{e(cfg["role"])}</div>')
    org_bits = []
    if cfg.get("org"):
        org = e(cfg["org"])
        if website:
            org = f'<a class="e-muted" href="{e(website)}" style="color:{c["text_muted"]};text-decoration:none;">{org}</a>'
        org_bits.append(org)
    if website:
        org_bits.append(f'<a class="e-link" href="{e(website)}" style="color:{c["link"]};'
                        f'text-decoration:none;">{e(_bare(website))}</a>')
    if org_bits:
        lines.append(f'<div class="e-muted" style="{small}">{" &middot; ".join(org_bits)}</div>')
    reach = []
    if cfg.get("phone"):
        reach.append(f'<a class="e-muted" href="{_tel(cfg["phone"])}" style="color:{c["text_muted"]};'
                     f'text-decoration:none;">{e(cfg["phone"])}</a>')
    if cfg.get("email"):
        reach.append(f'<a class="e-muted" href="mailto:{e(cfg["email"])}" style="color:{c["text_muted"]};'
                     f'text-decoration:none;">{e(cfg["email"])}</a>')
    if reach:
        lines.append(f'<div class="e-muted" style="{small}margin-bottom:7px;">{" &middot; ".join(reach)}</div>')

    links = cfg.get("links") or []
    if links:
        cells = []
        for i, link in enumerate(links):
            pad = "0 0 0 6px" if i == len(links) - 1 else "0 14px 0 6px"
            href = u(link["url"])
            # Badge and label lead to the same place, both are clickable.
            cells.append(
                f'<td style="background-color:{_color(link.get("color"), c)};font-family:{font};'
                f'font-size:10.5px;font-weight:bold;min-width:22px;padding:0 4px;height:18px;'
                f'text-align:center;border-radius:3px;white-space:nowrap;">'
                f'<a href="{href}" style="color:#ffffff;text-decoration:none;display:block;">'
                f'{e(str(link.get("badge", "")))}</a></td>'
                f'<td style="padding:{pad};font-family:{font};font-size:12.5px;white-space:nowrap;">'
                f'<a class="e-p" href="{href}" style="color:{c["text"]};text-decoration:none;">'
                f'{e(str(link.get("label", "")))}</a></td>')
        lines.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                     'style="border-collapse:collapse;"><tr>' + "".join(cells) + "</tr></table>")

    block = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin-top:28px;border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;"><tr>'
        + wordmark
        + f'<td style="padding-left:{16 if wordmark else 0}px;vertical-align:middle;">' + "".join(lines) + "</td>"
        + "</tr></table>")

    notice = cfg.get("notice")
    if isinstance(notice, dict) and notice.get("text") and notice_active(notice, today):
        text = e(str(notice["text"]))
        if notice.get("url"):
            text = (f'{text} <a class="e-link" href="{u(notice["url"])}" style="color:{c["link"]};">'
                    f'{e(_bare(str(notice["url"])))}</a>')
        block += (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;'
            f'border-collapse:collapse;"><tr><td class="e-warn" style="background-color:{c["muted_bg"]};'
            f'border-left:3px solid {c["warning"]};padding:8px 12px;font-family:{font};font-size:12.5px;'
            f'line-height:1.5;color:{c["text"]};">{text}</td></tr></table>')

    cta = cfg.get("cta")
    if isinstance(cta, dict) and cta.get("label") and cta.get("url"):
        from .markdown import button_html  # noqa: PLC0415 - one renderer for every button
        block += f'<div style="margin-top:14px;">{button_html(str(cta["label"]), _url(cta["url"], cfg, recipient, informal), c, small=True)}</div>'

    block += _cards_html(cfg.get("cards") or [], cfg, recipient, informal, c)

    tag = cfg.get("tagline")
    if isinstance(tag, dict):
        name = (f' <strong class="e-h" style="color:{c["primary"]};">{e(tag["name"])}</strong>,'
                if tag.get("name") else "")
        raw = str(tag.get("url") or "")
        url = _url(raw, cfg, recipient, informal) if raw else ""
        link = (f' <a class="e-link" href="{e(url)}" style="color:{c["link"]};">{e(_bare(raw))}</a>'
                if url else "")
        block += (
            f'<div class="e-rule" style="border-top:1px solid {c["border"]};margin-top:16px;padding-top:10px;">'
            f'<p class="e-muted" style="margin:0;font-family:{font};font-size:12px;line-height:1.5;'
            f'color:{c["text_muted"]};">{e(str(tag.get("lead", "")))}{name} {e(str(tag.get("text", "")))}{link}</p></div>')

    legal = cfg.get("legal") or []
    if legal:
        block += (
            f'<p class="e-muted" style="margin:10px 0 0;font-family:{font};font-size:10.5px;line-height:1.5;'
            f'color:{c["text_muted"]};">' + "<br />".join(e(str(x)) for x in legal) + "</p>")
    return block


def _render_short(cfg: dict, c: dict, recipient: str, informal: bool, today: dt.date, minimal: bool) -> str:
    """compact: one rule, a name line, a contact line, badges inline, legal.
    minimal: the name line and the contact line, nothing else."""
    e = escape
    font = c["font_body"]
    small = f"font-family:{font};font-size:12.5px;line-height:1.6;color:{c['text_muted']};"
    head = [f'<strong class="e-h" style="color:{c["primary"]};">{e(cfg["name"])}</strong>'] if cfg.get("name") else []
    head += [e(str(cfg[k])) for k in ("role", "org") if cfg.get(k)]
    reach = []
    if cfg.get("phone"):
        reach.append(f'<a class="e-muted" href="{_tel(cfg["phone"])}" style="color:{c["text_muted"]};'
                     f'text-decoration:none;">{e(cfg["phone"])}</a>')
    if cfg.get("email"):
        reach.append(f'<a class="e-muted" href="mailto:{e(cfg["email"])}" style="color:{c["text_muted"]};'
                     f'text-decoration:none;">{e(cfg["email"])}</a>')
    if cfg.get("website"):
        reach.append(f'<a class="e-link" href="{e(_url(cfg["website"], cfg, recipient, informal))}" '
                     f'style="color:{c["link"]};text-decoration:none;">{e(_bare(cfg["website"]))}</a>')
    if not minimal:
        for link in cfg.get("links") or []:
            reach.append(f'<a class="e-link" href="{e(_url(link["url"], cfg, recipient, informal))}" '
                         f'style="color:{c["link"]};text-decoration:none;">{e(str(link.get("label", "")))}</a>')
    out = (f'<div class="e-rule" style="margin-top:26px;padding-top:10px;border-top:1px solid {c["border"]};">'
           f'<p class="e-muted" style="margin:0;{small}">{" &middot; ".join(head)}'
           + (f'<br />{" &middot; ".join(reach)}' if reach else "") + "</p>")
    if not minimal:
        notice = cfg.get("notice")
        if isinstance(notice, dict) and notice.get("text") and notice_active(notice, today):
            out += f'<p class="e-p" style="margin:6px 0 0;{small}color:{c["text"]};">{e(str(notice["text"]))}</p>'
        if cfg.get("legal"):
            out += (f'<p class="e-muted" style="margin:6px 0 0;font-family:{font};font-size:10.5px;line-height:1.5;'
                    f'color:{c["text_muted"]};">' + "<br />".join(e(str(x)) for x in cfg["legal"]) + "</p>")
    return out + "</div>"


def _card_cell(card: dict, cfg: dict, recipient: str, informal: bool, c: dict, span: int) -> str:
    font = c["font_body"]
    e = escape
    href = e(_url(card["url"], cfg, recipient, informal))
    inner = (
        f'<a href="{href}" style="display:block;text-decoration:none;color:{c["text"]};">'
        f'<div class="e-link" style="font-family:{font};font-size:10px;font-weight:bold;letter-spacing:.12em;'
        f'text-transform:uppercase;color:{c["link"]};">{e(str(card.get("kicker", "")))}</div>'
        f'<div class="e-h" style="font-family:{font};font-size:13px;font-weight:bold;color:{c["primary"]};'
        f'padding:2px 0 4px;">{e(str(card.get("title", "")))}</div>'
        f'<div class="e-muted" style="font-family:{font};font-size:12px;line-height:1.4;color:{c["text_muted"]};">'
        f'{e(str(card.get("text", "")))}</div></a>')
    return (
        f'<td class="e-callout" valign="top" width="{100 if span == 2 else 50}%" colspan="{span}" '
        f'style="background-color:{c["accent_subtle"] or c["muted_bg"]};border:1px solid '
        f'{c["accent_line"] or c["border"]};color:{c["text"]};padding:10px 12px;">{inner}</td>')


def _cards_html(cards: list, cfg: dict, recipient: str, informal: bool, c: dict) -> str:
    """Two cards per row, `wide: true` alone. Tables only, no flex, no calc()."""
    if not cards:
        return ""
    rows: list[str] = []
    buf: list[dict] = []

    def flush():
        for i in range(0, len(buf), 2):
            pair = buf[i:i + 2]
            span = 2 if len(pair) == 1 else 1
            rows.append("".join(_card_cell(x, cfg, recipient, informal, c, span) for x in pair))
        buf.clear()

    for card in cards:
        if card.get("wide"):
            flush()
            rows.append(_card_cell(card, cfg, recipient, informal, c, 2))
        else:
            buf.append(card)
    flush()
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="6" border="0" '
            'style="margin-top:12px;border-collapse:separate;">'
            + "".join(f"<tr>{r}</tr>" for r in rows) + "</table>")


def render_signature_html(text: str, theme: dict) -> str:
    """The persona's plain `signature` block, when no structured footer is chosen."""
    body = "<br />".join(escape(line) for line in str(text).strip().splitlines())
    return (f'<p class="e-muted" style="margin:28px 0 0;font-family:{theme["font_body"]};font-size:13px;'
            f'line-height:1.5;color:{theme["text_muted"]};">{body}</p>')


# -------------------------------------------------------------------- text --

def render_text(cfg: dict, recipient: str = "", informal: bool = False, today: dt.date | None = None) -> str:
    """Plain-text footer: every address written out, for text mails and chat previews."""
    today = today or dt.date.today()
    if cfg.get("style") == "minimal":
        first = " · ".join(str(cfg[k]) for k in ("name", "role", "org") if cfg.get(k))
        second = " · ".join(str(cfg[k]) for k in ("phone", "email", "website") if cfg.get(k))
        return "\n".join(x for x in (first, second) if x)
    head = " · ".join(x for x in [cfg.get("name", ""), cfg.get("org", ""), cfg.get("website", "")] if x)
    out = [head] if head else []
    if cfg.get("role"):
        out.append(cfg["role"])
    if cfg.get("phone"):
        out.append(f'Phone: {cfg["phone"]}')
    if cfg.get("email"):
        out.append(f'Mail: {cfg["email"]}')
    for link in cfg.get("links") or []:
        out.append(f'{link.get("label", "")}: {_url(link["url"], cfg, recipient, informal)}')
    notice = cfg.get("notice")
    if isinstance(notice, dict) and notice.get("text") and notice_active(notice, today):
        out += ["", str(notice["text"]) + (f' {notice["url"]}' if notice.get("url") else "")]
    cta = cfg.get("cta")
    if isinstance(cta, dict) and cta.get("label") and cta.get("url"):
        out += ["", f'{cta["label"]}: {_url(cta["url"], cfg, recipient, informal)}']
    for card in cfg.get("cards") or []:
        out += ["", f'{card.get("kicker", "")}: {card.get("title", "")}'.strip(": "),
                str(card.get("text", "")), _url(card["url"], cfg, recipient, informal)]
    tag = cfg.get("tagline")
    if isinstance(tag, dict):
        lead = " ".join(x for x in [tag.get("lead", ""), (tag["name"] + ",") if tag.get("name") else "",
                                    tag.get("text", "")] if x)
        out += ["", lead]
        if tag.get("url"):
            out.append(tag["url"])
    if cfg.get("legal"):
        out += [""] + [str(x) for x in cfg["legal"]]
    return "\n".join(out).strip("\n")


def urls(cfg: dict) -> list[str]:
    """Every URL a footer links to, for the preflight check."""
    found = [cfg.get("website") or ""]
    found += [x.get("url", "") for x in cfg.get("links") or []]
    found += [x.get("url", "") for x in cfg.get("cards") or []]
    for key in ("tagline", "notice", "cta"):
        if isinstance(cfg.get(key), dict):
            found.append(cfg[key].get("url", ""))
    return [str(x) for x in found if x]
