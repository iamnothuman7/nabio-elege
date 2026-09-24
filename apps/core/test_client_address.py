from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.workspace.middleware import AccessSecurityMiddleware
from apps.workspace.models import SecurityProfile
from .checks import production_guardrails
from .client_address import canonical_ip, client_address


class ClientAddressTests(SimpleTestCase):
    def request(self, peer="192.0.2.10", **headers):
        return RequestFactory().get("/", REMOTE_ADDR=peer, **headers)

    @override_settings(TRUSTED_PROXY_IPS=[])
    def test_no_implicit_trust_in_loopback_or_forwarded_chains(self):
        for peer in ["127.0.0.1", "192.0.2.10"]:
            self.assertEqual(
                client_address(
                    self.request(
                        peer,
                        HTTP_X_REAL_IP="198.51.100.5",
                        HTTP_X_FORWARDED_FOR="198.51.100.6",
                    )
                ),
                peer,
            )

    @override_settings(TRUSTED_PROXY_IPS=["127.0.0.1", "::1"])
    def test_explicit_peer_can_supply_one_valid_address(self):
        for peer in ["127.0.0.1", "::ffff:127.0.0.1", "0:0:0:0:0:0:0:1"]:
            self.assertEqual(
                client_address(self.request(peer, HTTP_X_REAL_IP="198.51.100.5")),
                "198.51.100.5",
            )

    @override_settings(TRUSTED_PROXY_IPS=["127.0.0.1"])
    def test_untrusted_peer_cannot_choose_rate_limit_key(self):
        self.assertEqual(
            client_address(self.request(HTTP_X_REAL_IP="198.51.100.5")), "192.0.2.10"
        )

    @override_settings(TRUSTED_PROXY_IPS=["127.0.0.1"])
    def test_invalid_forwarded_address_falls_back_to_peer(self):
        for value in [
            "",
            "unknown",
            "198.51.100.5, 198.51.100.6",
            "198.51.100.5:443",
            "[::1]",
            "fe80::1%eth0",
            "0.0.0.0",
            "::ffff:0.0.0.0",
            "::ffff:224.0.0.1",
            "224.0.0.1",
            "x" * 1000,
        ]:
            self.assertEqual(
                client_address(
                    self.request(
                        "127.0.0.1",
                        HTTP_X_REAL_IP=value,
                        HTTP_X_FORWARDED_FOR="198.51.100.7",
                    )
                ),
                "127.0.0.1",
            )

    @override_settings(TRUSTED_PROXY_IPS=["127.0.0.1"])
    def test_missing_or_invalid_peer_cannot_delegate_trust(self):
        for value in ["", "unknown", "host:443"]:
            self.assertEqual(
                client_address(self.request(value, HTTP_X_REAL_IP="198.51.100.5")),
                "unknown",
            )

    def test_ipv6_is_canonical_and_mapped_ipv4_shares_same_bucket(self):
        self.assertEqual(
            canonical_ip("2001:0db8:0000:0000:0000:0000:0000:0001"), "2001:db8::1"
        )
        self.assertEqual(canonical_ip("::ffff:192.0.2.10"), "192.0.2.10")

    def test_wildcard_or_network_configuration_never_grants_trust(self):
        for values in [["*"], ["0.0.0.0/0"], ["127.0.0.0/8"], "127.0.0.1"]:
            with override_settings(TRUSTED_PROXY_IPS=values):
                self.assertEqual(
                    client_address(
                        self.request("127.0.0.1", HTTP_X_REAL_IP="198.51.100.5")
                    ),
                    "127.0.0.1",
                )

    @override_settings(APP_ENV="production", TRUST_PROXY_HEADERS=True)
    def test_deployment_rejects_missing_or_invalid_explicit_proxies(self):
        for values in [[], ["*"], ["0.0.0.0/0"], ["invalid"], "127.0.0.1"]:
            with override_settings(TRUSTED_PROXY_IPS=values):
                self.assertIn(
                    "nabio.E014", {error.id for error in production_guardrails(None)}
                )
        with override_settings(TRUSTED_PROXY_IPS=["127.0.0.1", "::1"]):
            self.assertNotIn(
                "nabio.E014", {error.id for error in production_guardrails(None)}
            )

    @override_settings(TRUSTED_PROXY_IPS=["127.0.0.1"])
    def test_public_form_limits_are_per_visitor_with_security_headers(self):
        cache.clear()
        middleware = AccessSecurityMiddleware(lambda request: HttpResponse("accepted"))

        def send(address):
            request = RequestFactory().post(
                "/f/test-only/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP=address
            )
            request.user = AnonymousUser()
            return middleware(request)

        with patch("apps.workspace.middleware.time.time", return_value=120):
            for _ in range(30):
                self.assertEqual(send("198.51.100.5").status_code, 200)
            blocked = send("198.51.100.5")
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked["Retry-After"], "60")
            self.assertEqual(blocked["Cache-Control"], "no-store")
            self.assertIn("frame-ancestors 'none'", blocked["Content-Security-Policy"])
            self.assertEqual(send("198.51.100.6").status_code, 200)


@override_settings(TRUSTED_PROXY_IPS=["127.0.0.1"])
class ProxiedLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "proxied-operator", password="Synthetic-Login-2026!"
        )

    def submit(self, username, password, address):
        return self.client.post(
            reverse("login"),
            {"username": username, "password": password},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_REAL_IP=address,
        )

    def test_one_visitor_does_not_lock_every_visitor_behind_proxy(self):
        for _ in range(5):
            self.submit("unknown-account", "wrong", "198.51.100.5")
        blocked = self.submit(
            "proxied-operator", "Synthetic-Login-2026!", "198.51.100.5"
        )
        self.assertContains(blocked, "Não foi possível entrar")
        allowed = self.submit(
            "proxied-operator", "Synthetic-Login-2026!", "198.51.100.6"
        )
        self.assertEqual(allowed.status_code, 302)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertEqual(allowed["Cache-Control"], "no-store")

    def test_account_limit_cannot_be_evaded_by_rotating_client_address(self):
        for index in range(5):
            self.submit("proxied-operator", "wrong", f"198.51.100.{index + 1}")
        self.assertContains(
            self.submit("proxied-operator", "Synthetic-Login-2026!", "198.51.100.99"),
            "Não foi possível entrar",
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_security_redirects_are_not_cacheable(self):
        SecurityProfile.objects.create(user=self.user, password_change_required=True)
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(
            response["Permissions-Policy"], "camera=(), microphone=(), geolocation=()"
        )
