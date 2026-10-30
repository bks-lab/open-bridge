"""Markdown, footer, theme: what reaches the recipient's screen."""

from __future__ import annotations

import datetime as dt
import unittest

from tests.support import BridgeCase


def renderer():
    from engine.markdown import Renderer
    from engine.theme import BUILTIN, Theme, NEUTRAL_DARK
    return Renderer(Theme(dict(BUILTIN["minimal"]), dict(NEUTRAL_DARK), [], "minimal"))


class Links(unittest.TestCase):
    def test_javascript_link_is_not_linked(self):
        html = renderer().render("[click](javascript:alert(1))")
        self.assertNotIn("href", html)

    def test_file_link_is_not_linked(self):
        self.assertNotIn("href", renderer().render("[x](file:///etc/passwd)"))

    def test_https_link_is_linked_and_underlined(self):
        html = renderer().render("[site](https://example.com)")
        self.assertIn('href="https://example.com"', html)
        self.assertIn("text-decoration:underline", html)

    def test_bare_url_links_to_itself(self):
        html = renderer().render("see https://example.com/a.")
        self.assertIn('href="https://example.com/a"', html)

    def test_markup_in_text_is_escaped(self):
        html = renderer().render("<script>x</script>")
        self.assertNotIn("<script>", html)


class Blocks(unittest.TestCase):
    def test_alert(self):
        html = renderer().render("> [!WARNING]\n> careful")
        self.assertIn("Warning", html)
        self.assertIn("careful", html)

    def test_table_alignment(self):
        html = renderer().render("| a | b |\n|:--|--:|\n| 1 | 2 |")
        self.assertIn("text-align:right", html)

    def test_button_has_outlook_vml(self):
        html = renderer().render("[[Go]](https://example.com)")
        self.assertIn("v:roundrect", html)
        self.assertIn('class="e-btn"', html)

    def test_badge_label_is_configurable(self):
        from engine.markdown import Renderer
        r = renderer()
        r2 = Renderer(r.t, labels={"done": "FINISHED"}, aliases={"ok": "done"})
        self.assertIn("FINISHED", r2.render("[ok]"))

    def test_consecutive_lines_are_one_paragraph(self):
        html = renderer().render("Best,\nAlex")
        self.assertEqual(html.count("<p "), 1)
        self.assertIn("<br />", html)

    def test_text_part_writes_links_out(self):
        from engine.markdown import to_text
        self.assertIn("site (https://example.com)", to_text("[site](https://example.com)"))


class Footer(BridgeCase):
    def load(self, **kw):
        from engine import footer
        return footer.load(self.root, kw.pop("fid", "contact"), **kw)

    def theme(self):
        from engine.theme import load
        return load("design", self.root)

    def test_persona_fills_name_and_email(self):
        cfg = self.load()
        self.assertEqual(cfg["name"], "Alex Example")
        self.assertEqual(cfg["email"], "alex@example.com")

    def test_extends_inherits_and_overrides(self):
        cfg = self.load(fid="team")
        self.assertEqual(cfg["org"], "Example Studio")
        self.assertEqual(cfg["style"], "compact")
        self.assertEqual(cfg["cards"], [])

    def test_language_variant(self):
        self.assertEqual(self.load(language="de")["role"], "[de] Consultant")
        self.assertEqual(self.load(language="de-AT")["role"], "[de] Consultant")

    def test_notice_only_inside_its_window(self):
        from engine import footer
        cfg = self.load()
        inside = footer.render_html(cfg, self.theme(), today=dt.date(2026, 8, 1))
        outside = footer.render_html(cfg, self.theme(), today=dt.date(2026, 9, 1))
        self.assertIn("Away from", inside)
        self.assertNotIn("Away from", outside)

    def test_visitor_query_only_for_a_plain_name(self):
        from engine import footer
        cfg = self.load()
        self.assertEqual(footer.visitor_query(cfg, "Anna"), "?for=Anna")
        self.assertEqual(footer.visitor_query(cfg, "Anna", informal=True), "?for=Anna&tone=casual")
        self.assertEqual(footer.visitor_query(cfg, "<b>x</b>"), "")
        self.assertEqual(footer.visitor_query(cfg, "a@b.example"), "")

    def test_field_markup_is_escaped(self):
        from engine import footer
        cfg = dict(self.load(), role="<img src=x onerror=alert(1)>")
        self.assertNotIn("<img", footer.render_html(cfg, self.theme()))

    def test_styles(self):
        from engine import footer
        t = self.theme()
        card = footer.render_html(self.load(), t)
        compact = footer.render_html(self.load(style="compact"), t)
        minimal = footer.render_html(self.load(style="minimal"), t)
        text = footer.render_html(self.load(style="text"), t)
        self.assertIn("Recent work", card)
        self.assertNotIn("Recent work", compact)
        self.assertIn("LinkedIn", compact)
        self.assertNotIn("LinkedIn", minimal)
        self.assertNotIn("<table", text)

    def test_badge_colour_by_role_token_or_hex(self):
        from engine import footer
        t = self.theme()
        self.assertEqual(footer._color("link", t), t["link"])
        self.assertEqual(footer._color("secondary", t), "#2d5b8f")     # DESIGN.md token, not a role
        self.assertEqual(footer._color("#0A66C2", t), "#0A66C2")
        self.assertEqual(footer._color("nonsense", t), t["primary"])

    def test_unknown_footer_names_the_known_ones(self):
        from engine.config import ConfigError
        with self.assertRaisesRegex(ConfigError, "defined: contact, team"):
            self.load(fid="nope")


class Theme(BridgeCase):
    def test_link_skips_an_unreadable_accent(self):
        from engine.theme import contrast, load
        t = load("design", self.root)
        self.assertEqual(t["link"], "#2d5b8f")          # accent #5fa0d9 is 2.7:1, secondary wins
        self.assertGreaterEqual(contrast(t["link"], t["card_bg"]), 4.5)

    def test_no_readable_candidate_is_darkened_and_reported(self):
        from engine.theme import build_design, contrast
        t = build_design({"colors": {"accent": "#9fc5ff", "surface": "#ffffff"}})
        self.assertGreaterEqual(contrast(t["link"], "#ffffff"), 4.5)
        self.assertTrue(any("darkened" in n for n in t.notes))

    def test_dark_palette_from_colorsDark(self):
        from engine.theme import load
        self.assertEqual(load("design", self.root).dark["card_bg"], "#191e24")

    def test_override_token(self):
        from engine.theme import load
        self.assertEqual(load("design", self.root, {"link": "info"})["link"], "#2d5b8f")


class Designs(BridgeCase):
    """The persona a mail goes out under may wear its own design (identity/designs/)."""

    BRAND = ("---\nversion: alpha\nscope: user\nname: second\ndescription: A second brand.\n"
             "colors:\n  primary: \"#5A1E3C\"\n  secondary: \"#7A2E14\"\n  surface: \"#FFFFFF\"\n---\n# Second\n")

    def test_persona_design_ref_dresses_the_mail(self):
        self.write("identity/designs/second.md", self.BRAND)
        persona = self.root / "identity" / "personas" / "alex.yaml"
        persona.write_text(persona.read_text(encoding="utf-8") + "design_ref: second\n", encoding="utf-8")
        d = self.build(to=["acme/ben"], profile="everyday")
        self.assertEqual(d.theme.tokens.get("primary"), "#5a1e3c")
        self.assertNotIn("#0f2a4a", d.html.lower(), "the root DESIGN.md primary leaked into a second-brand mail")

    def test_without_design_ref_the_root_design_dresses_it(self):
        self.write("identity/designs/second.md", self.BRAND)
        d = self.build(to=["acme/ben"], profile="everyday")
        self.assertEqual(d.theme.tokens.get("primary"), "#0f2a4a")

    def test_an_unknown_design_ref_is_an_error_not_the_root(self):
        from engine.config import ConfigError
        persona = self.root / "identity" / "personas" / "alex.yaml"
        persona.write_text(persona.read_text(encoding="utf-8") + "design_ref: nobody\n", encoding="utf-8")
        with self.assertRaises(ConfigError) as err:
            self.build(to=["acme/ben"], profile="everyday")
        self.assertIn("nobody", str(err.exception))


if __name__ == "__main__":
    unittest.main()
