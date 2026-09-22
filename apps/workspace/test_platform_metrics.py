from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from apps.core.rls import DatabaseScope
from .platform_metrics import (
    PREFIX,
    RETENTION,
    counter_key,
    record_page_view,
    usage_snapshot,
)


class OperationalMetricsTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def request(self, path="/produto/", name="product_landing", **headers):
        request = self.factory.get(path, **headers)
        request.user = AnonymousUser()
        request.resolver_match = SimpleNamespace(url_name=name)
        return request

    def test_anonymous_landing_counts_without_identity_or_query_string(self):
        request = self.request(
            "/produto/?private=never-store-this",
            REMOTE_ADDR="192.0.2.9",
            HTTP_USER_AGENT="private-agent",
        )
        with patch(
            "apps.workspace.platform_metrics.cache.add", wraps=cache.add
        ) as added:
            record_page_view(request, HttpResponse("public"))
        calls = repr(added.call_args_list)
        for private in ("never-store-this", "192.0.2.9", "private-agent"):
            self.assertNotIn(private, calls)
        self.assertIn(str(RETENTION), calls)
        self.assertEqual(usage_snapshot(7, [])["landing"], 1)

    def test_ignore_head_errors_private_forms_api_and_privacy_preferences(self):
        request = self.request()
        for status in (302, 403, 404, 500):
            record_page_view(request, HttpResponse(status=status))
        record_page_view(request, HttpResponse("{}", content_type="application/json"))
        record_page_view(request, StreamingHttpResponse(iter([b"public"])))
        request.method = "HEAD"
        record_page_view(request, HttpResponse())
        for header in ("HTTP_DNT", "HTTP_SEC_GPC"):
            record_page_view(self.request(**{header: "1"}), HttpResponse())
        record_page_view(
            self.request(HTTP_SEC_PURPOSE="prefetch;prerender"), HttpResponse()
        )
        record_page_view(
            self.request("/f/private-code/", name="public_form"), HttpResponse()
        )
        self.assertEqual(usage_snapshot(7, [])["landing"], 0)

    def test_customer_usage_uses_authorized_scope_not_url_or_headers(self):
        tenant = SimpleNamespace(pk=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
        scope = DatabaseScope(
            tenant_id=str(tenant.pk), campaign_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        )
        request = self.request(
            "/c/not-used-as-identity/", name="dashboard", HTTP_X_TENANT_ID="attacker"
        )
        request.user = SimpleNamespace(
            is_authenticated=True, is_staff=False, is_superuser=False
        )
        with patch("apps.workspace.platform_metrics.current_scope", return_value=scope):
            record_page_view(request, HttpResponse())
        data = usage_snapshot(7, [tenant])
        self.assertEqual(data["workspace"], 1)
        self.assertEqual(data["tenants"][0]["views"], 1)
        with patch(
            "apps.workspace.platform_metrics.current_scope",
            return_value=DatabaseScope(),
        ):
            record_page_view(request, HttpResponse())
        request.user.is_superuser = True
        with patch("apps.workspace.platform_metrics.current_scope", return_value=scope):
            record_page_view(request, HttpResponse())
        self.assertEqual(usage_snapshot(7, [tenant])["workspace"], 1)

    def test_rolling_window_and_empty_state_are_explicit(self):
        day = timezone.localdate()
        cache.set(counter_key(day, "landing"), 3)
        cache.set(counter_key(day - timedelta(days=10), "landing"), 4)
        cache.set(counter_key(day - timedelta(days=31), "landing"), 8)
        self.assertEqual(usage_snapshot(7, [])["landing"], 3)
        self.assertEqual(usage_snapshot(30, [])["landing"], 7)
        self.assertEqual(len(usage_snapshot(30, [])["rows"]), 30)
        self.assertIsNone(usage_snapshot(7, [])["started"])

    def test_cache_failure_never_breaks_a_page_or_claims_zero(self):
        with patch(
            "apps.workspace.platform_metrics.cache.add", side_effect=ConnectionError
        ):
            with self.assertLogs(
                "apps.workspace.platform_metrics", level="WARNING"
            ) as captured:
                record_page_view(self.request(), HttpResponse())
            self.assertEqual(len(captured.output), 1)
        with patch(
            "apps.workspace.platform_metrics.cache.get_many",
            side_effect=ConnectionError,
        ):
            self.assertEqual(usage_snapshot(7, []), {"available": False, "days": 7})


class MetricsMiddlewareTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_successful_landing_gets_counted_but_head_and_help_do_not(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/produto/").status_code, 200)
        self.assertEqual(self.client.head("/produto/").status_code, 200)
        self.assertEqual(self.client.get("/ajuda-acesso/").status_code, 200)
        self.assertEqual(usage_snapshot(7, [])["landing"], 2)
        self.assertIsNotNone(cache.get(PREFIX + "started"))
