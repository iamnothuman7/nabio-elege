from types import SimpleNamespace
from uuid import UUID

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils.text import slugify

from .navigation_icons import ALIASES, PATHS
from .registry import MODULES


class SidebarTests(SimpleTestCase):
    def context(self):
        campaign = SimpleNamespace(
            id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            name="Synthetic",
            tenant=SimpleNamespace(name="Synthetic"),
        )
        navigation = [
            {"name": group, "modules": [m for m in MODULES if m.group == group]}
            for group in dict.fromkeys(m.group for m in MODULES)
        ]
        return {
            "campaign": campaign,
            "user": SimpleNamespace(pk=123),
            "active": "tarefas",
            "navigation": navigation,
            "map_access": True,
        }

    def test_all_modules_and_groups_have_named_local_icons(self):
        for key in [m.key for m in MODULES] + [slugify(m.group) for m in MODULES]:
            self.assertIn(key, ALIASES)
            self.assertIn(ALIASES[key], PATHS)

    def test_active_page_accessible_names_and_real_brand_symbol(self):
        html = render_to_string("workspace/sidebar.html", self.context())
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn('aria-label="Tarefas"', html)
        self.assertIn("workspace/brand/nabio-elege-icon.png", html)
        self.assertIn(
            'data-sidebar-scope="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb:123"', html
        )
        self.assertIn('aria-hidden="true"', html)

    def test_restricted_navigation_does_not_reintroduce_hidden_links(self):
        context = self.context()
        context.update(navigation=[], map_access=False)
        html = render_to_string("workspace/sidebar.html", context)
        for label in [
            "Mapa da campanha",
            "Equipe e acessos",
            "Relatórios",
            "Auditoria",
            "Tarefas",
        ]:
            self.assertNotIn(label, html)

    def test_shared_shell_restoration_script_and_keyboard_target(self):
        html = render_to_string("workspace/base.html", self.context())
        self.assertIn("workspace/sidebar.js", html)
        self.assertIn("workspace/sidebar.css", html)
        self.assertIn('<main id="main" tabindex="-1">', html)
