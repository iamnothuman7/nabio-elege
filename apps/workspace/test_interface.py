from pathlib import Path

from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase


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

    def test_landing_motion_continuous_without_visible_pause_control(self):
        html = render_to_string("workspace/landing.html")
        self.assertIn('class="type-title">Clareza na gestão.</em>', html)
        self.assertNotIn('class="motion-toggle"', html)
        self.assertNotIn("Pausar animações", html)
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

    def test_brazil_map_has_27_local_shapes_and_accessible_controls(self):
        from html.parser import HTMLParser

        class MapParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.states = []
                self.options = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "path" and attrs.get("class") == "brazil-state":
                    self.states.append(attrs)
                if tag == "option" and attrs.get("value"):
                    self.options.append(attrs["value"])

        html = render_to_string("workspace/landing_brazil.html")
        parser = MapParser()
        parser.feed(html)
        self.assertEqual(len(parser.states), 27)
        self.assertEqual(len({p["data-uf"] for p in parser.states}), 27)
        self.assertEqual(len({p["data-region-id"] for p in parser.states}), 5)
        self.assertEqual(set(parser.options), {p["data-uf"] for p in parser.states})
        self.assertIn('aria-live="polite"', html)
        self.assertIn("IBGE", html)
        self.assertIn("relevo 3D ilustrativo", html)
        self.assertIn("<noscript>", html)
        for state in parser.states:
            self.assertTrue(state["d"].startswith("M"))
            self.assertTrue(state["d"].endswith("Z"))
        js = Path(finders.find("workspace/brazil-map.js")).read_text(encoding="utf-8")
        for feature in (
            "pointercancel",
            "lostpointercapture",
            "ArrowRight",
            "prefers-reduced-motion",
        ):
            self.assertIn(feature, js)
        self.assertNotIn("fetch(", js)

    def test_brazil_state_highlight_uses_shape_lift_not_rectangular_focus(self):
        css = Path(finders.find("workspace/brazil-map.css")).read_text(encoding="utf-8")
        self.assertIn(
            "#brazil-surfaces .brazil-state:focus-visible { outline: none; box-shadow: none; -webkit-tap-highlight-color: transparent; }",
            css,
        )
        self.assertIn(
            ".brazil-ready #brazil-surfaces .brazil-state:hover,\n"
            "#brazil-surfaces .brazil-state.is-selected,\n"
            "#brazil-surfaces .brazil-state:focus-visible { fill: #b8f1c9; transform: translateY(-8px); filter: drop-shadow(0 8px 0 #07522f); }",
            css,
        )
        self.assertIn(
            "#brazil-surfaces .brazil-state:focus-visible { stroke: #fff; stroke-width: 3; }",
            css,
        )
        self.assertIn(
            ".brazil-explorer :focus-visible { outline: 3px solid #d4eddb; outline-offset: 3px; }",
            css,
        )
        self.assertIn(
            "#brazil-surfaces .brazil-state:focus-visible { transform: none; filter: none; }",
            css,
        )
        js = Path(finders.find("workspace/brazil-map.js")).read_text(encoding="utf-8")
        self.assertNotIn(".blur(", js)
        self.assertIn("item.setAttribute('aria-pressed', String(active))", js)


class PublicSurfaceTests(TestCase):
    def test_public_pages_support_head_and_keep_security_headers(self):
        for path in ("/", "/produto/", "/entrar/", "/ajuda-acesso/"):
            with self.subTest(path=path):
                response = self.client.head(path, secure=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response["X-Frame-Options"], "DENY")
                self.assertIn("default-src 'self'", response["Content-Security-Policy"])
                self.assertEqual(response.content, b"")

    def test_landing_uses_only_local_scripts_and_secure_source_link(self):
        from html.parser import HTMLParser

        class ResourceParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.resources = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag in ("script", "img", "link"):
                    self.resources.append(attrs.get("src", attrs.get("href", "")))

        response = self.client.get("/produto/", secure=True)
        parser = ResourceParser()
        parser.feed(response.content.decode())
        self.assertTrue(parser.resources)
        self.assertTrue(all(url.startswith("/static/") for url in parser.resources))
        self.assertContains(response, "workspace/brazil-map.js")
