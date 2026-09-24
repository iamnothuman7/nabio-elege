import gzip
import json
import uuid
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.models import AuditEvent
from .geo_validation import validate_boundary
from .geography import (
    BASE,
    MAX_BYTES,
    GeographyUnavailable,
    NoRedirect,
    provider_path,
    public_geography,
)
from .models import Territory


POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[-38.53, -3.73], [-38.52, -3.73], [-38.52, -3.72], [-38.53, -3.73]]
    ],
}


class BoundaryValidationTests(SimpleTestCase):
    def test_simple_polygon_and_legacy_empty_value(self):
        validate_boundary(POLYGON)
        validate_boundary({})

    def test_invalid_polygons_rejected(self):
        invalid = [
            {"type": "Point", "coordinates": [-38, -3]},
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 2], [0, 0]]]},
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [3, 3], [0, 3], [2, 0], [0, 0]]],
            },
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 1], [2, 0], [1, 1], [0, 0]]],
            },
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 0], [0, 1]]]},
            {"type": "Polygon", "coordinates": [[[0, 0], [181, 1], [2, 0], [0, 0]]]},
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [float("nan"), 1], [2, 0], [0, 0]]],
            },
            {"type": "Polygon", "coordinates": [[[0, 0], [True, 1], [2, 0], [0, 0]]]},
            {"type": "Polygon", "coordinates": [[*[[-38, -3]] * 202]]},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_boundary(value)


class GeographyProviderTests(SimpleTestCase):
    def test_map_library_is_local_and_matches_official_distribution(self):
        import base64
        import hashlib
        from pathlib import Path
        from django.contrib.staticfiles import finders
        from django.template.loader import render_to_string

        html = render_to_string("workspace/map_assets.html")
        self.assertNotIn("https://unpkg.com", html)
        for name, expected in {
            "leaflet.js": "20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
            "leaflet.css": "p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=",
        }.items():
            body = Path(finders.find("workspace/vendor/leaflet/" + name)).read_bytes()
            self.assertEqual(
                base64.b64encode(hashlib.sha256(body).digest()).decode(), expected
            )

    def setUp(self):
        cache.clear()

    def response(self, body):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = BASE + "v1/localidades/estados"
        response.read.return_value = json.dumps(body).encode()
        return response

    def test_exact_provider_paths_and_arbitrary_targets_rejected(self):
        self.assertIn("intrarregiao=UF", provider_path("limites", "BR"))
        self.assertIn("intrarregiao=municipio", provider_path("limites", "23"))
        self.assertIn("2304400/distritos", provider_path("distritos", "2304400"))
        for kind, code in [
            ("limites", "https://example.test"),
            ("municipios", "23/../../"),
            ("catalogo", "23"),
            ("unknown", "BR"),
        ]:
            with self.assertRaises(ValueError):
                provider_path(kind, code)

    def test_public_data_cached_without_campaign_or_person_identifiers(self):
        source = [
            {
                "id": 23,
                "nome": "Ceará",
                "sigla": "CE",
                "regiao": {"id": 2, "nome": "Nordeste"},
            }
        ]
        with patch(
            "apps.workspace.geography.open_geography",
            return_value=self.response(source),
        ) as request:
            first = public_geography("catalogo", "BR")
            second = public_geography("catalogo", "BR")
        self.assertEqual(first, second)
        request.assert_called_once()
        self.assertEqual(first["data"][0]["uf"], "CE")
        self.assertEqual(
            request.call_args.args[0].full_url, BASE + provider_path("catalogo", "BR")
        )

    def test_failures_size_and_redirects_are_bounded(self):
        with patch(
            "apps.workspace.geography.open_geography", side_effect=URLError("offline")
        ):
            with self.assertRaises(GeographyUnavailable):
                public_geography("catalogo", "BR")
        response = self.response([])
        response.read.return_value = b"x" * (MAX_BYTES + 1)
        with patch("apps.workspace.geography.open_geography", return_value=response):
            with self.assertRaises(GeographyUnavailable):
                public_geography("catalogo", "BR")
        response.read.assert_called_once_with(MAX_BYTES + 1)
        with self.assertRaises(GeographyUnavailable):
            NoRedirect().redirect_request(
                None, None, 302, "redirect", {}, "http://127.0.0.1/private"
            )

    def test_only_boundary_identifier_properties_returned(self):
        source = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": POLYGON,
                    "properties": {"codarea": "23", "unexpected": "discard"},
                }
            ],
        }
        with patch(
            "apps.workspace.geography.open_geography",
            return_value=self.response(source),
        ):
            result = public_geography("limites", "BR")
        self.assertEqual(result["data"]["features"][0]["properties"], {"codarea": "23"})

    def test_gzip_provider_response_is_supported(self):
        response = self.response([])
        response.read.return_value = gzip.compress(
            b'[{"id":2304400,"nome":"Fortaleza"}]'
        )
        with patch("apps.workspace.geography.open_geography", return_value=response):
            result = public_geography("municipios", "23")
        self.assertEqual(result["data"], [{"id": "2304400", "name": "Fortaleza"}])

    def test_gzip_decoded_size_is_limited(self):
        response = self.response([])
        response.read.return_value = gzip.compress(b"x" * (MAX_BYTES + 1))
        with patch("apps.workspace.geography.open_geography", return_value=response):
            with self.assertRaises(GeographyUnavailable):
                public_geography("catalogo", "BR")


class MapAreaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "map-operator", password="Synthetic-Map-2026!"
        )
        cls.tenant = Tenant.objects.create(
            name="Organização sintética", slug="map-test"
        )
        cls.campaign = Campaign.objects.create(
            tenant=cls.tenant,
            code="map-test",
            name="Campanha sintética",
            election_id="test",
            office_code="test",
            jurisdiction_code="test",
            phase="operation",
        )
        cls.other = Campaign.objects.create(
            tenant=cls.tenant,
            code="map-other",
            name="Outra campanha",
            election_id="test",
            office_code="test",
            jurisdiction_code="test",
            phase="operation",
        )
        cls.role = Role.objects.create(tenant=cls.tenant, code="map-admin", name="Mapa")
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
        self.client.force_login(self.user)
        self.url = reverse("create_map_area", args=[self.campaign.pk])
        self.payload = {
            "command_id": str(uuid.uuid4()),
            "name": "Área sintética",
            "area_kind": "community",
            "municipality": "Fortaleza",
            "state": "CE",
            "ibge_code": "2304400",
            "boundary": POLYGON,
            "source_reference": "Contorno fictício para teste",
            "public_area_confirmed": True,
        }

    def create(self, **overrides):
        return self.client.post(
            self.url, {**self.payload, **overrides}, content_type="application/json"
        )

    def test_create_retry_and_command_conflict(self):
        first = self.create()
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(self.create().json(), first.json())
        self.assertEqual(self.create(name="Outro nome").status_code, 409)
        self.assertEqual(Territory.objects.filter(campaign=self.campaign).count(), 1)
        event = AuditEvent.objects.get(action="territory.boundary_created")
        self.assertNotIn("coordinates", json.dumps(event.minimized_diff))

    def test_required_public_confirmation_source_and_polygon(self):
        for changes in (
            {"public_area_confirmed": False},
            {"source_reference": ""},
            {"boundary": {}},
            {"boundary": {"type": "Point"}},
            {"area_kind": "person"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 400)
        self.assertFalse(Territory.objects.exists())

    def test_permissions_cross_campaign_csrf_and_forged_fields(self):
        other_url = reverse("create_map_area", args=[self.other.pk])
        self.assertEqual(
            self.client.post(
                other_url, self.payload, content_type="application/json"
            ).status_code,
            404,
        )
        self.assertEqual(self.create(campaign_id=str(self.other.pk)).status_code, 400)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(
            secure.post(
                self.url, self.payload, content_type="application/json"
            ).status_code,
            403,
        )
        self.role.permissions.remove(
            Permission.objects.get(code="territories.manage.campaign")
        )
        self.assertEqual(self.create().status_code, 403)
        self.assertFalse(Territory.objects.exists())

    def test_geography_access_and_provider_failure_have_safe_responses(self):
        url = reverse("geography_layer", args=[self.campaign.pk, "catalogo", "BR"])
        self.assertEqual(Client().get(url).status_code, 302)
        with patch(
            "apps.workspace.geo_views.public_geography",
            side_effect=GeographyUnavailable("upstream private diagnostic"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 503)
            self.assertNotContains(response, "private diagnostic", status_code=503)
        with patch("apps.workspace.geo_views.public_geography", side_effect=ValueError):
            self.assertEqual(self.client.get(url).status_code, 400)

    def test_map_contains_only_current_campaign_public_areas(self):
        self.create()
        Territory.objects.create(
            tenant=self.tenant,
            campaign=self.other,
            name="Other campaign hidden",
            municipality="Fortaleza",
            state="CE",
            boundary=POLYGON,
            source_reference="Synthetic",
            public_area_confirmed=True,
        )
        response = self.client.get(reverse("campaign_map", args=[self.campaign.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Área sintética")
        self.assertNotContains(response, "Other campaign hidden")
        self.assertContains(response, "geo-region")
        self.assertNotIn("unpkg.com", response["Content-Security-Policy"])
        self.assertIn("script-src 'self';", response["Content-Security-Policy"])
