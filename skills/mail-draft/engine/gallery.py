"""The gallery: every way this Bridge can dress a mail, on one local page.

One tile per built-in theme and one per profile in workflow/mail-profiles/,
each with a sample mail rendered exactly as a draft for that profile would be.
It exists so a person can SEE the occasions before picking one, and so a change
to DESIGN.md or a footer shows up everywhere at once.

Nothing here reaches a mail client: the module imports no client and calls no
process. The output is a directory of HTML files, by default under
`mail.drafts_dir` (gitignored: a rendered footer carries names and numbers).
"""

from __future__ import annotations

import html as h
from pathlib import Path

from . import profiles
from .config import ConfigError, MailConfig
from .draft import Request, build
from .markdown import Renderer, document
from .theme import load as load_theme

SAMPLE = """Here is a short sample, so every occasion can be compared on the same text.

## Summary

| Item | Owner | Status |
|------|-------|--------|
| [Release notes](https://example.com/notes) | Sam | [done] |
| Data migration | Alex | [progress] |
| Access for the new team | Kim | [blocked] |

## Next steps

- Review the **migration plan** by Friday
- Confirm the date for the `v2` cut-over

> [!NOTE]
> Times are in the recipient's time zone.

[[Open the board]](https://example.com/board)
"""

THEMES = ("design", "minimal", "plain")


def _write_pair(out: Path, stem: str, light: str, dark: str) -> None:
    (out / f"{stem}.html").write_text(light, encoding="utf-8")
    (out / f"{stem}-dark.html").write_text(dark, encoding="utf-8")


def _tile(stem: str, name: str, title: str, purpose: str, meta: list[str], notes: list[str]) -> str:
    meta_html = " · ".join(h.escape(m) for m in meta if m)
    notes_html = "".join(f"<li>{h.escape(n)}</li>" for n in notes)
    return f"""<article class="tile" id="{h.escape(stem)}">
<header><h2>{h.escape(title or name)}</h2><code>{h.escape(name)}</code></header>
<p class="purpose">{h.escape(purpose) if purpose else "&nbsp;"}</p>
<p class="meta">{meta_html}</p>
{f'<ul class="notes">{notes_html}</ul>' if notes_html else ''}
<iframe loading="lazy" title="{h.escape(name)}" src="{h.escape(stem)}.html" data-light="{h.escape(stem)}.html"
 data-dark="{h.escape(stem)}-dark.html"></iframe>
<p class="open"><a href="{h.escape(stem)}.html">light</a> · <a href="{h.escape(stem)}-dark.html">dark</a></p>
</article>"""


def _page(tiles: list[str], root: Path) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Mail gallery</title>
<style>
:root {{ color-scheme: light dark; --bg:#f4f4f5; --fg:#18181b; --muted:#52525b; --card:#ffffff; --line:#d4d4d8; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#18181b; --fg:#f4f4f5; --muted:#a1a1aa; --card:#27272a; --line:#3f3f46; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 system-ui, -apple-system, 'Segoe UI', sans-serif; }}
.top {{ padding:16px; display:flex; flex-wrap:wrap; gap:12px; align-items:baseline; }}
.top h1 {{ margin:0; font-size:20px; }} .top p {{ margin:0; color:var(--muted); }}
.top button {{ font:inherit; padding:4px 12px; border-radius:6px; border:1px solid var(--line); background:var(--card); color:var(--fg); cursor:pointer; }}
main {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 520px), 1fr)); gap:16px; padding:0 16px 24px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; min-width:0; }}
.tile header {{ display:flex; justify-content:space-between; gap:8px; align-items:baseline; }}
.tile h2 {{ margin:0; font-size:16px; }} .tile code {{ color:var(--muted); }}
.purpose {{ margin:4px 0; }} .meta {{ margin:0 0 8px; color:var(--muted); font-size:12px; }}
.notes {{ margin:0 0 8px; padding-left:18px; color:#b45309; font-size:12px; }}
iframe {{ width:100%; height:640px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
.open {{ margin:6px 0 0; font-size:12px; }}
</style></head><body>
<div class="top"><h1>Mail gallery</h1>
<p>Every built-in theme and every profile of {h.escape(root.name)}, rendered on the same sample. Nothing here is sent.</p>
<button type="button" id="mode">show dark</button></div>
<main>
{chr(10).join(tiles)}
</main>
<script>
(function () {{
  var dark = false, btn = document.getElementById('mode');
  btn.addEventListener('click', function () {{
    dark = !dark;
    btn.textContent = dark ? 'show light' : 'show dark';
    document.querySelectorAll('iframe').forEach(function (f) {{
      f.src = dark ? f.dataset.dark : f.dataset.light;
    }});
  }});
}})();
</script>
</body></html>
"""


def run(cfg: MailConfig, out: Path | None = None, body: str = "") -> tuple[Path, list[str]]:
    """Write the gallery. Returns (index.html, problems worth printing)."""
    root = cfg.root
    out = out or (cfg.drafts_dir / "gallery")
    out.mkdir(parents=True, exist_ok=True)
    sample = body or SAMPLE
    tiles: list[str] = []
    problems: list[str] = []

    labels = cfg.get("labels") or {}
    aliases = cfg.get("badge_aliases") or {}
    styles = cfg.get("heading_styles") or {}
    for name in THEMES:
        t = load_theme(name, root, cfg.get("tokens") or {})
        content = Renderer(t, labels, aliases, styles).render(sample)
        shell = {"title": f"Theme {name}", "eyebrow": "Built-in", "lang": str(cfg.get("language") or "en")}
        _write_pair(out, f"builtin-{name}", document(content, t, dark_css=False, **shell),
                    document(content, t, force_dark=True, **shell))
        tiles.append(_tile(f"builtin-{name}", name, f"Theme {name}",
                           "Built-in theme, no profile and no footer.", [f"theme {name}"], []))

    files = profiles.available(root)
    for pid in sorted(files):
        raw = files[pid] or {}
        stem = f"profile-{pid}"
        try:
            resolved = profiles.resolve(files, pid)
            d = build(Request(to=["reader@example.com"], subject=str(resolved.get("title") or pid),
                              body=sample, profile=pid, recipient_name="Alex"), cfg)
        except ConfigError as err:
            problems.append(f"{pid}: {err}")
            msg = h.escape(str(err))
            page = f"<!doctype html><meta charset='utf-8'><p style='font:14px system-ui;padding:16px'>{msg}</p>"
            _write_pair(out, stem, page, page)
            tiles.append(_tile(stem, pid, str(raw.get("title") or pid), str(raw.get("description") or ""),
                               ["not renderable"], [str(err)]))
            continue
        dark = document(d.content, d.theme, force_dark=True, **d.shell)
        _write_pair(out, stem, d.html_static, dark)
        footer = resolved.get("footer")
        meta = [f"theme {d.theme_name}", "no footer" if footer is False else f"footer {d.footer_id or '-'}",
                f"client {d.client}" if getattr(d, "client", "") else "", f"sender {d.sender}" if d.sender else "",
                f"language {d.language}" if d.language else ""]
        notes = [e for e in d.errors if "attachment" not in e]
        tiles.append(_tile(stem, pid, str(resolved.get("title") or pid),
                           str(resolved.get("description") or ""), meta, notes))

    index = out / "index.html"
    index.write_text(_page(tiles, root), encoding="utf-8")
    return index, problems
