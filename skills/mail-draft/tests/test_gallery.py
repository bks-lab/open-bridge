"""The gallery: one sample mail per profile on one local page, nothing sent."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.support import BridgeCase


class Gallery(BridgeCase):
    def run_gallery(self, *extra) -> tuple[int, str, Path]:
        from engine.cli import main
        out = self.root / "out-gallery"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["gallery", "--out", str(out), *extra])
        return code, buf.getvalue(), out

    def test_one_tile_per_profile_and_per_builtin_theme(self):
        code, _, out = self.run_gallery()
        self.assertEqual(code, 0)
        page = (out / "index.html").read_text(encoding="utf-8")
        for pid in ("everyday", "application", "family"):
            self.assertIn(f'id="profile-{pid}"', page)
            self.assertTrue((out / f"profile-{pid}.html").is_file(), pid)
        for theme in ("design", "minimal", "plain"):
            self.assertIn(f'id="builtin-{theme}"', page)
            self.assertTrue((out / f"builtin-{theme}.html").is_file(), theme)

    def test_tile_names_purpose_theme_and_footer(self):
        self.write("workflow/mail-profiles/report.yaml",
                   "schema_version: 1\nscope: user\nid: report\ntitle: Status report\n"
                   "description: Weekly status to a customer.\nfooter: contact\ntheme: design\n")
        _, _, out = self.run_gallery()
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn("Status report", page)
        self.assertIn("Weekly status to a customer.", page)
        self.assertIn("footer contact", page)
        self.assertIn("theme design", page)

    def test_rendered_sample_is_the_profiles_own_dress(self):
        _, _, out = self.run_gallery()
        family = (out / "profile-family.html").read_text(encoding="utf-8")
        everyday = (out / "profile-everyday.html").read_text(encoding="utf-8")
        # family: footer false, plain theme, its own sign-off
        self.assertIn("Love,", family)
        self.assertNotIn("Example Studio", family)
        # everyday: the contact footer
        self.assertIn("Example Studio", everyday)

    def test_page_is_offline(self):
        _, _, out = self.run_gallery()
        for path in out.glob("*.html"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("<script src=", text, path.name)
            self.assertNotIn("fonts.googleapis", text, path.name)
            self.assertNotIn('<link rel="stylesheet"', text, path.name)

    def test_never_reaches_a_mail_client(self):
        with mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen:
            code, _, _ = self.run_gallery()
        self.assertEqual(code, 0)
        run.assert_not_called()
        popen.assert_not_called()

    def test_default_output_is_under_the_drafts_dir(self):
        from engine.cli import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["gallery"]), 0)
        self.assertTrue((self.root / ".bridge" / "mail-drafts" / "gallery" / "index.html").is_file())

    def test_own_sample_body(self):
        sample = self.write("sample.md", "A sample sentence only this test writes.")
        _, _, out = self.run_gallery("--body-file", str(sample))
        self.assertIn("A sample sentence only this test writes.",
                      (out / "profile-everyday.html").read_text(encoding="utf-8"))

    def test_a_broken_profile_is_shown_not_fatal(self):
        self.write("workflow/mail-profiles/broken.yaml",
                   "schema_version: 1\nscope: user\nid: broken\nfooter: missing-footer\n")
        code, printed, out = self.run_gallery()
        self.assertEqual(code, 0)
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="profile-broken"', page)
        self.assertIn("missing-footer", page)
        self.assertIn("broken", printed)

    def test_prints_the_page_path(self):
        _, printed, out = self.run_gallery()
        self.assertIn(str(out / "index.html"), printed)


if __name__ == "__main__":
    unittest.main()
