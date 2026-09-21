from pathlib import Path

from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class InterfaceTests(SimpleTestCase):
    def test_login_uses_compact_layout_without_clipping_form(self):
        html = render_to_string("workspace/login.html")
        self.assertIn('class="auth-body login-page"', html)
        self.assertIn("auth-story-center", html)
        self.assertIn("workspace/interface.css", html)
        self.assertIn('autocomplete="current-password"', html)
        css = Path(finders.find("workspace/interface.css")).read_text(encoding="utf-8")
        self.assertIn("100svh", css)
        self.assertNotIn("overflow: hidden", css)
        self.assertIn("prefers-reduced-transparency", css)

    def test_landing_motion_has_pause_accessible_heading_and_no_new_dependency(self):
        html = render_to_string("workspace/landing.html")
        self.assertIn('class="type-title">Clareza na gestão.</em>', html)
        self.assertIn(
            'class="motion-toggle" type="button" aria-pressed="false" hidden', html
        )
        self.assertIn("workspace/product-motion.css", html)
        self.assertEqual(html.count('class="ribbon-group"'), 1)
        css = Path(finders.find("workspace/product-motion.css")).read_text(
            encoding="utf-8"
        )
        js = Path(finders.find("workspace/product.js")).read_text(encoding="utf-8")
        for feature in (
            "prefers-reduced-motion",
            "motion-paused",
            "animation-play-state",
            "backdrop-filter",
        ):
            self.assertIn(feature, css)
        self.assertIn("setAttribute('aria-hidden', 'true')", js)
        self.assertIn("visibilitychange", js)
        self.assertIn("IntersectionObserver", js)
        self.assertNotIn("setInterval", js)

    def test_shared_workspace_and_auth_shell_use_refined_surfaces(self):
        for template in ("base", "auth_base"):
            html = render_to_string(f"workspace/{template}.html")
            self.assertIn("workspace/interface.css", html.split("</head>")[0])
