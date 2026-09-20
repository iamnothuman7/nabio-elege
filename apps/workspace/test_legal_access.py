import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.models import Document
from apps.core.services import append_audit_event
from .document_services import require_document_access
from .legal_access import (
    change_case_access,
    initialize_case_access,
    restrict_queryset,
    visible_cases,
)
from .models import LegalCase, LegalCaseAccess, Occurrence
from .registry import REGISTRY
from .services import execute_action
from .ui_forms import model_form_class


class LegalCaseAccessTests(TestCase):
    def test_migration_backfill_is_limited_to_author_and_responsible(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace

        legacy = LegalCase.objects.create(
            **self.scope,
            title="Caso legado",
            case_type="Consulta",
            responsible=self.members[self.reviewer.pk],
        )
        migration = importlib.import_module(
            "apps.workspace.migrations.0007_legalcaseaccess"
        )
        editor = SimpleNamespace(connection=connection)
        migration.seed_existing_case_access(apps, editor)
        migration.seed_existing_case_access(apps, editor)
        self.assertEqual(legacy.access_grants.count(), 2)
        self.assertTrue(
            legacy.access_grants.filter(
                membership=self.members[self.owner.pk], can_manage_access=True
            ).exists()
        )
        self.assertFalse(
            legacy.access_grants.filter(
                membership=self.members[self.outsider.pk]
            ).exists()
        )

    def test_ui_self_revocation_returns_to_list(self):
        self.grant(can_manage=True)
        self.case.refresh_from_db()
        response = self.client.post(
            reverse("case_access", args=[self.campaign.pk, self.case.pk]),
            {
                "action": "revoke",
                "membership": str(self.members[self.owner.pk].pk),
                "row_version": self.case.row_version,
                "reason": "Transferência de responsabilidade",
            },
        )
        self.assertRedirects(
            response, reverse("module_list", args=[self.campaign.pk, "juridico"])
        )

    def setUp(self):
        self.owner = User.objects.create_user("case-owner")
        self.reviewer = User.objects.create_user("case-reviewer")
        self.outsider = User.objects.create_user("campaign-user")
        self.tenant = Tenant.objects.create(name="Teste", slug="legal-access")
        self.campaign = Campaign.objects.create(
            tenant=self.tenant,
            code="legal",
            name="Campanha",
            election_id="test",
            office_code="test",
            jurisdiction_code="test",
        )
        role = Role.objects.create(tenant=self.tenant, code="legal", name="Jurídico")
        role.permissions.set(Permission.objects.all())
        self.members = {
            u.pk: Membership.objects.create(
                user=u,
                tenant=self.tenant,
                campaign=self.campaign,
                role=role,
                status="active",
            )
            for u in [self.owner, self.reviewer, self.outsider]
        }
        self.scope = {
            "tenant": self.tenant,
            "campaign": self.campaign,
            "created_by": self.owner,
        }
        self.document = Document.objects.create(
            **self.scope,
            display_name="Documento confidencial fictício",
            classification="legal",
            status="available",
        )
        self.case = LegalCase.objects.create(
            **self.scope,
            title="Caso reservado fictício",
            case_type="Consulta",
            restricted_document=self.document,
        )
        initialize_case_access(self.case, self.owner)
        self.client.force_login(self.owner)

    def grant(self, user=None, revoke=False, can_manage=False, **overrides):
        self.case.refresh_from_db()
        return change_case_access(
            actor=self.owner,
            campaign=self.campaign,
            case_id=self.case.pk,
            membership_id=self.members[(user or self.reviewer).pk].pk,
            can_manage=can_manage,
            revoke=revoke,
            version=self.case.row_version,
            reason="Conferência de acesso sintético",
            **overrides,
        )

    def test_campaign_permission_does_not_grant_all_cases(self):
        self.assertTrue(
            visible_cases(self.owner, self.campaign).filter(pk=self.case.pk).exists()
        )
        self.assertFalse(visible_cases(self.outsider, self.campaign).exists())
        self.client.force_login(self.outsider)
        self.assertNotContains(
            self.client.get(
                reverse("module_list", args=[self.campaign.pk, "juridico"])
            ),
            self.case.title,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "module_detail", args=[self.campaign.pk, "juridico", self.case.pk]
                )
            ).status_code,
            404,
        )

    def test_grant_and_revoke_are_immediately_effective(self):
        self.grant()
        self.assertTrue(visible_cases(self.reviewer, self.campaign).exists())
        self.grant(revoke=True)
        self.assertFalse(visible_cases(self.reviewer, self.campaign).exists())
        with self.assertRaises(PermissionDenied):
            require_document_access(self.reviewer, self.document)

    def test_expired_or_revoked_campaign_membership_cannot_use_case_grant(self):
        self.grant()
        member = self.members[self.reviewer.pk]
        member.expires_at = timezone.now() - timedelta(seconds=1)
        member.save()
        self.assertFalse(visible_cases(self.reviewer, self.campaign).exists())
        member.expires_at = None
        member.revoke()
        self.assertFalse(visible_cases(self.reviewer, self.campaign).exists())

    def test_document_list_detail_and_picker_hide_restricted_case_document(self):
        self.client.force_login(self.outsider)
        self.assertNotContains(
            self.client.get(
                reverse("module_list", args=[self.campaign.pk, "documentos"])
            ),
            self.document.display_name,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "module_detail",
                    args=[self.campaign.pk, "documentos", self.document.pk],
                )
            ).status_code,
            404,
        )
        form = model_form_class(REGISTRY["juridico"])(
            campaign=self.campaign, actor=self.outsider
        )
        self.assertFalse(
            form.fields["restricted_document"]
            .queryset.filter(pk=self.document.pk)
            .exists()
        )
        with self.assertRaises(PermissionDenied):
            require_document_access(self.outsider, self.document)

    def test_shared_document_requires_access_to_every_case(self):
        self.grant()
        require_document_access(self.reviewer, self.document)
        other = LegalCase.objects.create(
            **self.scope,
            title="Outro caso",
            case_type="Consulta",
            restricted_document=self.document,
        )
        initialize_case_access(other, self.owner)
        with self.assertRaises(PermissionDenied):
            require_document_access(self.reviewer, self.document)
        require_document_access(self.owner, self.document)

    def test_occurrence_and_case_picker_do_not_leak_case(self):
        occurrence = Occurrence.objects.create(
            **self.scope,
            title="Relato reservado",
            location="Fictício",
            legal_case=self.case,
        )
        self.assertFalse(
            restrict_queryset(Occurrence.objects.all(), self.outsider, self.campaign)
            .filter(pk=occurrence.pk)
            .exists()
        )
        form = model_form_class(REGISTRY["ocorrencias"])(
            campaign=self.campaign, actor=self.outsider
        )
        self.assertFalse(form.fields["legal_case"].queryset.exists())

    def test_audit_does_not_leak_restricted_case_reason(self):
        append_audit_event(
            actor=self.owner,
            tenant=self.tenant,
            campaign=self.campaign,
            action="legal.test",
            resource_type="workspace.legalcase",
            resource_id=self.case.pk,
            reason="Marcador restrito de teste",
        )
        self.client.force_login(self.outsider)
        self.assertNotContains(
            self.client.get(reverse("audit_log", args=[self.campaign.pk])),
            "Marcador restrito de teste",
        )

    def test_cross_campaign_grants_are_rejected(self):
        other = Campaign.objects.create(
            tenant=self.tenant,
            code="other",
            name="Outra",
            election_id="test",
            office_code="test",
            jurisdiction_code="test",
        )
        member = Membership.objects.create(
            user=self.reviewer,
            tenant=self.tenant,
            campaign=other,
            role=self.members[self.owner.pk].role,
            status="active",
        )
        with self.assertRaises(ValidationError):
            LegalCaseAccess.objects.create(
                **self.scope, legal_case=self.case, membership=member
            )

    def test_cannot_revoke_or_demote_only_active_access_manager(self):
        with self.assertRaises(ValidationError):
            self.grant(self.owner, revoke=True)
        with self.assertRaises(ValidationError):
            self.grant(self.owner, can_manage=False)
        self.grant(can_manage=True)
        self.grant(self.owner, revoke=True)
        self.assertFalse(visible_cases(self.owner, self.campaign).exists())

    def test_reading_case_does_not_allow_delegating_access(self):
        self.grant()
        self.client.force_login(self.reviewer)
        self.assertEqual(
            self.client.get(
                reverse("case_access", args=[self.campaign.pk, self.case.pk])
            ).status_code,
            403,
        )

    def test_domain_action_rechecks_acl_even_for_replayed_command(self):
        command = str(uuid.uuid4())
        args = dict(
            actor=self.owner,
            campaign=self.campaign,
            config=REGISTRY["juridico"],
            object_id=self.case.pk,
            action="submit",
            version=self.case.row_version,
            command_id=command,
            data={"reason": "Teste de revisão"},
        )
        execute_action(**args)
        self.grant(can_manage=True)
        self.grant(self.owner, revoke=True)
        with self.assertRaises(PermissionDenied):
            execute_action(**args)

    def test_ui_creation_grants_creator_and_renders_management(self):
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "juridico"]),
            {
                "title": "Novo caso sintético",
                "case_type": "Consulta",
                "command_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, 302)
        case = LegalCase.objects.get(title="Novo caso sintético")
        self.assertTrue(
            case.access_grants.filter(
                membership=self.members[self.owner.pk], can_manage_access=True
            ).exists()
        )
        self.assertContains(
            self.client.get(response.url), "Administrar acessos do caso"
        )
        self.assertEqual(
            self.client.get(
                reverse("case_access", args=[self.campaign.pk, case.pk])
            ).status_code,
            200,
        )

    def test_stale_access_form_cannot_overwrite_a_newer_grant(self):
        old = self.case.row_version
        self.grant()
        with self.assertRaises(ValidationError):
            change_case_access(
                actor=self.owner,
                campaign=self.campaign,
                case_id=self.case.pk,
                membership_id=self.members[self.outsider.pk].pk,
                can_manage=False,
                revoke=False,
                version=old,
                reason="Teste desatualizado",
            )

    def test_suspended_tenant_removes_visibility(self):
        self.tenant.status = "suspended"
        self.tenant.save()
        self.assertFalse(visible_cases(self.owner, self.campaign).exists())
