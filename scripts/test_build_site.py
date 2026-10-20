"""Regression checks for locale completeness, safe output and real demo media."""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import build_site


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source_copy(self):
        source = self.root / "site"
        shutil.copytree(build_site.ROOT / "site", source)
        return source

    def test_complete_bilingual_pages_and_media(self):
        output = self.root / "public" / "project-name"
        build_site.build(build_site.ROOT / "site", output)
        for locale in build_site.LOCALES:
            html = (output / locale / "index.html").read_text()
            self.assertIn(f'lang="{locale}"', html)
            self.assertEqual(html.count('class="media-pair"'), 3)
            self.assertEqual(html.count('class="demo motion-demo"'), 3)
            self.assertEqual(html.count('class="demo still-demo"'), 3)
            self.assertEqual(html.count("data-animation="), 3)
            self.assertIn("https://github.com/shabbywu/ultralight-py", html)
            self.assertIn("../assets/", html)
            self.assertIn(
                f'href="../{locale}/" lang="{locale}" hreflang="{locale}" data-language="{locale}" aria-current="page"',
                html,
            )
            self.assertNotIn("{{", html)
        self.assertTrue((output / "en/licenses.html").is_file())
        self.assertTrue((output / "zh-CN/licenses.html").is_file())

    def test_missing_translation_fails_before_replacing_previous_build(self):
        source = self.source_copy()
        p = source / "locales/en.json"
        catalog = json.loads(p.read_text())
        del catalog["pause"]
        p.write_text(json.dumps(catalog))
        output = self.root / "dist"
        output.mkdir()
        (output / "keep.txt").write_text("previous build")
        with self.assertRaisesRegex(ValueError, "identical keys"):
            build_site.build(source, output)
        self.assertEqual((output / "keep.txt").read_text(), "previous build")

    def test_changed_styles_invalidate_cached_assets_on_every_page(self):
        source = self.source_copy()
        output = self.root / "dist"
        build_site.build(source, output)
        before = hashlib.sha256((source / "assets/style.css").read_bytes()).hexdigest()[
            :12
        ]
        for page in output.rglob("*.html"):
            self.assertIn(f"style.css?v={before}", page.read_text())
            self.assertRegex(page.read_text(), r"app\.js\?v=[0-9a-f]{12}")
        css = source / "assets/style.css"
        css.write_text(css.read_text() + "\n/* updated style */\n")
        build_site.build(source, output)
        after = hashlib.sha256(css.read_bytes()).hexdigest()[:12]
        self.assertNotEqual(before, after)
        for page in output.rglob("*.html"):
            self.assertIn(f"style.css?v={after}", page.read_text())
            self.assertNotIn(f"style.css?v={before}", page.read_text())

    def test_translation_placeholder_must_match(self):
        source = self.source_copy()
        p = source / "locales/en.json"
        catalog = json.loads(p.read_text())
        catalog["expand_label"] = "Enlarge {wrong}"
        p.write_text(json.dumps(catalog))
        with self.assertRaisesRegex(ValueError, "placeholders"):
            build_site.read_content(source)

    def test_still_webp_cannot_masquerade_as_animation(self):
        p = self.root / "fake.webp"
        p.write_bytes(b"RIFF\x04\0\0\0WEBP")
        with self.assertRaisesRegex(ValueError, "multiple real animation frames"):
            build_site.animation_frames(p)

    def test_link_validator_catches_subpath_escape_and_missing_anchor(self):
        out = self.root / "public"
        out.mkdir()
        for ref, error in (
            ("/assets/style.css", "Root-relative"),
            ("../outside.html", "Missing local"),
            ("#absent", "Missing anchor"),
        ):
            (out / "index.html").write_text(f'<a href="{ref}">link</a>')
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, error):
                build_site.validate(out)

    def test_localized_content_is_escaped(self):
        self.assertEqual(
            build_site.render("<h1>{{title}}</h1>", {"title": '<script>"&'}),
            "<h1>&lt;script&gt;&quot;&amp;</h1>",
        )

    def test_duplicate_project_ids_are_rejected(self):
        source = self.source_copy()
        p = source / "projects.json"
        projects = json.loads(p.read_text())
        projects[1]["id"] = projects[0]["id"]
        p.write_text(json.dumps(projects))
        with self.assertRaisesRegex(ValueError, "unique URL-safe"):
            build_site.read_content(source)

    def test_demo_paths_cannot_escape_asset_directory(self):
        source = self.source_copy()
        p = source / "projects.json"
        projects = json.loads(p.read_text())
        projects[0]["animation"] = "index.html"
        p.write_text(json.dumps(projects))
        with self.assertRaisesRegex(ValueError, "Missing demo or license"):
            build_site.read_content(source)


if __name__ == "__main__":
    unittest.main()
