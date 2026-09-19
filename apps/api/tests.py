from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.campaigns.models import Campaign, Membership, Role, Tenant


class CampaignApiIsolationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("api-user", password="test-only")
        tenant_a = Tenant.objects.create(name="Organização A", slug="api-org-a")
        tenant_b = Tenant.objects.create(name="Organização B", slug="api-org-b")
        self.campaign_a = Campaign.objects.create(
            tenant=tenant_a,
            code="a",
            name="Campanha A",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        self.campaign_b = Campaign.objects.create(
            tenant=tenant_b,
            code="b",
            name="Campanha B",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        role = Role.objects.create(tenant=tenant_a, code="reader", name="Leitor")
        Membership.objects.create(
            user=self.user,
            tenant=tenant_a,
            campaign=self.campaign_a,
            role=role,
            status=Membership.Status.ACTIVE,
        )
        self.client.force_login(self.user)

    def test_campaign_list_excludes_other_tenants(self):
        response = self.client.get("/api/v1/campaigns")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], str(self.campaign_a.id))

    def test_cross_campaign_detail_returns_not_found(self):
        response = self.client.get(f"/api/v1/campaigns/{self.campaign_b.id}")
        self.assertEqual(response.status_code, 404)

    def test_health_check_is_public(self):
        self.client.logout()
        response = self.client.get("/api/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "ok"})
