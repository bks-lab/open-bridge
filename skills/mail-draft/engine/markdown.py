"""Markdown to mail HTML, and Markdown to the plain-text part of the same mail.

Mail HTML is a dialect of its own: tables for layout, every style inline, hex
colours only, no webfonts, Word as the renderer in desktop Outlook. This module
writes that dialect from a small Markdown subset and nothing else:

    # / ## / ###          headings (one title-sized h1 is rarely needed, the
                          subject already stands at the top of the card)
    paragraphs            consecutive lines stay one paragraph, joined by <br>
    **bold** *italic* `code`
    [text](url)           links, underlined: colour alone is not a link signal
    https://bare.url      linked as written, so the visible text IS the target
    - item / 1. item      lists
    > quote               callout
    > [!NOTE] ...         GitHub alert syntax: NOTE, TIP, IMPORTANT, WARNING, CAUTION
    | a | b |             tables, header row, zebra rows
    ```code```            fenced code
    ---                   hairline
    [[Label]](url)        a button that also renders in desktop Outlook (VML)
    [done] [blocked] ...  status badges, labels configurable
    ![alt](attachment:f)  a visible pointer to an attached file

Links accept http, https, mailto and tel. Anything else renders as text, so a
`javascript:` or `file:` link cannot reach a recipient through this module.
"""

from __future__ import annotations

import re
from html import escape

SAFE_SCHEME = re.compile(r"^(https?:|mailto:|tel:)", re.I)

# badge -> (theme role, glyph, default label). Labels are English by default
# and replaced per instance through `mail.labels`.
BADGES = {
    "done":     ("success", "&#10003;", "DONE"),
    "progress": ("info",    "&#9679;",  "IN PROGRESS"),
    "blocked":  ("warning", "&#9888;",  "BLOCKED"),
    "waiting":  ("warning", "&#9711;",  "WAITING"),
    "todo":     ("text_muted", "&#9711;", "TO DO"),
    "new":      ("info",    "&#9733;",  "NEW"),
    "info":     ("text_muted", "&#8505;", "INFO"),
    "high":     ("danger",  "!",        "HIGH PRIORITY"),
    "urgent":   ("danger",  "!!",       "URGENT"),
}

ALERTS = {
    "NOTE":      ("info",    "Note"),
    "TIP":       ("success", "Tip"),
    "IMPORTANT": ("primary", "Important"),
    "WARNING":   ("warning", "Warning"),
    "CAUTION":   ("danger",  "Caution"),
}


class Renderer:
    def __init__(self, theme: dict, labels: dict | None = None, aliases: dict | None = None,
                 heading_styles: dict | None = None):
        self.t = theme
        # `## <words>` that dress a section heading: {callout: [...], warning: [...]}.
        # A whole word, any case; warning wins when both match.
        self.heading_styles = {
            kind: [str(w) for w in (heading_styles or {}).get(kind) or [] if str(w).strip()]
            for kind in ("callout", "warning")}
        self.labels = {k.lower(): str(v) for k, v in (labels or {}).items()}
        # An alias that points at no built-in badge is dropped, not a crash.
        self.aliases = {str(k).lower(): str(v).lower() for k, v in (aliases or {}).items()
                        if str(v).lower() in BADGES}

    # --------------------------------------------------------------- inline --

    def badge(self, key: str) -> str:
        key = self.aliases.get(key.lower(), key.lower())
        role, glyph, label = BADGES[key]
        label = escape(self.labels.get(key, label))
        t = self.t
        color = t.get(role) or t["primary"]
        return (
            '<!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="display:inline-table;vertical-align:middle;"><tr>'
            f'<td style="background-color:{t["muted_bg"]};border-left:3px solid {color};padding:3px 10px;'
            f'font-size:12px;font-weight:600;font-family:Arial,sans-serif;color:{t["text"]};white-space:nowrap;">'
            f'{label}</td></tr></table><![endif]-->'
            '<!--[if !mso]><!-->'
            f'<span class="e-badge" style="display:inline-block;background-color:{t["muted_bg"]};'
            f'border:1px solid {t["border"]};border-left:3px solid {color};padding:3px 10px;font-size:12px;'
            f'font-weight:600;letter-spacing:0.06em;font-family:{t["font_body"]};color:{t["text"]};'
            f'white-space:nowrap;border-radius:4px;vertical-align:middle;">'
            f'<span style="color:{color};">{glyph}</span> {label}</span><!--<![endif]-->')

    def link(self, text: str, href: str) -> str:
        """`text` is already escaped HTML, `href` is escaped too."""
        if not SAFE_SCHEME.match(href.replace("&amp;", "&")):
            return text
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        return (f'<a class="e-link" href="{href}" style="color:{self.t["link"]};'
                f'text-decoration:underline;">{text}</a>')

    def inline(self, text: str) -> str:
        t = self.t
        held: list[str] = []

        def hold(fragment: str) -> str:
            held.append(fragment)
            return f"\x00{len(held) - 1}\x00"

        # The placeholder marker must not be forgeable from the text itself.
        text = escape(text.replace("\x00", ""), quote=True)

        text = re.sub(
            r"!\[([^\]]*)\]\(attachment:([^)]+)\)",
            lambda m: hold(
                f'<span class="e-callout" style="display:inline-block;background-color:'
                f'{t["accent_subtle"] or t["muted_bg"]};border:1px solid {t["accent_line"] or t["border"]};'
                f'padding:6px 12px;font-size:13px;font-family:{t["font_body"]};color:{t["text"]};'
                f'border-radius:6px;">&#128206; <strong>{m.group(1)}</strong> '
                f'<span class="e-muted" style="color:{t["text_muted"]};">({m.group(2)})</span></span>'),
            text)

        text = re.sub(
            r"!\[([^\]]*)\]\(([^)\s]+)\)",
            lambda m: hold(
                f'<img src="{m.group(2)}" alt="{m.group(1)}" style="max-width:100%;height:auto;border:0;" />'
                if SAFE_SCHEME.match(m.group(2)) and m.group(2).lower().startswith("http") else m.group(1)),
            text)

        text = re.sub(
            r"`([^`]+)`",
            lambda m: hold(
                f'<span class="e-code" style="font-family:{t["font_mono"]};font-size:13px;'
                f'background-color:{t["muted_bg"]};border:1px solid {t["border"]};border-radius:4px;'
                f'padding:1px 5px;color:{t["text"]};">{m.group(1)}</span>'),
            text)

        text = re.sub(r"\[\[([^\]]+)\]\]\(([^)\s]+)\)",
                      lambda m: hold(button_html(m.group(1), m.group(2), t, escaped=True)), text)

        text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                      lambda m: hold(self.link(m.group(1), m.group(2))), text)

        text = re.sub(r"(?<![\w/\"'=])(https?://[^\s<>\x00]+[^\s<>\x00.,;:!?)\]])",
                      lambda m: hold(self.link(m.group(1), m.group(1))), text)

        keys = "|".join(re.escape(k) for k in sorted(set(BADGES) | set(self.aliases), key=len, reverse=True))
        text = re.sub(rf"\[({keys})\]", lambda m: hold(self.badge(m.group(1))), text, flags=re.I)

        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<em>\1</em>", text)
        text = re.sub(r"(?<![\w_])_([^_\s][^_]*?)_(?![\w_])", r"<em>\1</em>", text)

        while "\x00" in text:
            text = re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], text)
        return text

    # ---------------------------------------------------------------- blocks --

    def p_style(self) -> str:
        t = self.t
        return (f'font-family:{t["font_body"]};font-size:{t["base_size"]};'
                f'line-height:{t["base_line"]};color:{t["text"]};')

    def heading(self, level: int, raw: str) -> str:
        t = self.t
        content = self.inline(raw)
        if t.get("plain_headings"):
            size = {1: "20px", 2: "17px", 3: "15px"}[level]
            return (f'<h{level} style="margin:22px 0 10px 0;font-family:{t["font_body"]};font-size:{size};'
                    f'font-weight:700;color:{t["text"]};">{content}</h{level}>')
        if level == 1:
            fam = t["font_display"] if t.get("display_headings") else t["font_body"]
            weight = "500" if t.get("display_headings") else "700"
            return (f'<h1 class="e-h" style="margin:34px 0 14px 0;font-family:{fam};font-size:28px;'
                    f'font-weight:{weight};line-height:1.2;color:{t["primary"]};padding-bottom:12px;'
                    f'border-bottom:1px solid {t["border"]};">{content}</h1>')
        if level == 2:
            base = (f'margin:30px 0 10px 0;font-family:{t["font_body"]};font-size:20px;'
                    f'font-weight:600;line-height:1.35;color:{t["primary"]};')
            kind = self.heading_kind(raw)
            if kind == "warning":
                return (f'<h2 class="e-warn" style="{base}background-color:{t["muted_bg"]};'
                        f'border-left:3px solid {t.get("warning") or t["primary"]};'
                        f'border-radius:0 10px 10px 0;padding:14px 18px;">{content}</h2>')
            if kind == "callout" and t.get("accent_subtle"):
                return (f'<h2 class="e-callout" style="{base}background-color:{t["accent_subtle"]};'
                        f'border:1px solid {t["accent_line"]};border-radius:10px;padding:14px 18px;">'
                        f'{content}</h2>')
            return f'<h2 class="e-h" style="{base}">{content}</h2>'
        return (f'<h3 class="e-h" style="margin:22px 0 8px 0;font-family:{t["font_body"]};font-size:17px;'
                f'font-weight:600;line-height:1.4;color:{t["text"]};">{content}</h3>')

    def heading_kind(self, raw: str) -> str:
        for kind in ("warning", "callout"):
            for word in self.heading_styles.get(kind, []):
                if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", raw, re.I):
                    return kind
        return ""

    def callout(self, html_body: str, kind: str | None = None) -> str:
        t = self.t
        if kind:
            role, title = ALERTS[kind]
            color = t.get(role) or t["primary"]
            head = (f'<div style="font-family:{t["font_body"]};font-size:12px;font-weight:700;letter-spacing:.08em;'
                    f'text-transform:uppercase;color:{color};margin-bottom:4px;">'
                    f'{escape(self.labels.get(kind.lower(), title))}</div>')
            return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                    f'style="margin:18px 0;"><tr><td class="e-warn" style="background-color:{t["muted_bg"]};'
                    f'border-left:3px solid {color};padding:12px 16px;{self.p_style()}">{head}{html_body}'
                    f'</td></tr></table>')
        if not t.get("accent_subtle"):
            return (f'<p style="margin:16px 0;padding-left:12px;border-left:3px solid {t["border"]};'
                    f'{self.p_style()}">{html_body}</p>')
        return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                f'style="margin:18px 0;"><tr><td class="e-callout" style="background-color:{t["accent_subtle"]};'
                f'border:1px solid {t["accent_line"]};border-radius:10px;padding:16px 20px;{self.p_style()}">'
                f'{html_body}</td></tr></table>')

    @staticmethod
    def split_row(row: str) -> list[str]:
        """Cells of a table row; a `|` inside backticks or escaped as `\\|` stays text."""
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|") and not row.endswith("\\|"):
            row = row[:-1]
        cells, buf, in_code, i = [], [], False, 0
        while i < len(row):
            ch = row[i]
            if ch == "\\" and i + 1 < len(row) and row[i + 1] == "|":
                buf.append("|")
                i += 2
                continue
            if ch == "`":
                in_code = not in_code
            if ch == "|" and not in_code:
                cells.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
            i += 1
        cells.append("".join(buf).strip())
        return cells

    def table(self, rows: list[str]) -> str:
        t = self.t
        cells = [self.split_row(r) for r in rows]
        align: list[str] = []
        if len(cells) > 1 and all(re.match(r"^:?-{2,}:?$", c) for c in cells[1] if c):
            for c in cells[1]:
                align.append("center" if c.startswith(":") and c.endswith(":") else
                             "right" if c.endswith(":") else "left")
            cells = [cells[0]] + cells[2:]
        head, body = cells[0], cells[1:]
        border = t["border"]
        out = [f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
               f'style="border-collapse:collapse;margin:18px 0;min-width:280px;max-width:100%;'
               f'border:1px solid {border};">']
        out.append("<tr>")
        for i, h in enumerate(head):
            a = align[i] if i < len(align) else "left"
            out.append(f'<th class="e-th" style="background-color:{t["header_bg"]};padding:10px 14px;'
                       f'text-align:{a};font-family:{t["font_body"]};font-weight:600;font-size:12px;'
                       f'letter-spacing:0.08em;text-transform:uppercase;color:{t["header_text"]};'
                       f'border:1px solid {border};">{self.inline(h)}</th>')
        out.append("</tr>")
        for n, row in enumerate(body):
            zebra = t.get("zebra") and n % 2 == 1
            bg = t["muted_bg"] if zebra else t["card_bg"]
            cls = "e-zebra" if zebra else "e-td"
            out.append("<tr>")
            if len(row) > len(head):
                # More cells than headings: keep the content in the last column.
                row = row[:len(head) - 1] + [" | ".join(row[len(head) - 1:])]
            for i in range(len(head)):
                cell = row[i] if i < len(row) else ""
                a = align[i] if i < len(align) else "left"
                out.append(f'<td class="{cls}" style="background-color:{bg};padding:10px 14px;text-align:{a};'
                           f'border:1px solid {border};font-family:{t["font_body"]};font-size:{t["base_size"]};'
                           f'line-height:1.5;color:{t["text"]};vertical-align:top;">'
                           f'{self.inline(cell) if cell else "&nbsp;"}</td>')
            out.append("</tr>")
        out.append("</table>")
        return "".join(out)

    def code_block(self, lines: list[str]) -> str:
        t = self.t
        body = "<br />".join(escape(x).replace("  ", "&nbsp; ") or "&nbsp;" for x in lines)
        return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                f'style="margin:16px 0;"><tr><td class="e-code" style="background-color:{t["muted_bg"]};'
                f'border:1px solid {t["border"]};border-radius:6px;padding:12px 14px;font-family:{t["font_mono"]};'
                f'font-size:13px;line-height:1.5;color:{t["text"]};">{body}</td></tr></table>')

    def render(self, md: str) -> str:
        lines = md.replace("\x00", "").replace("\r\n", "\n").split("\n")
        parts: list[str] = []
        para: list[str] = []
        i = 0

        def flush_para():
            if para:
                parts.append(f'<p class="e-p" style="margin:0 0 14px 0;{self.p_style()}">'
                             + "<br />".join(self.inline(x) for x in para) + "</p>")
                para.clear()

        while i < len(lines):
            raw = lines[i]
            line = raw.strip()

            if line.startswith("```"):
                flush_para()
                block = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    block.append(lines[i].rstrip())
                    i += 1
                parts.append(self.code_block(block))
                i += 1
                continue
            if not line:
                flush_para()
                i += 1
                continue
            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):
                flush_para()
                parts.append(f'<hr class="e-rule" style="border:none;border-top:1px solid {self.t["border"]};'
                             f'margin:28px 0;" />')
                i += 1
                continue
            if line.startswith("|"):
                flush_para()
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append(lines[i])
                    i += 1
                parts.append(self.table(rows))
                continue
            if line.startswith(">"):
                flush_para()
                quote = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    quote.append(re.sub(r"^>\s?", "", lines[i].strip()))
                    i += 1
                kind = None
                m = re.match(r"^\[!(\w+)\]\s*(.*)$", quote[0]) if quote else None
                if m and m.group(1).upper() in ALERTS:
                    kind = m.group(1).upper()
                    quote[0] = m.group(2)
                inner = Renderer(self.t, self.labels, self.aliases).render("\n".join(q for q in quote))
                parts.append(self.callout(inner.replace("margin:0 0 14px 0", "margin:0 0 6px 0"), kind))
                continue
            if re.match(r"^\[\[[^\]]+\]\]\([^)\s]+\)$", line):
                flush_para()
                m = re.match(r"^\[\[([^\]]+)\]\]\(([^)\s]+)\)$", line)
                parts.append(f'<div style="margin:18px 0;">{button_html(m.group(1), m.group(2), self.t)}</div>')
                i += 1
                continue
            list_m = re.match(r"^([-*+]|\d+[.)])\s+", line)
            if list_m:
                flush_para()
                ordered = list_m.group(1)[0].isdigit()
                items = []
                while i < len(lines) and re.match(r"^([-*+]|\d+[.)])\s+", lines[i].strip()):
                    items.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", lines[i].strip()))
                    i += 1
                tag = "ol" if ordered else "ul"
                parts.append(f'<{tag} class="e-p" style="margin:0 0 14px 0;padding-left:24px;{self.p_style()}">'
                             + "".join(f'<li style="margin:4px 0;">{self.inline(x)}</li>' for x in items)
                             + f"</{tag}>")
                continue
            head = re.match(r"^(#{1,3})\s+(.+)$", line)
            if head:
                flush_para()
                parts.append(self.heading(len(head.group(1)), head.group(2)))
                i += 1
                continue
            para.append(line)
            i += 1
        flush_para()
        return "\n".join(parts)


def button_html(label: str, url: str, t: dict, escaped: bool = False, small: bool = False) -> str:
    """A bulletproof button: VML for desktop Outlook, a styled link everywhere else."""
    label_html = label if escaped else escape(label)
    href = url if escaped else escape(url, quote=True)
    if not SAFE_SCHEME.match(href.replace("&amp;", "&")):
        return label_html
    from .theme import ensure_contrast  # noqa: PLC0415
    fill = t.get("primary") or "#111827"
    ink = ensure_contrast(t.get("on_primary") or "#ffffff", fill)
    height = 34 if small else 42
    size = 13 if small else 15
    plain_len = len(re.sub(r"&\w+;|&#\d+;", "x", label_html))
    width = max(120, plain_len * (8 if small else 9) + 48)
    return (
        f'<!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" '
        f'xmlns:w="urn:schemas-microsoft-com:office:word" href="{href}" '
        f'style="height:{height}px;v-text-anchor:middle;width:{width}px;" arcsize="14%" stroke="f" '
        f'fillcolor="{fill}"><w:anchorlock/><center style="color:{ink};font-family:Arial,sans-serif;'
        f'font-size:{size}px;font-weight:bold;">{label_html}</center></v:roundrect><![endif]-->'
        f'<!--[if !mso]><!--><a class="e-btn" href="{href}" style="background-color:{fill};border-radius:6px;'
        f'color:{ink};display:inline-block;font-family:{t.get("font_body", "Arial, sans-serif")};'
        f'font-size:{size}px;font-weight:600;line-height:{height}px;text-align:center;text-decoration:none;'
        f'padding:0 22px;-webkit-text-size-adjust:none;mso-hide:all;">{label_html}</a><!--<![endif]-->')


# ---------------------------------------------------------------- the shell --

def document(content: str, t, *, title: str = "", eyebrow: str = "", preheader: str = "",
             lang: str = "en", force_dark: bool = False, dark_css: bool = True) -> str:
    """Wrap rendered content in the mail document: card, dark mode, Outlook fixes.

    `dark_css=False` leaves the dark-mode rules out. A client that converts HTML
    into its own format (Apple Mail does, on `set html content`) renders it once
    under the CURRENT system appearance and keeps the computed colours. With the
    dark rules present on a Mac in dark mode, light text is frozen into the mail
    and a recipient reading in light mode gets pale grey on white.
    """
    dark = getattr(t, "dark", {}) or {}
    d = {
        "bg": dark.get("bg", "#111418"), "card_bg": dark.get("card_bg", "#1a1e24"),
        "muted_bg": dark.get("muted_bg", "#232831"), "text": dark.get("text", "#e6e9ee"),
        "text_muted": dark.get("text_muted", "#a6afbb"), "border": dark.get("border", "#343c48"),
        "link": dark.get("link", "#7fb0ff"), "accent_subtle": dark.get("accent_subtle", "#1c2638"),
        "accent_line": dark.get("accent_line", "#34496b"),
    }
    from .theme import ensure_contrast  # noqa: PLC0415
    d["btn_text"] = ensure_contrast(d["bg"], d["link"])
    dark_rules = f"""
    .e-body {{ background-color: {d['bg']} !important; }}
    .e-card {{ background-color: {d['card_bg']} !important; border-color: {d['border']} !important; }}
    .e-h {{ color: {d['text']} !important; border-color: {d['border']} !important; }}
    .e-p, .e-p li, .e-td {{ color: {d['text']} !important; }}
    .e-td {{ background-color: {d['card_bg']} !important; border-color: {d['border']} !important; }}
    .e-zebra {{ background-color: {d['muted_bg']} !important; border-color: {d['border']} !important; color: {d['text']} !important; }}
    .e-th {{ border-color: {d['border']} !important; }}
    .e-muted {{ color: {d['text_muted']} !important; }}
    .e-rule {{ border-color: {d['border']} !important; }}
    .e-link {{ color: {d['link']} !important; }}
    .e-callout {{ background-color: {d['accent_subtle']} !important; border-color: {d['accent_line']} !important; color: {d['text']} !important; }}
    .e-warn {{ background-color: {d['muted_bg']} !important; color: {d['text']} !important; }}
    .e-badge {{ background-color: {d['muted_bg']} !important; border-color: {d['border']} !important; color: {d['text']} !important; }}
    .e-code {{ background-color: {d['muted_bg']} !important; border-color: {d['border']} !important; color: {d['text']} !important; }}
    .e-btn {{ background-color: {d['link']} !important; color: {d['btn_text']} !important; }}"""
    dark_block = dark_rules if force_dark else f"@media (prefers-color-scheme: dark) {{{dark_rules}\n}}"
    ogsc = f"""[data-ogsc] .e-body {{ background-color: {d['bg']} !important; }}
[data-ogsc] .e-card {{ background-color: {d['card_bg']} !important; }}
[data-ogsc] .e-h, [data-ogsc] .e-p, [data-ogsc] .e-td {{ color: {d['text']} !important; }}
[data-ogsc] .e-muted {{ color: {d['text_muted']} !important; }}
[data-ogsc] .e-link {{ color: {d['link']} !important; }}"""
    scheme = "light dark"
    if not dark_css:
        dark_block, ogsc, scheme = "", "", "light"

    masthead = ""
    if title and t.get("card"):
        brow = ""
        if eyebrow:
            brow = (f'<p class="e-link" style="margin:0 0 8px 0;font-family:{t["font_body"]};font-size:12px;'
                    f'font-weight:600;letter-spacing:0.14em;text-transform:uppercase;color:{t["link"]};">'
                    f'{escape(eyebrow)}</p>')
        fam = t["font_display"] if t.get("display_headings") else t["font_body"]
        masthead = (brow + f'<h1 class="e-h" style="margin:0 0 22px 0;font-family:{fam};font-size:28px;'
                    f'font-weight:{500 if t.get("display_headings") else 700};line-height:1.2;color:{t["primary"]};'
                    f'padding-bottom:18px;border-bottom:1px solid {t["border"]};">{escape(title)}</h1>')

    pre = ""
    if preheader:
        pre = (f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;'
               f'line-height:1px;color:{t["bg"]};opacity:0;">{escape(preheader)}'
               + "&#8199;&#65279;&#847; " * 30 + "</div>")

    inner = masthead + content
    if t.get("card"):
        top = (f'<tr><td style="background-color:{t["masthead"]};height:3px;line-height:3px;font-size:1px;">'
               f'&nbsp;</td></tr>') if t.get("masthead") else ""
        inner = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
                 f'<td align="center"><table role="presentation" class="e-card" cellpadding="0" cellspacing="0" '
                 f'border="0" width="680" style="width:100%;max-width:680px;background-color:{t["card_bg"]};'
                 f'border:1px solid {t["border"]};border-radius:12px;">{top}<tr><td class="e-pad" '
                 f'style="padding:32px;">{inner}</td></tr></table></td></tr></table>')

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" lang="{escape(lang)}">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="X-UA-Compatible" content="IE=edge" />
<meta name="color-scheme" content="{scheme}" />
<meta name="supported-color-schemes" content="{scheme}" />
<title>{escape(title)}</title>
<!--[if gte mso 9]><xml><o:OfficeDocumentSettings><o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<!--[if mso]><style type="text/css">
body, table, td, p, a, li, span, h2, h3 {{ font-family: 'Segoe UI', Arial, sans-serif !important; }}
h1 {{ font-family: {"Georgia, serif" if t.get("display_headings") else "'Segoe UI', Arial, sans-serif"} !important; }}
</style><![endif]-->
<style type="text/css">
body, table, td, p, a, li {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
img {{ -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }}
a {{ word-break: break-word; }}
:root {{ color-scheme: {scheme}; supported-color-schemes: {scheme}; }}
{dark_block}
{ogsc}
@media only screen and (max-width: 600px) {{ .e-body {{ padding: 12px 6px !important; }} .e-pad {{ padding: 20px !important; }} }}
</style>
</head>
<body class="e-body" style="margin:0;padding:{"28px 12px" if t.get("card") else "8px"};background-color:{t["bg"]};font-family:{t["font_body"]};font-size:{t["base_size"]};line-height:{t["base_line"]};color:{t["text"]};">
{pre}{inner}
</body>
</html>"""


# --------------------------------------------------------------- plain text --

def to_text(md: str, labels: dict | None = None, aliases: dict | None = None) -> str:
    """The text/plain part: the same message, readable without any markup."""
    labels = {k.lower(): str(v) for k, v in (labels or {}).items()}
    aliases = {str(k).lower(): str(v).lower() for k, v in (aliases or {}).items() if str(v).lower() in BADGES}
    md = md.replace("\x00", "")
    out: list[str] = []
    in_code = False
    in_alert = False
    for raw in md.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if in_alert and not line.strip().startswith(">"):
            in_alert = False
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append("    " + line)
            continue
        s = line.strip()
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            out.append("-" * 40)
            continue
        if "|" in s and re.match(r"^\|?\s*:?-{2,}", s) and set(s) <= set("|:- "):
            continue
        if s.startswith("|"):
            out.append("  " + " | ".join(_inline_text(c, labels, aliases) for c in Renderer.split_row(s)))
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            out.append("-" * 40)
            continue
        m = re.match(r"^(#{1,3})\s+(.+)$", s)
        if m:
            text = _inline_text(m.group(2), labels, aliases)
            out += ["", text, ("=" if len(m.group(1)) == 1 else "-") * min(len(text), 60)]
            continue
        m = re.match(r"^>\s?\[!(\w+)\]\s*(.*)$", s)
        if m and m.group(1).upper() in ALERTS:
            title = labels.get(m.group(1).lower(), ALERTS[m.group(1).upper()][1])
            out.append(f"{title.upper()}: {_inline_text(m.group(2), labels, aliases)}".rstrip())
            in_alert = True
            continue
        if s.startswith(">"):
            rest = _inline_text(re.sub(r"^>\s?", "", s), labels, aliases)
            if in_alert and out and out[-1].endswith(":"):
                out[-1] += " " + rest
            else:
                out.append(("  " if in_alert else "| ") + rest)
            continue
        m = re.match(r"^\[\[([^\]]+)\]\]\(([^)\s]+)\)$", s)
        if m:
            out.append(f"{m.group(1)}: {m.group(2)}")
            continue
        m = re.match(r"^([-*+])\s+(.*)$", s)
        if m:
            out.append("  - " + _inline_text(m.group(2), labels, aliases))
            continue
        out.append(_inline_text(line, labels, aliases))
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _inline_text(s: str, labels: dict, aliases: dict) -> str:
    s = re.sub(r"!\[([^\]]*)\]\(attachment:([^)]+)\)", r"[attached: \2]", s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", s)
    s = re.sub(r"\[\[([^\]]+)\]\]\(([^)\s]+)\)", r"\1: \2", s)

    def link(m):
        text, url = m.group(1), m.group(2)
        return text if text == url or url == f"mailto:{text}" else f"{text} ({url})"
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)

    keys = "|".join(re.escape(k) for k in sorted(set(BADGES) | set(aliases), key=len, reverse=True))

    def badge(m):
        key = aliases.get(m.group(1).lower(), m.group(1).lower())
        return f"[{labels.get(key, BADGES[key][2])}]"
    s = re.sub(rf"\[({keys})\]", badge, s, flags=re.I)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"\1", s)
    s = re.sub(r"(?<![\w_])_([^_\s][^_]*?)_(?![\w_])", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s
