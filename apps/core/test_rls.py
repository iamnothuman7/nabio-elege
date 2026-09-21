import json
import uuid
from contextlib import contextmanager
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import AnonymousUser, User
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.forms.models import (
    Form,
    FormVersion,
    PrivacyNoticeVersion,
    ProcessingPurpose,
    SourceLink,
    Submission,
)
from apps.operations.models import Project, StockBalance, StockItem, Warehouse
from apps.workspace.models import Invitation
from .crypto import hash_token
from .models import AuditEvent, Document, DocumentVersion, RetentionPolicy
from .rls import KEYS, current_scope, database_scope, verify_database_isolation
from .rls_schema_v1 import policy_plan
from .scope_middleware import CampaignScopeMiddleware


class ScopeCoverageTests(SimpleTestCase):
    def test_all_campaign_models_have_a_policy_plan(self):
        plan = policy_plan(apps, connection)
        self.assertGreater(len(plan), 60)
        for table in (
            "forms_contactpoint",
            "core_documentversion",
            "finance_budgetline",
            "workspace_legalcaseaccess",
        ):
            self.assertIn(table, plan)
        self.assertNotIn("auth_user", plan)


@skipUnless(connection.vendor == "postgresql", "RLS exige PostgreSQL real")
class PostgreSQLIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Created transactionally inside this test class: role/grants roll back
        # with the class fixtures. Never creates a production runtime account.
        cls.runtime_role = "nabio_rls_test_" + uuid.uuid4().hex[:20]
        role_sql = connection.ops.quote_name(cls.runtime_role)
        with connection.cursor() as cursor:
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute(
                f"CREATE ROLE {role_sql} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            )
            cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role_sql}")
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role_sql}"
            )
            cursor.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role_sql}"
            )
        cls.user = User.objects.create_user("rls-operator")
        cls.other_user = User.objects.create_user("rls-other")
        cls.tenant = Tenant.objects.create(name="Organização fictícia", slug="rls-a")
        other_tenant = Tenant.objects.create(
            name="Outra organização fictícia", slug="rls-b"
        )
        cls.campaigns = []
        cls.projects = []
        cls.documents = []
        cls.items = []
        for index, tenant in enumerate((cls.tenant, cls.tenant, other_tenant)):
            campaign = Campaign.objects.create(
                tenant=tenant,
                code=f"rls-{index}",
                name=f"Campanha fictícia {index}",
                election_id="test",
                office_code="test",
                jurisdiction_code="test",
            )
            cls.campaigns.append(campaign)
            scope = {"tenant": tenant, "campaign": campaign, "created_by": cls.user}
            cls.projects.append(
                Project.objects.create(**scope, title=f"Projeto restrito {index}")
            )
            document = Document.objects.create(
                **scope,
                display_name=f"Arquivo fictício {index}",
                classification="internal",
            )
            cls.documents.append(document)
            DocumentVersion.objects.create(
                document=document,
                version_number=1,
                storage_key=f"test/{index}",
                sha256="a" * 64,
                media_type="application/pdf",
                size_bytes=4,
                uploaded_by=cls.user,
            )
            item = StockItem.objects.create(
                **scope, name=f"Item {index}", sku=f"RLS{index}", unit="un"
            )
            cls.items.append(item)
            warehouse = Warehouse.objects.create(
                **scope, name=f"Depósito {index}", code=f"rls{index}"
            )
            StockBalance.objects.create(item=item, warehouse=warehouse)
        cls.campaign = cls.campaigns[0]
        cls.role = Role.objects.create(tenant=cls.tenant, code="rls", name="Operação")
        for code in (
            "tasks.manage.campaign",
            "campaigns.read.campaign",
            "documents.read.campaign",
        ):
            resource, action, scope_name = code.split(".")
            Permission.objects.get_or_create(
                code=code,
                defaults={"resource": resource, "action": action, "scope": scope_name},
            )
        cls.role.permissions.set(Permission.objects.all())
        cls.member = Membership.objects.create(
            tenant=cls.tenant,
            campaign=cls.campaign,
            role=cls.role,
            user=cls.user,
            status="active",
        )
        scope = {"tenant": cls.tenant, "campaign": cls.campaign}
        retention = RetentionPolicy.objects.create(
            tenant=cls.tenant, code="rls", name="Teste", status="active"
        )
        purpose = ProcessingPurpose.objects.create(
            **scope,
            code="rls",
            description="Atendimento fictício",
            legal_basis_ref="Teste",
            allowed_fields=["message"],
            retention_policy=retention,
            status="active",
        )
        notice = PrivacyNoticeVersion.objects.create(
            purpose=purpose,
            version=1,
            content="Aviso fictício",
            content_hash="b" * 64,
            status="approved",
            approved_by=cls.user,
            approved_at=timezone.now(),
        )
        form = Form.objects.create(
            **scope, purpose=purpose, title="Formulário fictício", slug="rls"
        )
        cls.version = FormVersion.objects.create(
            form=form,
            version_number=1,
            schema_json={"fields": [{"name": "message", "type": "long_text"}]},
            schema_hash="c" * 64,
            notice_version=notice,
            status="published",
            approved_by=cls.user,
            approved_at=timezone.now(),
        )
        Form.objects.filter(pk=form.pk).update(
            status="published", current_version=cls.version
        )
        cls.link = SourceLink.objects.create(**scope, form=form)
        cls.invitation_token = uuid.uuid4().hex
        cls.invitation = Invitation.objects.create(
            **scope,
            username="rls-invited",
            role=cls.role,
            token_hash=hash_token(cls.invitation_token),
            expires_at=timezone.now() + timedelta(days=1),
        )

    @contextmanager
    def runtime(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                previous = cursor.fetchone()[0]
                cursor.execute(
                    "SET LOCAL ROLE " + connection.ops.quote_name(self.runtime_role)
                )
            try:
                yield
            finally:
                if not connection.needs_rollback:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SET LOCAL ROLE " + connection.ops.quote_name(previous)
                        )

    def test_runtime_role_is_restricted_and_all_policies_are_forced(self):
        self.assertFalse(verify_database_isolation())
        with self.runtime():
            self.assertTrue(verify_database_isolation())

    def test_every_scoped_table_denies_queries_without_context(self):
        with self.runtime(), connection.cursor() as cursor:
            for table in policy_plan(apps, connection):
                with self.subTest(table=table):
                    cursor.execute(
                        "SELECT count(*) FROM " + connection.ops.quote_name(table)
                    )
                    self.assertEqual(cursor.fetchone()[0], 0)

    def test_unfiltered_query_and_sql_cannot_cross_campaign_or_tenant(self):
        with self.runtime(), database_scope(campaign=self.campaign, actor=self.user):
            self.assertEqual(
                list(Project.objects.values_list("pk", flat=True)),
                [self.projects[0].pk],
            )
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM operations_project")
                self.assertEqual(str(cursor.fetchone()[0]), str(self.projects[0].pk))
            self.assertFalse(Project.objects.filter(pk=self.projects[1].pk).exists())
            self.assertFalse(Project.objects.filter(pk=self.projects[2].pk).exists())

    def test_children_and_balances_inherit_parent_scope(self):
        with self.runtime(), database_scope(campaign=self.campaign):
            self.assertEqual(
                list(DocumentVersion.objects.values_list("document_id", flat=True)),
                [self.documents[0].pk],
            )
            self.assertEqual(
                list(StockBalance.objects.values_list("item_id", flat=True)),
                [self.items[0].pk],
            )

    def test_cross_campaign_insert_and_scope_reassignment_fail_in_database(self):
        with self.runtime(), database_scope(campaign=self.campaign):
            for tenant, campaign in (
                (self.tenant, self.campaigns[1]),
                (self.campaigns[2].tenant, self.campaign),
            ):
                with (
                    self.subTest(campaign=campaign.pk),
                    self.assertRaises(DatabaseError),
                    transaction.atomic(),
                ):
                    Project.objects.bulk_create(
                        [
                            Project(
                                tenant=tenant,
                                campaign=campaign,
                                title="Tentativa inválida",
                            )
                        ]
                    )
            with self.assertRaises(DatabaseError), transaction.atomic():
                Project.objects.filter(pk=self.projects[0].pk).update(
                    campaign=self.campaigns[1]
                )
            self.assertEqual(
                Project.objects.filter(pk=self.projects[1].pk).update(
                    title="Não autorizado"
                ),
                0,
            )

    def test_child_cannot_reference_another_campaign_parent(self):
        with self.runtime(), database_scope(campaign=self.campaign):
            with self.assertRaises(DatabaseError), transaction.atomic():
                DocumentVersion.objects.bulk_create(
                    [
                        DocumentVersion(
                            document=self.documents[1],
                            version_number=2,
                            storage_key="test/forbidden",
                            sha256="d" * 64,
                            media_type="application/pdf",
                            size_bytes=4,
                            uploaded_by=self.user,
                        )
                    ]
                )

    def test_nested_scope_exception_and_connection_reuse_restore_context(self):
        with self.runtime():
            with database_scope(campaign=self.campaign):
                with self.assertRaises(RuntimeError):
                    with database_scope(campaign=self.campaigns[1]):
                        self.assertEqual(Project.objects.get().pk, self.projects[1].pk)
                        raise RuntimeError("Teste de rollback")
                self.assertEqual(Project.objects.get().pk, self.projects[0].pk)
            self.assertEqual(current_scope().campaign_id, "")
            self.assertFalse(Project.objects.exists())
            with connection.cursor() as cursor:
                for key in KEYS:
                    cursor.execute("SELECT current_setting(%s, true)", [f"nabio.{key}"])
                    self.assertIn(cursor.fetchone()[0], (None, ""))

    def test_http_scope_ignores_forged_headers_and_is_cleared(self):
        self.client.force_login(self.user)
        with self.runtime():
            response = self.client.get(
                f"/c/{self.campaign.pk}/m/projetos/",
                HTTP_X_CAMPAIGN_ID=str(self.campaigns[1].pk),
                HTTP_X_TENANT_ID=str(self.campaigns[2].tenant_id),
            )
            self.assertContains(response, "Projeto restrito 0")
            self.assertNotContains(response, "Projeto restrito 1")
            self.assertEqual(
                self.client.get(f"/c/{self.campaigns[1].pk}/m/projetos/").status_code,
                404,
            )
            self.assertFalse(Project.objects.exists())
            self.assertEqual(
                self.client.get(f"/api/v1/campaigns/{self.campaign.pk}").status_code,
                200,
            )

    def test_revoked_membership_cannot_establish_request_scope(self):
        self.client.force_login(self.user)
        self.member.revoke()
        with self.runtime():
            self.assertEqual(
                self.client.get(f"/c/{self.campaign.pk}/m/projetos/").status_code, 404
            )

    def test_public_form_accepts_only_its_published_context(self):
        with self.runtime():
            response = self.client.get(f"/api/v1/public/forms/{self.link.public_code}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["title"], "Formulário fictício")
            payload = {
                "version_id": str(self.version.pk),
                "fields": {"message": "Solicitação fictícia"},
            }
            response = self.client.post(
                f"/api/v1/public/forms/{self.link.public_code}/submissions",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )
            self.assertEqual(response.status_code, 202, response.content)
            self.assertFalse(Submission.objects.exists())
            self.assertEqual(
                self.client.get("/api/v1/public/forms/invalid-code").status_code, 404
            )

    def test_public_route_does_not_expose_other_data_before_scope_selection(self):
        with self.runtime(), database_scope(public_code=self.link.public_code):
            self.assertEqual(SourceLink.objects.count(), 1)
            self.assertFalse(Project.objects.exists())
            self.assertFalse(Form.objects.exists())
        self.link.revoked_at = timezone.now()
        self.link.save()
        with self.runtime(), database_scope(public_code=self.link.public_code):
            self.assertFalse(SourceLink.objects.exists())

    def test_invitation_routing_requires_valid_token_and_does_not_grant_other_rows(
        self,
    ):
        with (
            self.runtime(),
            database_scope(invitation_hash=hash_token(self.invitation_token)),
        ):
            self.assertEqual(Invitation.objects.count(), 1)
            self.assertFalse(Project.objects.exists())
        with self.runtime(), database_scope(invitation_hash=hash_token("invalid")):
            self.assertFalse(Invitation.objects.exists())

    def test_invitation_acceptance_works_without_bypassing_rls(self):
        with self.runtime():
            response = self.client.post(
                "/convite/",
                {
                    "token": self.invitation_token,
                    "password": "Synthetic-only-Password!2026",
                },
            )
            self.assertEqual(response.status_code, 302, response.content)
            self.assertTrue(
                Membership.objects.filter(
                    user__username="rls-invited", campaign=self.campaign
                ).exists()
            )
            self.assertFalse(Project.objects.exists())

    def test_login_and_password_change_work_under_runtime_role(self):
        self.user.set_password("Synthetic-old-Password!2026")
        self.user.save(update_fields=["password"])
        with self.runtime():
            response = self.client.post(
                "/entrar/",
                {
                    "username": self.user.username,
                    "password": "Synthetic-old-Password!2026",
                },
            )
            self.assertEqual(response.status_code, 302)
            response = self.client.post(
                "/senha/",
                {
                    "old_password": "Synthetic-old-Password!2026",
                    "new_password1": "Synthetic-new-Password!2026",
                    "new_password2": "Synthetic-new-Password!2026",
                },
            )
            self.assertEqual(response.status_code, 302, response.content)
            self.assertFalse(Project.objects.exists())

    def test_background_submission_and_outbox_keep_campaign_context(self):
        from apps.core.outbox import dispatch_outbox_event
        from apps.core.models import OutboxEvent
        from apps.forms.tasks import process_submission_task
        from apps.forms.public_services import receive_public_submission

        with self.runtime(), database_scope(campaign=self.campaign):
            receive_public_submission(
                public_code=self.link.public_code,
                version_id=self.version.pk,
                fields={"message": "Atendimento fictício"},
                idempotency_key=uuid.uuid4().hex,
            )
            submission = Submission.objects.get()
            event = OutboxEvent.objects.get(kind="submission.accepted.v1")
            with patch("apps.core.outbox.current_app.send_task") as sender:
                self.assertTrue(dispatch_outbox_event(event.pk))
                sender.assert_called_once_with(
                    "forms.process_submission",
                    args=[str(submission.pk), str(self.campaign.pk)],
                )
        with self.runtime():
            self.assertEqual(
                process_submission_task.run(str(submission.pk), str(self.campaign.pk)),
                str(submission.pk),
            )
            self.assertFalse(Submission.objects.exists())
        submission.refresh_from_db()
        self.assertEqual(submission.processing_status, "processed")

    def test_periodic_expiration_visits_campaigns_with_separate_scopes(self):
        from apps.workspace.inventory import expire_due_reservations
        from apps.workspace.models import StockReservation

        for campaign, item in zip(self.campaigns, self.items):
            balance = StockBalance.objects.get(item=item)
            balance.physical_quantity = 5
            balance.reserved_quantity = 2
            balance.save()
            StockReservation.objects.create(
                tenant=campaign.tenant,
                campaign=campaign,
                item=item,
                warehouse=balance.warehouse,
                quantity=2,
                purpose="Reserva fictícia",
                expires_at=timezone.now() - timedelta(minutes=1),
            )
        with self.runtime():
            self.assertEqual(expire_due_reservations(), 3)
            self.assertEqual(expire_due_reservations(), 0)
            self.assertFalse(StockReservation.objects.exists())
        self.assertFalse(StockBalance.objects.exclude(reserved_quantity=0).exists())

    def test_global_audit_is_actor_scoped_and_sql_cannot_mutate_audit(self):
        own = AuditEvent.objects.create(
            actor=self.user, action="security.test", resource_type="user"
        )
        AuditEvent.objects.create(
            actor=self.other_user, action="security.test", resource_type="user"
        )
        with (
            self.runtime(),
            database_scope(actor=self.user),
            connection.cursor() as cursor,
        ):
            self.assertEqual(
                list(AuditEvent.objects.values_list("pk", flat=True)), [own.pk]
            )
            cursor.execute("UPDATE core_auditevent SET reason = 'invalid'")
            self.assertEqual(cursor.rowcount, 0)
            cursor.execute("DELETE FROM core_auditevent")
            self.assertEqual(cursor.rowcount, 0)

    def test_streaming_reestablishes_scope_only_during_read(self):
        request = RequestFactory().get(f"/c/{self.campaign.pk}/")
        request.user = self.user

        def content():
            yield Project.objects.get().title.encode()

        with self.runtime():
            response = CampaignScopeMiddleware(
                lambda req: StreamingHttpResponse(content())
            )(request)
            self.assertFalse(Project.objects.exists())
            self.assertEqual(
                b"".join(response.streaming_content), b"Projeto restrito 0"
            )
            self.assertFalse(Project.objects.exists())

    def test_failed_response_rolls_back_writes_and_clears_scope(self):
        request = RequestFactory().get(f"/c/{self.campaign.pk}/")
        request.user = self.user

        def fail(req):
            Project.objects.filter(pk=self.projects[0].pk).update(
                title="Mudança revertida"
            )
            return HttpResponse(status=500)

        with self.runtime():
            response = CampaignScopeMiddleware(fail)(request)
            self.assertEqual(response.status_code, 500)
            self.assertFalse(Project.objects.exists())
        self.projects[0].refresh_from_db()
        self.assertEqual(self.projects[0].title, "Projeto restrito 0")

    def test_liveness_does_not_open_scope_or_authenticate(self):
        request = RequestFactory().get("/healthz/")
        request.user = AnonymousUser()
        with patch(
            "apps.core.scope_middleware.database_scope",
            side_effect=AssertionError("Liveness não deve abrir transação"),
        ):
            self.assertEqual(
                CampaignScopeMiddleware(lambda req: HttpResponse("ok"))(
                    request
                ).status_code,
                200,
            )

    def test_runtime_guard_rejects_table_without_force_rls(self):
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE operations_project NO FORCE ROW LEVEL SECURITY")
        with self.runtime():
            self.assertFalse(verify_database_isolation())
