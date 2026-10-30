"""From a request to a finished draft: profile, recipients, words, dress, checks.

Nothing in here talks to a mail client. `build()` returns a `Draft` holding the
HTML, the text part, the envelope and every decision with its reason, and the
caller decides where it goes (a client, an .eml, a preview, only a report).
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import footer as footer_mod
from . import lint, profiles, recipients, theme as theme_mod
from .config import ConfigError, MailConfig
from .markdown import Renderer, document, to_text

PLACEHOLDER = re.compile(r"\{(first_name|last_name|name|group|sender_name|sender_first_name|subject|date)\}")
SNIPPET = re.compile(r"\{\{\s*snippet:([a-z0-9_-]+)\s*\}\}", re.I)


@dataclass
class Request:
    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    profile: str = ""
    footer: str | None = None          # None = profile decides, "" = no footer
    footer_style: str = ""
    theme: str = ""
    lang: str = ""
    address_form: str = ""
    client: str = ""
    priority: str = ""
    preheader: str = ""
    greeting: bool = True
    recipient_name: str = ""
    today: dt.date | None = None
    # A reply keeps the subject it was given (no profile template around
    # "Re: ...") and has no masthead: the quote below it is the context.
    reply: bool = False


@dataclass
class Draft:
    to: list = field(default_factory=list)
    cc: list = field(default_factory=list)
    bcc: list = field(default_factory=list)
    subject: str = ""
    markdown: str = ""
    html: str = ""
    text: str = ""
    attachments: list[Path] = field(default_factory=list)
    sender: str = ""
    client: str = ""
    priority: str = "normal"
    profile_id: str = ""
    footer_id: str = ""
    language: str = ""
    address_form: str = ""
    theme_name: str = ""
    style_skill: str = ""
    today: dt.date = field(default_factory=dt.date.today)
    decisions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    footer_cfg: dict = field(default_factory=dict)
    theme: dict = field(default_factory=dict)
    content: str = ""                 # rendered body + footer, before the document shell
    html_static: str = ""             # the same mail without dark-mode rules (see markdown.document)
    shell: dict = field(default_factory=dict)  # title, eyebrow, preheader, lang for the shell

    def explain(self) -> str:
        lines = [f"profile   {self.profile_id}", f"footer    {self.footer_id or '(none)'}",
                 f"language  {self.language}  ({self.address_form})", f"theme     {self.theme_name}",
                 f"client    {self.client}", f"sender    {self.sender or '(client default)'}"]
        lines += ["", "why:"] + [f"  - {d}" for d in self.decisions]
        return "\n".join(lines)


def _fill(template: str, ctx: dict) -> str:
    return PLACEHOLDER.sub(lambda m: str(ctx.get(m.group(1), "")), template)


def _signed_off(body: str, sign_off: str, sender_name: str) -> bool:
    """Does the body already end with a closing of its own?

    Yes when one of its last three lines starts like the profile's closing line
    ("Best,", "Kind regards"), or names the sender. Without a footer the sender
    name is unknown, so the closing phrase is what decides.
    """
    tail = [x.strip().lower() for x in body.strip().split("\n")[-3:] if x.strip()]
    first = sign_off.split("\n", 1)[0].strip().lower().rstrip(",.!")
    names = {n.lower() for n in (sender_name, sender_name.split()[0] if sender_name else "") if n}
    for line in tail:
        if first and line.startswith(first):
            return True
        if names and any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", line) for n in names):
            return True
    return False


LINK_TARGET = re.compile(r"(\]\()([^)\s]+)(\))")
ALIAS_SHAPE = re.compile(r"^[a-z][a-z0-9_-]*:[\w][\w./#-]*$", re.I)
URL_SCHEMES = ("http:", "https:", "mailto:", "tel:", "attachment:")


def _resolve_link_aliases(body: str, aliases: dict, d) -> str:
    """`[text](site:home)` to `[text](https://...)` from the alias map.

    A target that looks like an alias (`word:word`) but is not a URL scheme and
    not in the map is an error: it would reach the recipient as dead text. An
    alias whose target is not http(s), mailto or tel is an error too, and stays
    unresolved, so the renderer shows it as text and never as a link.
    """
    aliases = {str(k).lower(): str(v) for k, v in (aliases or {}).items()}

    def sub(m):
        target = m.group(2)
        low = target.lower()
        if low.startswith(URL_SCHEMES) or not ALIAS_SHAPE.match(target):
            return m.group(0)
        url = aliases.get(low)
        if url is None:
            d.errors.append(f"link target '{target}' is neither a URL nor a link alias "
                            "(link_aliases in the profile or bridge-config.yaml mail:)")
            return m.group(0)
        if not re.match(r"^(https?://|mailto:|tel:)", url, re.I):
            d.errors.append(f"link alias '{target}' points at '{url}', not an http(s), mailto or tel URL")
            return m.group(0)
        return m.group(1) + url + m.group(3)
    return LINK_TARGET.sub(sub, body)


def _expand_path(raw: str, root: Path) -> Path:
    text = os.path.expandvars(os.path.expanduser(raw.replace("${home}", "~")))
    p = Path(text)
    return p if p.is_absolute() else root / p


def default_client() -> str:
    return "apple-mail" if platform.system() == "Darwin" else "eml"


def build(req: Request, cfg: MailConfig) -> Draft:
    root = cfg.root
    d = Draft()
    today = req.today or dt.date.today()
    d.today = today
    if "\n" in req.subject or "\r" in req.subject:
        raise ConfigError("the subject must be one line")
    if not req.body.strip():
        raise ConfigError("the body is empty")

    files = profiles.available(root)
    to = recipients.resolve(root, req.to)
    if not to:
        raise ConfigError("no recipient")
    first = to[0]
    profile, why = profiles.select(files, first, req.profile, str(cfg.get("default_profile") or ""))
    d.profile_id = str(profile.get("id"))
    d.decisions.append(f"profile {d.profile_id}: {why}" + (" (first recipient decides)" if len(to) > 1 else ""))
    d.style_skill = str(profile.get("style_skill") or cfg.get("style_skill") or "")

    d.to = to
    d.cc = recipients.resolve(root, list(profile.get("cc") or []) + req.cc)
    d.bcc = recipients.resolve(root, list(profile.get("bcc") or []) + req.bcc)

    # language and form of address: flag > recipient > profile > config
    for value, source in ((req.lang, "--lang"), (first.language, f"recipient {first.label()}"),
                          (profile.get("language"), f"profile {d.profile_id}"),
                          (cfg.get("language"), "bridge-config.yaml mail.language")):
        if value:
            d.language = str(value)
            d.decisions.append(f"language {d.language}: {source}")
            break
    for value, source in ((req.address_form, "flag"), (first.address_form, f"recipient {first.label()}"),
                          (profile.get("address_form"), f"profile {d.profile_id}")):
        if value:
            d.address_form = str(value)
            d.decisions.append(f"address {d.address_form}: {source}")
            break
    d.address_form = d.address_form or "formal"

    # a profile may carry per-language wording, picked like a footer variant
    variant = (profile.get("variants") or {}).get(d.language)
    if variant is None and "-" in d.language:
        variant = (profile.get("variants") or {}).get(d.language.split("-")[0])
    if variant:
        profile = profiles._deep(profile, variant)
        d.decisions.append(f"profile {d.profile_id}: '{d.language}' variant applied")
    informal = d.address_form == "informal"

    # footer: flag > profile; a footer resolves its language variant itself
    fid = req.footer if req.footer is not None else profile.get("footer")
    fcfg: dict = {}
    if fid:
        fcfg = footer_mod.load(root, str(fid), d.language, str(cfg.get("language") or "en"),
                               req.footer_style or str(profile.get("footer_style") or ""))
        d.footer_id = str(fid)
        d.decisions.append(f"footer {fid} ({fcfg['style']}, {fcfg['_language']}): "
                           + ("--footer" if req.footer else f"profile {d.profile_id}"))
        if fcfg["_language"] != d.language:
            d.warnings.append(f"footer {fid} has no '{d.language}' variant, it renders in {fcfg['_language']}")
    d.footer_cfg = fcfg
    signature = ""
    if fid is None and profile.get("persona_ref"):
        signature = footer_mod.persona_signature(root, str(profile["persona_ref"]))
        if signature:
            d.decisions.append(f"signature: persona {profile['persona_ref']} (no footer set)")

    d.sender = str(profile.get("sender") or footer_mod.sender_of(fcfg) or "")

    sender_name = str(fcfg.get("name") or "")
    group = first.mandant_name if len(to) > 1 and len({r.mandant_id for r in to}) == 1 else ""
    single = len(to) == 1
    ctx = {
        "first_name": first.first_name if single else "",
        "last_name": first.last_name if single else "",
        "name": (req.recipient_name or first.name) if single else "",
        "group": group,
        "sender_name": sender_name,
        "sender_first_name": sender_name.split()[0] if sender_name else "",
        "subject": req.subject,
        "date": today.isoformat(),
    }
    if req.recipient_name and single:
        ctx["first_name"] = req.recipient_name.split()[0]

    template = "{subject}" if req.reply else str(profile.get("subject") or "{subject}")
    d.subject = _fill(template, ctx).strip()

    # words: snippets, greeting, sign-off
    snippets = profile.get("snippets") or {}

    def snip(m):
        key = m.group(1)
        if key not in snippets:
            d.errors.append(f"snippet '{key}' is not defined in profile {d.profile_id}")
            return m.group(0)
        return str(snippets[key])
    body = SNIPPET.sub(snip, req.body.strip("\n"))
    body = _resolve_link_aliases(body, {**(cfg.get("link_aliases") or {}),
                                        **(profile.get("link_aliases") or {})}, d)

    if req.greeting:
        greet = profile.get("greeting") or {}
        words = [str(w).lower() for w in (profile.get("greeting_words") or [])]
        opening = body.lstrip().split("\n", 1)[0].lower()
        # A whole word: "Historically, ..." is not greeted by "Hi".
        already = any(re.match(rf"{re.escape(w)}(?![\w])", opening) for w in words)
        named = ctx["first_name"] or ctx["name"]
        line = greet.get(d.address_form) if named else greet.get("fallback")
        if line and not already:
            body = _fill(str(line), ctx).strip() + "\n\n" + body
        close = (profile.get("sign_off") or {}).get(d.address_form)
        if close:
            rendered = _fill(str(close), ctx).strip()
            if not _signed_off(body, rendered, sender_name):
                body = body.rstrip() + "\n\n" + rendered
    d.markdown = body

    # dress
    theme_name = req.theme or str(profile.get("theme") or cfg.get("theme") or "design")
    tokens = {**(cfg.get("tokens") or {}), **(profile.get("tokens") or {})}
    # the persona that signs picks the design (identity/designs/): the footer's when a
    # footer is set, else the profile's persona_ref, which then supplies the signature
    persona = str(fcfg.get("_persona") or "") if fcfg else str(profile.get("persona_ref") or "")
    t = theme_mod.load(theme_name, root, tokens, persona)
    d.theme_name, d.theme = theme_name, t
    d.decisions += [f"theme {theme_name}: {n}" for n in t.notes]
    labels = {**(cfg.get("labels") or {}), **(profile.get("labels") or {})}
    aliases = {**(cfg.get("badge_aliases") or {}), **(profile.get("badge_aliases") or {})}
    if profile.get("heading_styles") is False:
        # `heading_styles: false` switches the configured words off for this
        # occasion; an empty map could not, it merges over mail.heading_styles.
        styles = {}
        d.decisions.append(f"heading styles off: profile {d.profile_id}")
    else:
        styles = {**(cfg.get("heading_styles") or {}), **(profile.get("heading_styles") or {})}
    content = Renderer(t, labels, aliases, styles).render(body)
    recipient_for_links = ctx["first_name"]
    if fcfg:
        content += footer_mod.render_html(fcfg, t, recipient_for_links, informal, today)
    elif signature:
        content += footer_mod.render_signature_html(signature, t)
    masthead = False if req.reply else profile.get("masthead", t.get("card"))
    eyebrow = str(profile.get("eyebrow") or cfg.get("eyebrow") or "")
    preheader = _fill(req.preheader or str(profile.get("preheader") or ""), ctx)
    d.content = content
    d.shell = {"title": d.subject if masthead else "", "eyebrow": eyebrow if masthead else "",
               "preheader": preheader, "lang": d.language or "en"}
    d.html = document(content, t, **d.shell)
    d.html_static = document(content, t, dark_css=False, **d.shell)
    text = to_text(body, labels, aliases)
    if fcfg:
        text += "\n-- \n" + footer_mod.render_text(fcfg, recipient_for_links, informal, today) + "\n"
    elif signature:
        text += "\n-- \n" + signature + "\n"
    d.text = text

    # envelope
    seen = set()
    for raw in list(profile.get("attachments") or []) + req.attachments:
        p = _expand_path(str(raw), root)
        if str(p) not in seen:
            seen.add(str(p))
            d.attachments.append(p)
    d.client = req.client or str(profile.get("client") or cfg.get("client") or default_client())
    d.priority = req.priority or str(profile.get("priority") or "normal")

    from . import validate  # noqa: PLC0415
    used = [("profile", d.profile_id, files.get(d.profile_id))]
    if d.footer_id:
        used.append(("footer", d.footer_id, footer_mod.available(root).get(d.footer_id)))
    for kind, name, data in used:
        if data:
            d.errors += [f"{kind} {name}: {e}" for e in validate.schema_errors(root, kind, data)]
    d.errors += [f"footer {d.footer_id}: link '{u}' is not http(s), mailto or tel"
                 for u in footer_mod.unsafe_urls(fcfg)] if fcfg else []

    lint.run(d, profile, cfg)
    return d
