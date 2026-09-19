from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Campaign, Membership, Permission, Role, Tenant
from .services import campaigns_for_user, has_campaign_permission


class CampaignIsolationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("member", password="test-only")
        self.tenant_a = Tenant.objects.create(name="Organização A", slug="org-a")
        self.tenant_b = Tenant.objects.create(name="Organização B", slug="org-b")
        self.campaign_a = Campaign.objects.create(
            tenant=self.tenant_a,
            code="a",
            name="Campanha A",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        self.campaign_b = Campaign.objects.create(
            tenant=self.tenant_b,
            code="b",
            name="Campanha B",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        self.role_a = Role.objects.create(
            tenant=self.tenant_a, code="reader", name="Leitor"
        )
        self.permission = Permission.objects.create(
            code="test.read.campaign", resource="test", action="read"
        )
        self.role_a.permissions.add(self.permission)
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant_a,
            campaign=self.campaign_a,
            role=self.role_a,
            status=Membership.Status.ACTIVE,
        )

    def test_user_only_lists_linked_campaign(self):
        self.assertEqual(list(campaigns_for_user(self.user)), [self.campaign_a])

    def test_permission_is_scoped_to_campaign(self):
        self.assertTrue(
            has_campaign_permission(self.user, self.campaign_a, self.permission.code)
        )
        self.assertFalse(
            has_campaign_permission(self.user, self.campaign_b, self.permission.code)
        )

    def test_membership_rejects_cross_tenant_role(self):
        role_b = Role.objects.create(tenant=self.tenant_b, code="reader", name="Leitor")
        with self.assertRaises(ValidationError):
            Membership.objects.create(
                user=get_user_model().objects.create_user("other"),
                tenant=self.tenant_a,
                campaign=self.campaign_a,
                role=role_b,
                status=Membership.Status.ACTIVE,
            )
