from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.models import RetentionPolicy
from apps.core.services import canonical_json_hash
from apps.forms.models import (
    Form,
    FormVersion,
    PrivacyNoticeVersion,
    ProcessingPurpose,
    SourceLink,
)
from apps.forms.services import publish_form_version


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


class PublicFormApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.publisher = user_model.objects.create_user("public-publisher")
        self.tenant = Tenant.objects.create(name="Organização", slug="public-org")
        self.campaign = Campaign.objects.create(
            tenant=self.tenant,
            code="campaign",
            name="Campanha",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        permission = Permission.objects.get(code="forms.publish.campaign")
        role = Role.objects.create(
            tenant=self.tenant, code="publisher", name="Publicador"
        )
        role.permissions.add(permission)
        Membership.objects.create(
            user=self.publisher,
            tenant=self.tenant,
            campaign=self.campaign,
            role=role,
            status=Membership.Status.ACTIVE,
        )
        retention = RetentionPolicy.objects.create(
            tenant=self.tenant,
            code="service",
            name="Atendimento",
            status=RetentionPolicy.Status.ACTIVE,
        )
        purpose = ProcessingPurpose.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.publisher,
            code="service",
            description="Atendimento",
            legal_basis_ref="revisão pendente",
            allowed_fields=["message"],
            retention_policy=retention,
            status=ProcessingPurpose.Status.ACTIVE,
        )
        notice = PrivacyNoticeVersion.objects.create(
            purpose=purpose,
            version=1,
            content="Aviso de privacidade para atendimento.",
            content_hash=canonical_json_hash({"version": 1}),
            status=PrivacyNoticeVersion.Status.APPROVED,
            approved_by=self.publisher,
            approved_at=timezone.now(),
        )
        form = Form.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.publisher,
            purpose=purpose,
            title="Atendimento",
            slug="service",
        )
        schema = {
            "fields": [
                {
                    "name": "message",
                    "type": "long_text",
                    "required": True,
                    "max_length": 2000,
                }
            ]
        }
        self.version = FormVersion.objects.create(
            form=form,
            version_number=1,
            schema_json=schema,
            schema_hash=canonical_json_hash(schema),
            notice_version=notice,
            status=FormVersion.Status.APPROVED,
            approved_by=self.publisher,
            approved_at=timezone.now(),
        )
        publish_form_version(
            actor=self.publisher,
            form_version_id=self.version.id,
            expected_form_row_version=form.row_version,
        )
        self.link = SourceLink.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.publisher,
            form=form,
        )

    def test_public_schema_and_submission(self):
        schema_response = self.client.get(
            f"/api/v1/public/forms/{self.link.public_code}"
        )
        self.assertEqual(schema_response.status_code, 200)
        self.assertEqual(schema_response.json()["title"], "Atendimento")

        response = self.client.post(
            f"/api/v1/public/forms/{self.link.public_code}/submissions",
            data={
                "version_id": str(self.version.id),
                "fields": {"message": "Solicitação fictícia"},
            },
            content_type="application/json",
            headers={"Idempotency-Key": "api-submission-1"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["message"], "Recebemos sua solicitação.")

    def test_public_submission_rejects_unknown_field(self):
        response = self.client.post(
            f"/api/v1/public/forms/{self.link.public_code}/submissions",
            data={
                "version_id": str(self.version.id),
                "fields": {"hidden_profile": "não permitido"},
            },
            content_type="application/json",
            headers={"Idempotency-Key": "api-submission-2"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")
