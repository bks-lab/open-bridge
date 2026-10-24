"""Part of a mandant as recipients (`mandant:<id>#<group>`), and a profile that
switches heading styles off."""

from __future__ import annotations

from tests.support import BridgeCase

ACME_GROUPS = "groups:\n  leads: [anna]\n  everyone: [anna, ben]\n"


class Groups(BridgeCase):
    def setUp(self):
        super().setUp()
        path = self.root / "identity/mandants/acme.yaml"
        path.write_text(path.read_text() + ACME_GROUPS, encoding="utf-8")

    def resolve(self, *tokens):
        from engine import recipients
        return recipients.resolve(self.root, list(tokens))

    def test_a_group_is_only_its_members(self):
        self.assertEqual([r.address for r in self.resolve("mandant:acme#leads")], ["anna@acme.example"])
        self.assertEqual(len(self.resolve("mandant:acme#everyone")), 2)

    def test_whole_mandant_still_works(self):
        self.assertEqual(len(self.resolve("mandant:acme")), 2)

    def test_unknown_group_names_the_defined_ones(self):
        from engine.config import ConfigError
        with self.assertRaisesRegex(ConfigError, r"no group 'board'.*everyone, leads"):
            self.resolve("mandant:acme#board")

    def test_member_that_is_no_person_is_an_error(self):
        from engine.config import ConfigError
        path = self.root / "identity/mandants/acme.yaml"
        path.write_text(path.read_text().replace("leads: [anna]", "leads: [anna, zed]"), encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "'zed'"):
            self.resolve("mandant:acme#leads")

    def test_validate_reports_a_member_that_is_no_person(self):
        from engine import validate
        path = self.root / "identity/mandants/acme.yaml"
        path.write_text(path.read_text().replace("leads: [anna]", "leads: [zed]"), encoding="utf-8")
        self.assertTrue(any("group 'leads'" in p and "'zed'" in p for p in validate.run(self.root)))

    def test_group_greeting_uses_the_mandant_name(self):
        d = self.build(to=["mandant:acme#everyone"], body="Text.", attachments=[str(self.root / "cv.pdf")])
        self.assertEqual(len(d.to), 2)

    def test_mandant_schema_accepts_groups(self):
        """The CORE schema, not only the engine, knows the block."""
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("schema checks need jsonschema")
        from pathlib import Path
        from engine.config import load_yaml
        repo = Path(__file__).resolve().parents[3]
        schema = load_yaml(repo / "identity/mandants/_schema.yaml")
        data = load_yaml(self.root / "identity/mandants/acme.yaml")
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(data)), [])
        data["groups"] = {"Bad Name": ["anna"]}
        self.assertNotEqual(list(Draft202012Validator(schema).iter_errors(data)), [])
        template = load_yaml(repo / "identity/mandants/_template.yaml")
        self.assertIn("groups", template)
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(template)), [])


class HeadingStylesOff(BridgeCase):
    BODY = "## Summary\n\nx\n\n## Blocked\n\ny"

    def setUp(self):
        super().setUp()
        cfg = self.root / "bridge-config.yaml"
        old = cfg.read_text() if cfg.is_file() else ""
        cfg.write_text(old + "mail:\n  heading_styles: {callout: [Summary], warning: [Blocked]}\n",
                       encoding="utf-8")

    def profile(self, extra: str):
        path = self.root / "workflow/mail-profiles/everyday.yaml"
        path.write_text(path.read_text() + extra, encoding="utf-8")

    def test_global_styles_reach_a_profile_that_says_nothing(self):
        d = self.build(to=["x@example.org"], body=self.BODY)
        self.assertIn('class="e-callout"', d.html)

    def test_profile_switches_styles_off(self):
        self.profile("heading_styles: false\n")
        d = self.build(to=["x@example.org"], body=self.BODY)
        self.assertNotIn('class="e-callout"', d.html)
        self.assertNotIn('<h2 class="e-warn"', d.html)
        self.assertTrue(any("heading styles off" in x for x in d.decisions))

    def test_off_is_valid_in_the_schema(self):
        from engine.validate import run
        self.profile("heading_styles: false\n")
        self.assertEqual(run(self.root), [])

    def test_a_child_profile_can_switch_them_back_on(self):
        self.profile("heading_styles: false\n")
        self.write("workflow/mail-profiles/report.yaml",
                   "schema_version: 1\nscope: user\nid: report\nextends: everyday\n"
                   "heading_styles: {callout: [Summary]}\n")
        d = self.build(to=["x@example.org"], body=self.BODY, profile="report")
        self.assertIn('class="e-callout"', d.html)

    def test_plain_never_dresses_a_heading(self):
        d = self.build(to=["x@example.org"], body=self.BODY, theme="plain")
        self.assertNotIn('class="e-callout"', d.html)
        self.assertNotIn('<h2 class="e-warn"', d.html)
