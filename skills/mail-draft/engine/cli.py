"""mail-draft: Markdown in, a draft in a mail client out. Never a send.

    compose    build the draft and hand it to the mail client (default: Apple Mail on macOS);
               with --reply-to, a reply in Apple Mail that keeps the quote
    preview    build it, write a light/dark preview page, open nothing in a mail client
    check      build it and report the preflight only
    explain    which profile, footer, language and sender a recipient gets, and why
    signature  render one footer on its own (preview, or paste into a client's signature)
    list       footers, profiles, and which mandants point where
    validate   check every footer, profile and the references between them
    verify     count drafts with a subject in a client's Drafts folder
    gallery    one sample mail per theme and profile on a local page, nothing sent

Arguments are named. Positional order was the trap of the script this replaces:
a missing priority made the attachment path read as the priority, and the mail
went out without its attachment while the summary looked complete.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

from . import footer as footer_mod
from . import profiles, validate
from .config import ConfigError, load
from .draft import Draft, Request, build
from .markdown import document
from .theme import load as load_theme


def _body(args) -> str:
    if args.body is not None:
        return args.body
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise ConfigError("no body: pass --body, --body-file, or pipe the text in")


def _request(args) -> Request:
    footer = None
    if args.no_footer:
        footer = ""
    elif args.footer:
        footer = args.footer
    return Request(
        to=args.to, subject=args.subject, body=_body(args), cc=args.cc or [], bcc=args.bcc or [],
        attachments=[str(Path(a).expanduser().resolve()) for a in args.attach or []], profile=args.profile or "", footer=footer,
        footer_style=args.footer_style or "", theme=args.theme or "", lang=args.lang or "",
        address_form="informal" if args.informal else "formal" if args.formal else "",
        client=getattr(args, "client", "") or "", priority=getattr(args, "priority", "") or "",
        preheader=args.preheader or "", greeting=not args.no_greeting,
        recipient_name=args.recipient_name or "", reply=bool(getattr(args, "reply_to", None)),
    )


def _slug(text: str) -> str:
    s = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return s[:48] or "draft"


def write_bundle(d: Draft, drafts_dir: Path) -> Path:
    """Source, HTML, text, .eml and a preview page, next to each other."""
    from . import mime
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    out = drafts_dir / f"{stamp}-{_slug(d.subject)}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "source.md").write_text(d.markdown + "\n", encoding="utf-8")
    (out / "mail.html").write_text(d.html, encoding="utf-8")
    (out / "mail.txt").write_text(d.text, encoding="utf-8")
    (out / "mail.eml").write_bytes(bytes(mime.build(d)))
    (out / "preview.html").write_text(preview_page(d), encoding="utf-8")
    (out / "report.txt").write_text(report(d) + "\n", encoding="utf-8")
    return out


def preview_page(d: Draft) -> str:
    """Light and dark side by side, the way two different readers will see it."""
    import html as h
    dark = document(d.content, d.theme, force_dark=True, **d.shell) if d.theme else d.html
    meta = h.escape(f"To: {', '.join(r.label() for r in d.to)}   Subject: {d.subject}")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" /><title>{h.escape(d.subject)}</title>
<style>:root{{color-scheme:light dark}}body{{margin:0;font:14px system-ui,sans-serif;background:#888;}}
header{{padding:10px 16px;background:#222;color:#eee}}main{{display:flex;flex-wrap:wrap;gap:12px;padding:12px}}
section{{flex:1 1 420px;min-width:0}}h2{{font-size:13px;color:#fff;margin:0 0 6px}}
iframe{{width:100%;height:85vh;border:0;border-radius:8px;background:#fff}}</style></head><body>
<header>{meta}</header><main>
<section><h2>Light</h2><iframe srcdoc="{h.escape(d.html, quote=True)}"></iframe></section>
<section><h2>Dark</h2><iframe srcdoc="{h.escape(dark, quote=True)}"></iframe></section>
</main></body></html>"""


def report(d: Draft) -> str:
    lines = [f"To:       {', '.join(r.label() for r in d.to)}"]
    if d.cc:
        lines.append(f"Cc:       {', '.join(r.label() for r in d.cc)}")
    if d.bcc:
        lines.append(f"Bcc:      {', '.join(r.label() for r in d.bcc)}")
    lines.append(f"Subject:  {d.subject}")
    if d.attachments:
        lines.append("Attach:   " + ", ".join(p.name for p in d.attachments))
    lines += ["", d.explain()]
    if d.errors:
        lines += ["", "ERRORS (no draft created):"] + [f"  x {e}" for e in d.errors]
    if d.warnings:
        lines += ["", "warnings:"] + [f"  ! {w}" for w in d.warnings]
    return "\n".join(lines)


def _open(path: Path) -> None:
    opener = {"darwin": ["open"], "win32": ["cmd", "/c", "start", ""]}.get(sys.platform, ["xdg-open"])
    subprocess.run([*opener, str(path)], check=False)


def _add_message_args(p: argparse.ArgumentParser, reply: bool = False) -> None:
    # compose checks --to and --subject itself: a reply takes both from the original.
    p.add_argument("--to", action="append", required=not reply,
                   help="address, mandant:<id>[#<group>], <mandant>/<person> or a person id (repeatable, comma ok)")
    p.add_argument("--cc", action="append")
    p.add_argument("--bcc", action="append")
    p.add_argument("--subject", required=not reply)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--body", help="Markdown text")
    g.add_argument("--body-file", help="a Markdown file (otherwise stdin)")
    p.add_argument("--attach", action="append", help="file to attach (repeatable)")
    p.add_argument("--profile", help="workflow/mail-profiles/<id>")
    f = p.add_mutually_exclusive_group()
    f.add_argument("--footer", help="identity/mail-footers/<id>, overrides the profile")
    f.add_argument("--no-footer", action="store_true")
    p.add_argument("--footer-style", choices=["card", "compact", "minimal", "text"])
    p.add_argument("--theme", choices=["design", "minimal", "plain"])
    p.add_argument("--lang", help="language, overrides the recipient's")
    a = p.add_mutually_exclusive_group()
    a.add_argument("--informal", action="store_true")
    a.add_argument("--formal", action="store_true")
    p.add_argument("--preheader")
    p.add_argument("--no-greeting", action="store_true", help="no greeting and no sign-off from the profile")
    p.add_argument("--recipient-name", help="first name for greeting and links when the address is unknown")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mail-draft", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compose", help="build the draft and hand it to the mail client")
    _add_message_args(c, reply=True)
    c.add_argument("--client", choices=["apple-mail", "outlook", "eml", "none"])
    c.add_argument("--reply-to", metavar="MESSAGE-ID|SUBJECT",
                   help="answer this message in Apple Mail (Message-ID, or words of its subject)")
    c.add_argument("--reply-all", action="store_true", help="with --reply-to: answer every recipient")
    c.add_argument("--priority", choices=["low", "normal", "high"])
    c.add_argument("--hide", action="store_true", help="save the draft without opening its window")
    c.add_argument("--force", action="store_true", help="create the draft despite preflight errors")

    pv = sub.add_parser("preview", help="write a light/dark preview page")
    _add_message_args(pv)
    pv.add_argument("--open", action="store_true")

    ck = sub.add_parser("check", help="preflight only")
    _add_message_args(ck)

    ex = sub.add_parser("explain", help="which profile, footer and language a recipient gets")
    ex.add_argument("--to", action="append", required=True)
    ex.add_argument("--profile")

    sg = sub.add_parser("signature", help="render one footer on its own")
    sg.add_argument("footer")
    sg.add_argument("--lang", default="")
    sg.add_argument("--style", choices=["card", "compact", "minimal", "text"])
    sg.add_argument("--theme", default="", choices=["", "design", "minimal", "plain"])
    sg.add_argument("--recipient-name", default="")
    sg.add_argument("--informal", action="store_true")
    sg.add_argument("--out", help="write signature.html here (a directory)")

    sub.add_parser("list", help="footers, profiles and mandant mappings")
    sub.add_parser("validate", help="check every footer and profile")

    vf = sub.add_parser("verify", help="count drafts with this subject in the Drafts folder")
    vf.add_argument("--client", required=True, choices=["apple-mail", "outlook"])
    vf.add_argument("--subject", required=True)

    gl = sub.add_parser("gallery", help="render a sample mail per theme and profile on one local page")
    gl.add_argument("--out", help="directory for the page (default: <mail.drafts_dir>/gallery)")
    gl.add_argument("--body-file", help="your own sample text (Markdown) instead of the built-in one")
    gl.add_argument("--open", action="store_true", help="open the page in the browser")

    args = ap.parse_args(argv)
    try:
        cfg = load()
        return COMMANDS[args.cmd](args, cfg)
    except ConfigError as err:
        print(f"mail-draft: {err}", file=sys.stderr)
        return 2


# Why a reply is Apple Mail only. Each client is named, never silently skipped.
REPLY_UNSUPPORTED = {
    "outlook": "Outlook for Mac gives scripts no reliable way to answer a message and keep its quote "
               "and attachments (it cannot even keep a new draft without an open window)",
    "eml": "an .eml file cannot carry the quote of a message that lives in the mail client",
    "none": "client none hands nothing to a mail client",
}


def _refuse_reply(client: str) -> int:
    why = REPLY_UNSUPPORTED.get(client, "only Apple Mail can answer a message here")
    print(f"mail-draft: a reply draft is not supported with client {client}: {why}. "
          f"Use --client apple-mail, or answer in {client} by hand. Nothing was created.", file=sys.stderr)
    return 2


def _prepare_reply(args, cfg):
    """Find the original BEFORE anything is built: to, subject and the thread come from it."""
    if args.client and args.client != "apple-mail":
        return _refuse_reply(args.client)
    from .clients import apple_mail
    original = apple_mail.find_original(args.reply_to)
    print(f"replying to: {original.describe()}")
    if not args.to:
        args.to = [original.address]
    if not args.subject:
        args.subject = apple_mail.reply_subject(original.subject)
    return original


def cmd_compose(args, cfg) -> int:
    original = None
    if args.reply_to:
        original = _prepare_reply(args, cfg)
        if isinstance(original, int):
            return original
    elif not args.to or not args.subject:
        raise ConfigError("compose needs --to and --subject (or --reply-to <message-id|subject> for a reply)")
    d = build(_request(args), cfg)
    if original is not None and d.client != "apple-mail":
        return _refuse_reply(d.client)
    bundle = write_bundle(d, cfg.drafts_dir)
    print(report(d))
    print(f"\nbundle:   {bundle}")
    if d.errors and not args.force:
        print("\nNo draft created. Fix the errors above, or pass --force to create it anyway.")
        return 1
    show = not args.hide
    if d.client == "none":
        print("\nclient none: nothing handed to a mail client, the bundle is the draft.")
        return 0
    if d.client == "eml":
        eml = bundle / "mail.eml"
        if show:
            _open(eml)
        print(f"\ndraft: {eml} (opens as a draft in Outlook and Thunderbird; Apple Mail shows it read-only)")
        return 0
    if d.client == "apple-mail":
        from .clients import apple_mail as client
    elif d.client == "outlook":
        from .clients import outlook as client
    else:
        raise ConfigError(f"unknown client '{d.client}'")
    if original is not None:
        result = client.reply_handoff(d, bundle / ".handoff", original, show=show, reply_all=args.reply_all)
    else:
        result = client.handoff(d, bundle / ".handoff", show=show)
    print(f"\n{d.client}: {result.detail}")
    if not result.ok:
        print("draft: FAILED" + (", NOT in the Drafts folder" if result.verified is False else ""))
    elif result.verified:
        print("draft: " + ("reply " if original is not None else "") + "in the Drafts folder")
    elif result.verified is False:
        print("draft: open as a window, NOT yet in the Drafts folder (save it there)")
    else:
        print("draft: created, not verified")
    print("Nothing was sent. Review the draft and press Send yourself.")
    return 0 if result.ok else 1


def cmd_preview(args, cfg) -> int:
    d = build(_request(args), cfg)
    bundle = write_bundle(d, cfg.drafts_dir)
    print(report(d))
    print(f"\npreview:  {bundle / 'preview.html'}")
    print("\n--- text part ---\n" + d.text)
    if args.open:
        _open(bundle / "preview.html")
    return 1 if d.errors else 0


def cmd_check(args, cfg) -> int:
    d = build(_request(args), cfg)
    print(report(d))
    return 1 if d.errors else 0


def cmd_explain(args, cfg) -> int:
    req = Request(to=args.to, subject="(subject)", body="(body)", profile=args.profile or "")
    d = build(req, cfg)
    print(d.explain())
    return 0


def cmd_signature(args, cfg) -> int:
    fcfg = footer_mod.load(cfg.root, args.footer, args.lang, str(cfg.get("language") or "en"), args.style or "")
    t = load_theme(args.theme or str(cfg.get("theme") or "design"), cfg.root, cfg.get("tokens") or {})
    html_fragment = footer_mod.render_html(fcfg, t, args.recipient_name, args.informal)
    print(footer_mod.render_text(fcfg, args.recipient_name, args.informal))
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "signature.html").write_text(document(html_fragment, t, lang=fcfg["_language"]), encoding="utf-8")
        (out / "signature-fragment.html").write_text(html_fragment, encoding="utf-8")
        print(f"\nwritten: {out / 'signature.html'} (open it, select all, paste into the client's signature)")
    return 0


def cmd_list(args, cfg) -> int:
    root = cfg.root
    footers = footer_mod.available(root)
    profs = profiles.available(root)
    print("footers (identity/mail-footers/):")
    for fid, data in footers.items():
        langs = [str(data.get("language") or cfg.get("language"))] + sorted((data.get("variants") or {}).keys())
        print(f"  {fid:22s} {str(data.get('style') or 'card'):8s} {'/'.join(langs):10s} {data.get('title', '')}")
    if not footers:
        print("  (none; copy identity/mail-footers/_template.yaml)")
    print("\nprofiles (workflow/mail-profiles/):")
    for pid in profs:
        data = profiles.resolve(profs, pid)
        mark = " *default" if data.get("default") else ""
        rule = data.get("applies_to") or {}
        applies = ", ".join(f"{k}={','.join(map(str, v))}" for k, v in rule.items() if v)
        footer = data.get("footer")
        shown = "(none)" if footer is False else footer or "-"
        print(f"  {pid:22s} footer={shown!s:16s} theme={data.get('theme', 'design')!s:8s} {applies}{mark}")
    if not profs:
        print("  (none; copy workflow/mail-profiles/_template.yaml)")
    mdir = root / "identity" / "mandants"
    mapped = []
    if mdir.is_dir():
        from .config import load_yaml
        for path in sorted(mdir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            m = load_yaml(path)
            if m.get("mail_profile"):
                mapped.append(f"  {path.stem:22s} -> {m['mail_profile']}")
            for p in m.get("persons") or []:
                if p.get("mail_profile"):
                    mapped.append(f"  {path.stem + '/' + str(p.get('id')):22s} -> {p['mail_profile']}")
    if mapped:
        print("\nmandants with their own profile:")
        print("\n".join(mapped))
    return 0


def cmd_validate(args, cfg) -> int:
    problems = validate.run(cfg.root)
    for p in problems:
        print(f"  x {p}")
    n_f = len(footer_mod.available(cfg.root))
    n_p = len(profiles.available(cfg.root))
    print(f"mail-draft validate: {n_f} footer(s), {n_p} profile(s), {len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_verify(args, cfg) -> int:
    if args.client == "apple-mail":
        from .clients.apple_mail import verify
    else:
        from .clients.outlook import verify
    count = verify(args.subject)
    print("not verifiable" if count is None else f"{count} draft(s) with that subject")
    return 0 if count else 1


def cmd_gallery(args, cfg) -> int:
    from . import gallery
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
    index, problems = gallery.run(cfg, Path(args.out).expanduser() if args.out else None, body)
    for p in problems:
        print(f"  ! {p}")
    print(f"gallery: {index}")
    print("Nothing was sent and no mail client was touched.")
    if args.open:
        _open(index)
    return 0


COMMANDS = {
    "compose": cmd_compose, "preview": cmd_preview, "check": cmd_check, "explain": cmd_explain,
    "signature": cmd_signature, "list": cmd_list, "validate": cmd_validate, "verify": cmd_verify,
    "gallery": cmd_gallery,
}

if __name__ == "__main__":
    sys.exit(main())
