import json
import uuid
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from .address_lookup import (
    BASE,
    MAX_BYTES,
    AddressUnavailable,
    NoAddressRedirect,
    lookup_address,
    query_path,
)
from .models import Territory


SOURCE = {
    "cep": "01001-000",
    "logradouro": "Praça da Sé",
    "bairro": "Sé",
    "localidade": "São Paulo",
    "uf": "SP",
    "ibge": "3550308",
    "discard": "not exposed",
}


class PostalProviderTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def response(self, body):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = BASE + "01001000/json/"
        response.read.return_value = json.dumps(body).encode()
        return response

    def test_exact_paths_and_unicode(self):
        self.assertEqual(query_path({"cep": " 01001-000 "}), "01001000/json/")
        self.assertEqual(
            query_path({"state": "SP", "city": "São Paulo", "street": "Praça da Sé"}),
            "SP/S%C3%A3o%20Paulo/Pra%C3%A7a%20da%20S%C3%A9/json/",
        )

    def test_invalid_queries_never_request_arbitrary_urls_or_send_extra_data(self):
        for data in [
            None,
            [],
            {"cep": 1001000},
            {"cep": "１0001000"},
            {"cep": "01001000", "person": "private"},
            {"cep": "https://localhost"},
            {"state": "XX", "city": "City", "street": "Street"},
            {"state": "SP", "city": "AB", "street": "Street"},
            {"state": "SP", "city": "City", "street": "../../secret"},
            {"state": "SP", "city": "City", "street": "x" * 101},
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                query_path(data)

    def test_whitelisted_data_is_cached_without_private_identifiers(self):
        with patch(
            "apps.workspace.address_lookup.open_address",
            return_value=self.response(SOURCE),
        ) as request:
            first = lookup_address({"cep": "01001000"})
            self.assertEqual(first, lookup_address({"cep": "01001-000"}))
        request.assert_called_once()
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, BASE + "01001000/json/")
        self.assertIsNone(sent.data)
        self.assertEqual(first["source"], "ViaCEP")
        self.assertEqual(
            set(first["data"][0]),
            {"cep", "street", "neighborhood", "city", "state", "ibge"},
        )

    def test_not_found_and_empty_search_are_cached(self):
        for body in [{"erro": True}, {"erro": "true"}, []]:
            cache.clear()
            with patch(
                "apps.workspace.address_lookup.open_address",
                return_value=self.response(body),
            ) as request:
                self.assertEqual(lookup_address({"cep": "01001000"})["data"], [])
                lookup_address({"cep": "01001000"})
                request.assert_called_once()

    def test_malformed_or_unbounded_provider_results_fail_closed(self):
        for body in [
            "bad",
            [SOURCE] * 51,
            [None],
            {**SOURCE, "ibge": "2304400"},
            {**SOURCE, "cep": "invalid"},
            {**SOURCE, "uf": "XX"},
            {**SOURCE, "bairro": "x" * 151},
        ]:
            with (
                self.subTest(body=str(body)[:80]),
                patch(
                    "apps.workspace.address_lookup.open_address",
                    return_value=self.response(body),
                ),
                self.assertRaises(AddressUnavailable),
            ):
                lookup_address({"cep": "01001000"})

    def test_network_size_and_redirect_limits(self):
        with (
            patch(
                "apps.workspace.address_lookup.open_address",
                side_effect=URLError("private upstream error"),
            ),
            self.assertRaises(AddressUnavailable),
        ):
            lookup_address({"cep": "01001000"})
        response = self.response(SOURCE)
        response.read.return_value = b"x" * (MAX_BYTES + 1)
        with (
            patch("apps.workspace.address_lookup.open_address", return_value=response),
            self.assertRaises(AddressUnavailable),
        ):
            lookup_address({"cep": "01001000"})
        response.read.assert_called_once_with(MAX_BYTES + 1)
        response = self.response(SOURCE)
        response.geturl.return_value = "http://127.0.0.1/private"
        with (
            patch("apps.workspace.address_lookup.open_address", return_value=response),
            self.assertRaises(AddressUnavailable),
        ):
            lookup_address({"cep": "01001000"})
        with self.assertRaises(AddressUnavailable):
            NoAddressRedirect().redirect_request(
                None, None, 302, "redirect", {}, "http://127.0.0.1"
            )


class PostalAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("postal-fixture")
        cls.tenant = Tenant.objects.create(name="Synthetic", slug="postal-fixture")
        cls.campaign = Campaign.objects.create(
            tenant=cls.tenant,
            name="Synthetic campaign",
            code="postal",
            election_id="test",
            office_code="test",
            jurisdiction_code="test",
            phase="operation",
        )
        cls.other = Campaign.objects.create(
            tenant=cls.tenant,
            name="Other",
            code="other",
            election_id="test",
            office_code="test",
            jurisdiction_code="test",
            phase="operation",
        )
        cls.role = Role.objects.create(tenant=cls.tenant, code="postal", name="Postal")
        cls.role.permissions.set(
            Permission.objects.filter(
                code__in=["territories.read.campaign", "territories.manage.campaign"]
            )
        )
        Membership.objects.create(
            user=cls.user,
            tenant=cls.tenant,
            campaign=cls.campaign,
            role=cls.role,
            status="active",
        )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)
        self.url = reverse("address_lookup", args=[self.campaign.pk])

    def post(self, payload=None):
        return self.client.post(
            self.url,
            payload if payload is not None else {"cep": "01001000"},
            content_type="application/json",
        )

    def test_lookup_is_read_only_and_authenticated_post(self):
        self.assertEqual(Client().post(self.url).status_code, 302)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        with patch(
            "apps.workspace.address_lookup.lookup_address",
            return_value={"source": "ViaCEP", "data": []},
        ) as lookup:
            self.assertEqual(self.post().status_code, 200)
            lookup.assert_called_once_with({"cep": "01001000"})
        self.assertFalse(Territory.objects.exists())

    def test_permission_campaign_isolation_and_csrf(self):
        with patch("apps.workspace.address_lookup.lookup_address") as lookup:
            other_url = reverse("address_lookup", args=[self.other.pk])
            self.assertEqual(
                self.client.post(
                    other_url, {"cep": "01001000"}, content_type="application/json"
                ).status_code,
                404,
            )
            secure = Client(enforce_csrf_checks=True)
            secure.force_login(self.user)
            self.assertEqual(
                secure.post(
                    self.url, {"cep": "01001000"}, content_type="application/json"
                ).status_code,
                403,
            )
            self.role.permissions.remove(
                Permission.objects.get(code="territories.manage.campaign")
            )
            self.assertEqual(self.post().status_code, 403)
            lookup.assert_not_called()

    def test_invalid_queries_and_oversized_body_are_rejected(self):
        with patch("apps.workspace.address_lookup.lookup_address") as lookup:
            for payload in [
                {"cep": "bad"},
                {"cep": "01001000", "user": "private"},
                {"cep": "x" * 2100},
                [],
            ]:
                self.assertEqual(self.post(payload).status_code, 400)
            self.assertEqual(
                self.client.post(
                    self.url, "{", content_type="application/json"
                ).status_code,
                400,
            )
            lookup.assert_not_called()

    def test_provider_failure_preserves_manual_entry_and_redacts_diagnostics(self):
        for error in [
            AddressUnavailable("private diagnostic"),
            RuntimeError("private diagnostic"),
        ]:
            with patch(
                "apps.workspace.address_lookup.lookup_address", side_effect=error
            ):
                response = self.post()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private diagnostic", response.content.decode())
                self.assertIn("manualmente", response.json()["detail"])

    def test_per_user_and_global_limits(self):
        with patch(
            "apps.workspace.address_lookup.lookup_address",
            return_value={"source": "ViaCEP", "data": []},
        ) as lookup:
            for _ in range(20):
                self.assertEqual(self.post().status_code, 200)
            response = self.post()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response["Retry-After"], "60")
            self.assertEqual(lookup.call_count, 20)
        from django.utils import timezone

        cache.clear()
        minute = int(timezone.now().timestamp()) // 60
        cache.set(f"postal-global:{minute}", 120, 90)
        with patch("apps.workspace.address_lookup.lookup_address") as lookup:
            self.assertEqual(self.post().status_code, 429)
            lookup.assert_not_called()

    def test_territory_form_manual_save_without_api_or_boundary(self):
        url = reverse("module_create", args=[self.campaign.pk, "territorios"])
        response = self.client.get(url)
        self.assertContains(response, "Localize o território")
        self.assertContains(response, "Não sei o CEP")
        self.assertNotContains(response, 'name="lookup-cep"')
        with patch("apps.workspace.address_lookup.lookup_address") as lookup:
            response = self.client.post(
                url,
                {
                    "name": "Centro",
                    "area_kind": "neighborhood",
                    "municipality": "Fortaleza",
                    "state": "CE",
                    "command_id": str(uuid.uuid4()),
                },
            )
            self.assertEqual(response.status_code, 302, response.content[:500])
            lookup.assert_not_called()
        area = Territory.objects.get(campaign=self.campaign)
        self.assertEqual(area.name, "Centro")
        self.assertFalse(area.boundary)

    def test_prefill_does_not_save_and_invalid_location_is_ignored(self):
        url = reverse("module_create", args=[self.campaign.pk, "territorios"])
        response = self.client.get(
            url, {"uf": "CE", "ibge": "2304400", "municipio": "Fortaleza"}
        )
        self.assertEqual(response.context["form"].initial["municipality"], "Fortaleza")
        response = self.client.get(
            url, {"uf": "CE", "ibge": "3550308", "municipio": "São Paulo"}
        )
        self.assertNotIn("municipality", response.context["form"].initial)
        self.assertFalse(Territory.objects.exists())

    def test_map_explains_selection_and_optional_advanced_controls(self):
        response = self.client.get(reverse("campaign_map", args=[self.campaign.pk]))
        for text in [
            "1. Estado / DF",
            "2. Município",
            "Selecionar uma cidade não cria um cadastro",
            "Mais opções do mapa",
            "Cadastrar território nesta cidade",
            "Desenhar um contorno no mapa · opcional",
        ]:
            self.assertContains(response, text)
