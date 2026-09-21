import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class BrandIdentityTests(SimpleTestCase):
    def test_official_favicon_is_packaged_without_modification(self):
        asset = finders.find("workspace/brand/nabio-elege-icon.png")
        self.assertIsNotNone(asset)
        content = Path(asset).read_bytes()
        self.assertEqual(content[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(content[16:20], "big"), 3375)
        self.assertEqual(int.from_bytes(content[20:24], "big"), 3375)
        self.assertEqual(
            hashlib.sha256(content).hexdigest(),
            "1268ccee4c18972aa6ad70dd57ef81aff9066436683e377ba44a959aff1faabc",
        )

    def test_all_page_shells_declare_the_official_favicon_in_head(self):
        fragment = render_to_string("workspace/brand_icons.html").strip()
        self.assertIn('rel="icon"', fragment)
        self.assertIn('type="image/png"', fragment)
        self.assertIn('sizes="3375x3375"', fragment)
        self.assertIn("workspace/brand/nabio-elege-icon.png", fragment)
        for name in ("landing", "auth_base", "base", "public_form"):
            with self.subTest(template=name):
                html = render_to_string(f"workspace/{name}.html", {"unavailable": True})
                head = html.split("<head>", 1)[1].split("</head>", 1)[0]
                self.assertIn(fragment, head)
                self.assertEqual(html.count('rel="icon"'), 1)

    def test_official_artwork_is_packaged_without_modification(self):
        asset = finders.find("workspace/brand/nabio-elege.png")
        self.assertIsNotNone(asset)
        content = Path(asset).read_bytes()
        self.assertEqual(content[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(content[16:20], "big"), 6000)
        self.assertEqual(int.from_bytes(content[20:24], "big"), 3375)
        self.assertEqual(
            hashlib.sha256(content).hexdigest(),
            "3c5e0ec3a85f7c344889cf5aefd4343c1a9f96c7bc46d4841b67033e609f7768",
        )

    def test_colored_and_white_variants_use_the_same_accessible_image(self):
        for white in (False, True):
            with self.subTest(white=white):
                html = render_to_string("workspace/brand_logo.html", {"white": white})
                self.assertIn("workspace/brand/nabio-elege.png", html)
                self.assertIn('alt="Nabio Elege — Gestão inteligente', html)
                self.assertEqual("brand-logo--white" in html, white)
                self.assertNotIn("brand-logo--mark", html)

    def test_decorative_symbol_does_not_duplicate_the_accessible_name(self):
        html = render_to_string(
            "workspace/brand_logo.html",
            {"white": True, "mark": True, "decorative": True},
        )
        self.assertIn('aria-hidden="true"', html)
        self.assertIn('alt=""', html)
        self.assertIn("brand-logo--mark", html)
        self.assertIn("brand-logo--white", html)

    def test_public_surfaces_share_brand_styles_and_no_placeholder_logo(self):
        for name in ("landing", "auth_base", "public_form"):
            with self.subTest(template=name):
                html = render_to_string(f"workspace/{name}.html", {"unavailable": True})
                self.assertIn("workspace/brand.css", html)
                self.assertIn("workspace/brand/nabio-elege.png", html)
                self.assertNotIn("brand-symbol", html)
                self.assertNotIn("product-symbol", html)
                self.assertLess(
                    html.index("workspace/brand.css"), html.index("</head>")
                )
                self.assertEqual("brand-logo--white" in html, name != "public_form")

    def test_workspace_navigation_uses_white_only_on_the_dark_sidebar(self):
        campaign = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            name="Campanha sintética",
            phase="operation",
            tenant=SimpleNamespace(name="Organização sintética"),
        )
        for context in ({}, {"campaign": campaign}):
            with self.subTest(campaign=bool(context)):
                html = render_to_string("workspace/base.html", context)
                self.assertIn("workspace/brand/nabio-elege.png", html)
                self.assertIn("workspace/brand.css", html)
                self.assertEqual("brand-logo--white" in html, bool(context))
                self.assertNotIn("brand-symbol", html)

    def test_brand_tokens_and_small_text_color_pairs_have_aa_contrast(self):
        css = Path(finders.find("workspace/brand.css")).read_text(encoding="utf-8")
        tokens = dict(re.findall(r"--(brand-[\w-]+):\s*(#[\da-f]{6});", css))
        self.assertEqual(tokens["brand-primary"], "#117444")
        self.assertEqual(tokens["brand-accent"], "#42b04a")
        self.assertIn("filter: brightness(0) invert(1)", css)

        def luminance(color):
            channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [
                c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                for c in channels
            ]
            return sum(
                c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722))
            )

        for foreground, background in (
            ("#ffffff", tokens["brand-primary"]),
            ("#052e1b", tokens["brand-accent"]),
            (tokens["brand-primary"], "#ffffff"),
            (tokens["brand-muted"], tokens["brand-soft"]),
            (tokens["brand-on-dark"], tokens["brand-deep"]),
        ):
            with self.subTest(foreground=foreground, background=background):
                lighter, darker = sorted(
                    (luminance(foreground), luminance(background)), reverse=True
                )
                self.assertGreaterEqual((lighter + 0.05) / (darker + 0.05), 4.5)
