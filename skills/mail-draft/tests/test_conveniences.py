"""Nicknames, link aliases and heading styles: what an instance moving from an
older mail tool needs so its mails keep looking and resolving the same."""

from __future__ import annotations

import unittest

from tests.support import BridgeCase


class Nicknames(BridgeCase):
    def setUp(self):
        super().setUp()
        self.write("identity/mandants/acme.yaml",
                   "schema_version: 1\nscope: user\nid: acme\ntype: company\ndisplay_name: Acme Ltd\n"
                   "persons:\n"
                   "  - id: anna_schmidt\n    display_name: Anna Schmidt\n    nicknames: [anna, as]\n"
                   "    channels: {email: anna@acme.example}\n")

    def test_a_nickname_resolves_like_the_person_id(self):
        from engine.recipients import resolve
        r = resolve(self.root, ["anna"])
        self.assertEqual([x.address for x in r], ["anna@acme.example"])
        self.assertEqual(r[0].person_id, "anna_schmidt")

    def test_nickname_match_ignores_case(self):
        from engine.recipients import resolve
        self.assertEqual(resolve(self.root, ["AS"])[0].address, "anna@acme.example")

    def test_an_id_wins_over_someone_elses_nickname(self):
        from engine.recipients import resolve
        self.write("identity/mandants/other.yaml",
                   "schema_version: 1\nscope: user\nid: other\ntype: company\n"
                   "persons:\n  - id: anna\n    channels: {email: anna@other.example}\n")
        self.assertEqual(resolve(self.root, ["anna"])[0].address, "anna@other.example")

    def test_an_ambiguous_nickname_is_refused(self):
        from engine.recipients import RecipientError, resolve
        self.write("identity/mandants/other.yaml",
                   "schema_version: 1\nscope: user\nid: other\ntype: company\n"
                   "persons:\n  - id: ann_other\n    nicknames: [anna]\n"
                   "    channels: {email: ann@other.example}\n")
        with self.assertRaises(RecipientError) as err:
            resolve(self.root, ["anna"])
        self.assertIn("more than one", str(err.exception))


class LinkAliases(BridgeCase):
    def test_profile_alias_becomes_the_url(self):
        self.write("workflow/mail-profiles/everyday.yaml",
                   (self.root / "workflow/mail-profiles/everyday.yaml").read_text()
                   + 'link_aliases: {"site:home": "https://example.com/"}\n')
        d = self.build(to=["x@example.org"], body="See [our page](site:home).")
        self.assertIn('href="https://example.com/"', d.html)
        self.assertIn("https://example.com/", d.text)
        self.assertNotIn("site:home", d.html)

    def test_config_alias_applies_and_profile_wins(self):
        cfg = self.root / "bridge-config.yaml"
        cfg.write_text('mail:\n  link_aliases: {"site:home": "https://config.example/", '
                       '"site:blog": "https://config.example/blog"}\n', encoding="utf-8")
        self.write("workflow/mail-profiles/everyday.yaml",
                   (self.root / "workflow/mail-profiles/everyday.yaml").read_text()
                   + 'link_aliases: {"site:home": "https://profile.example/"}\n')
        d = self.build(to=["x@example.org"], body="[a](site:home) [b](site:blog)")
        self.assertIn('href="https://profile.example/"', d.html)
        self.assertIn('href="https://config.example/blog"', d.html)

    def test_unknown_alias_is_an_error(self):
        d = self.build(to=["x@example.org"], body="[a](site:nowhere)")
        self.assertTrue(any("site:nowhere" in e for e in d.errors), d.errors)

    def test_alias_target_must_be_a_safe_url(self):
        self.write("workflow/mail-profiles/everyday.yaml",
                   (self.root / "workflow/mail-profiles/everyday.yaml").read_text()
                   + 'link_aliases: {"site:bad": "javascript:alert(1)"}\n')
        d = self.build(to=["x@example.org"], body="[a](site:bad)")
        self.assertNotIn("javascript:", d.html)
        self.assertTrue(any("site:bad" in e for e in d.errors), d.errors)

    def test_mailto_and_tel_are_not_aliases(self):
        d = self.build(to=["x@example.org"], body="[m](mailto:a@example.org) [t](tel:+4912345)")
        self.assertEqual(d.errors, [])
        self.assertIn('href="mailto:a@example.org"', d.html)


class HeadingStyles(BridgeCase):
    def renderer(self, styles):
        from engine.markdown import Renderer
        from engine.theme import BUILTIN, NEUTRAL_DARK, Theme
        return Renderer(Theme(dict(BUILTIN["minimal"]), dict(NEUTRAL_DARK), [], "minimal"),
                        heading_styles=styles)

    def test_a_listed_word_makes_a_callout_heading(self):
        html = self.renderer({"callout": ["Summary"]}).render("## Summary\n\ntext")
        self.assertIn('<h2 class="e-callout"', html)

    def test_a_listed_word_makes_a_warning_heading(self):
        html = self.renderer({"warning": ["Critical"]}).render("## Critical issues")
        self.assertIn('<h2 class="e-warn"', html)
        self.assertIn("border-left:3px solid", html)

    def test_match_is_a_whole_word_and_ignores_case(self):
        r = self.renderer({"warning": ["risk"]})
        self.assertIn('class="e-warn"', r.render("## RISK"))
        self.assertNotIn('class="e-warn"', r.render("## Asterisks"))

    def test_without_styles_a_heading_stays_plain(self):
        html = self.renderer(None).render("## Summary")
        self.assertIn('<h2 class="e-h"', html)

    def test_profile_styles_reach_the_draft(self):
        self.write("workflow/mail-profiles/everyday.yaml",
                   (self.root / "workflow/mail-profiles/everyday.yaml").read_text()
                   + "heading_styles: {callout: [Overview], warning: [Blocked]}\n")
        d = self.build(to=["x@example.org"], body="## Overview\n\nx\n\n## Blocked\n\ny")
        self.assertIn('<h2 class="e-callout"', d.html)
        self.assertIn('<h2 class="e-warn"', d.html)

    def test_schema_accepts_the_new_profile_keys(self):
        from engine.validate import run
        self.write("workflow/mail-profiles/everyday.yaml",
                   (self.root / "workflow/mail-profiles/everyday.yaml").read_text()
                   + "heading_styles: {callout: [Overview]}\n"
                   + 'link_aliases: {"site:home": "https://example.com/"}\n')
        self.assertEqual(run(self.root), [])


if __name__ == "__main__":
    unittest.main()
