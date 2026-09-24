import base64
import hashlib
import io
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.campaigns.services import campaigns_for_user, has_campaign_permission
from apps.core.crypto import encrypt_json
from apps.core.models import AuditEvent, Document, RetentionPolicy
from apps.finance.models import BankAccount, BankEntry, Obligation, PaymentRecord
from apps.finance.services import allocate_payment, reconcile_bank_entry
from apps.forms.models import Form, FormVersion, Manifestation, ProcessingPurpose, SourceLink
from apps.forms.public_services import receive_public_submission
from apps.operations.models import Project, PurchaseItem, PurchaseOrder, PurchaseRequest, StockBalance, StockItem, Supplier, Task, Warehouse
from apps.operations.services import apply_stock_movement
from .document_services import upload_document
from .models import Asset, AssetBooking, CampaignEvent, EditorialContent, LogisticsTrip, OfficialDataset, SecurityProfile, StockReservation
from .registry import MODULES, REGISTRY
from .security import matching_counter, new_totp_secret, totp, verify_second_factor
from .services import execute_action, import_aggregate_csv, prepare_create, validate_booking
from .views import csv_safe


class WorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user("operator", password="strong-test-password")
        cls.reviewer = User.objects.create_user("reviewer", password="strong-test-password")
        cls.tenant = Tenant.objects.create(name="Organização teste", slug="teste")
        cls.campaign = Campaign.objects.create(tenant=cls.tenant, code="teste", name="Campanha teste", election_id="2026", office_code="test", jurisdiction_code="test", phase="operation")
        cls.role = Role.objects.create(tenant=cls.tenant, code="operations", name="Operação")
        cls.role.permissions.set(Permission.objects.all())
        cls.member = Membership.objects.create(user=cls.actor, tenant=cls.tenant, campaign=cls.campaign, role=cls.role, status="active")
        cls.reviewer_member = Membership.objects.create(user=cls.reviewer, tenant=cls.tenant, campaign=cls.campaign, role=cls.role, status="active")
        cls.scope = {"tenant": cls.tenant, "campaign": cls.campaign, "created_by": cls.actor}
        cls.project = Project.objects.create(**cls.scope, title="Projeto")
        cls.item = StockItem.objects.create(**cls.scope, name="Papel", sku="TEST", unit="un")
        cls.warehouse = Warehouse.objects.create(**cls.scope, name="Depósito", code="teste")

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client.force_login(self.actor)

    def action(self, key, obj, action, actor=None, command=None, **data):
        obj.refresh_from_db()
        payload = {"reason": "Conferência administrativa", **data}
        return execute_action(actor=actor or self.actor, campaign=self.campaign, config=REGISTRY[key], object_id=obj.pk, action=action, version=obj.row_version, command_id=command or str(uuid.uuid4()), data=payload)

    def test_all_module_lists_and_create_pages_render(self):
        for module in MODULES:
            with self.subTest(module=module.key):
                response = self.client.get(reverse("module_list", args=[self.campaign.pk, module.key]))
                self.assertEqual(response.status_code, 200)
                if module.fields:
                    response = self.client.get(reverse("module_create", args=[self.campaign.pk, module.key]))
                    self.assertEqual(response.status_code, 200)

    def test_dashboard_and_utilities_render(self):
        for name in ["dashboard", "team", "audit_log", "reports", "stock_movement"]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=[self.campaign.pk]))
                self.assertEqual(response.status_code, 200)

    def test_project_create_edit_and_stale_rejection(self):
        response = self.client.post(reverse("module_create", args=[self.campaign.pk, "projetos"]), {"title": "Projeto novo", "description": "Teste", "command_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(title="Projeto novo")
        self.assertEqual(self.client.get(response.url).status_code, 200)
        old_version = project.row_version
        project.description = "Mudança de outra pessoa"
        project.save()
        response = self.client.post(reverse("module_edit", args=[self.campaign.pk, "projetos", project.pk]), {"title": "Sobrescrever", "description": "Teste", "row_version": old_version, "command_id": str(uuid.uuid4())})
        self.assertContains(response, "registro mudou")
        project.refresh_from_db()
        self.assertEqual(project.title, "Projeto novo")

    def test_cross_campaign_foreign_key_is_rejected(self):
        other = Campaign.objects.create(tenant=self.tenant, code="other", name="Outra", election_id="2026", office_code="test", jurisdiction_code="test")
        project = Project.objects.create(tenant=self.tenant, campaign=other, title="Outro projeto")
        with self.assertRaises(ValidationError):
            Task.objects.create(**self.scope, project=project, title="Inválida")
        response = self.client.post(reverse("module_create", args=[self.campaign.pk, "tarefas"]), {"project": str(project.pk), "title": "Invasão", "priority": "normal", "command_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(title="Invasão").exists())

    def test_superuser_has_no_implicit_campaign_access(self):
        admin = User.objects.create_superuser("support", "support@example.test", "test-password")
        self.assertFalse(campaigns_for_user(admin).exists())
        self.assertFalse(has_campaign_permission(admin, self.campaign, "finance.read.campaign"))
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("dashboard", args=[self.campaign.pk])).status_code, 404)
        # Platform inventory is available, but it does not grant campaign access.
        self.assertContains(self.client.get("/admin/"), "Administração da plataforma")
        self.assertFalse(campaigns_for_user(admin).exists())

    def test_suspended_tenant_and_revoked_membership_deny_access(self):
        self.tenant.status = "suspended"
        self.tenant.save()
        self.assertEqual(self.client.get(reverse("dashboard", args=[self.campaign.pk])).status_code, 404)
        self.tenant.status = "active"
        self.tenant.save()
        self.member.revoke()
        self.assertEqual(self.client.get(reverse("dashboard", args=[self.campaign.pk])).status_code, 404)

    def test_stale_model_save_rejected(self):
        a = Project.objects.get(pk=self.project.pk)
        b = Project.objects.get(pk=self.project.pk)
        a.title = "Primeira mudança"
        a.save()
        b.title = "Mudança perdida"
        with self.assertRaises(ValidationError):
            b.save()

    def test_audit_queryset_update_delete_rejected(self):
        AuditEvent.objects.create(actor=self.actor, campaign=self.campaign, tenant=self.tenant, action="test", resource_type="test")
        with self.assertRaises(ValidationError):
            AuditEvent.objects.all().update(action="tampered")
        with self.assertRaises(ValidationError):
            AuditEvent.objects.all().delete()

    def test_task_workflow_requires_dependencies_and_criteria(self):
        first = Task.objects.create(**self.scope, project=self.project, title="Primeira", completion_criteria="Conferir")
        second = Task.objects.create(**self.scope, project=self.project, title="Segunda", completion_criteria="Conferir")
        self.action("tarefas", second, "dependency", depends_on=str(first.pk))
        with self.assertRaises(ValidationError):
            self.action("tarefas", second, "start")
        for action in ["start", "review", "complete"]:
            self.action("tarefas", first, action)
        self.action("tarefas", second, "start")
        second.refresh_from_db()
        self.assertEqual(second.status, "in_progress")

    def test_workflow_command_is_idempotent(self):
        task = Task.objects.create(**self.scope, project=self.project, title="Tarefa")
        command = str(uuid.uuid4())
        self.assertTrue(self.action("tarefas", task, "start", command=command))
        self.assertFalse(self.action("tarefas", task, "start", command=command))
        self.assertEqual(AuditEvent.objects.filter(action="tarefas.start").count(), 1)

    def test_independent_editorial_approval_and_publication(self):
        content = EditorialContent.objects.create(**self.scope, title="Comunicado", channel="Site", body="Horário administrativo", rights_reference="Original")
        self.action("comunicacao", content, "submit")
        with self.assertRaises(ValidationError):
            self.action("comunicacao", content, "approve")
        self.action("comunicacao", content, "approve", actor=self.reviewer)
        self.action("comunicacao", content, "publication", publication_url="https://example.org/comunicado")
        content.refresh_from_db()
        self.assertEqual(content.status, "completed")
        self.assertIsNotNone(content.published_at)

    def test_asset_booking_overlap_and_custodian_acceptance(self):
        now = timezone.now()
        asset = Asset.objects.create(**self.scope, name="Bem", inventory_code="001", ownership="owned")
        booking = AssetBooking.objects.create(**self.scope, asset=asset, custodian=self.member, starts_at=now, ends_at=now + timedelta(hours=2))
        overlap = AssetBooking(**self.scope, asset=asset, custodian=self.member, starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=3))
        with self.assertRaises(ValidationError):
            validate_booking(overlap)
        with self.assertRaises(ValidationError):
            self.action("custodias", booking, "accept", actor=self.reviewer)
        self.action("custodias", booking, "accept")
        self.action("custodias", booking, "return")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "returned")

    def test_stock_reservation_blocks_exit_then_releases(self):
        apply_stock_movement(actor=self.actor, item_id=self.item.pk, warehouse_id=self.warehouse.pk, kind="entry", quantity=10, reason="Entrada de teste")
        with transaction.atomic():
            reservation = StockReservation(**self.scope, item=self.item, warehouse=self.warehouse, quantity=7, purpose="Evento", expires_at=timezone.now() + timedelta(days=1))
            prepare_create(reservation, self.actor)
            reservation.save()
        with self.assertRaises(ValidationError):
            apply_stock_movement(actor=self.actor, item_id=self.item.pk, warehouse_id=self.warehouse.pk, kind="exit", quantity=4, reason="Saída de teste")
        self.action("reservas", reservation, "release")
        balance = StockBalance.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(balance.available_quantity, Decimal("10"))

    def test_nonfinite_stock_quantity_rejected(self):
        for value in ["NaN", "Infinity", "-1", "0.00001", "not a number"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                apply_stock_movement(actor=self.actor, item_id=self.item.pk, warehouse_id=self.warehouse.pk, kind="entry", quantity=value, reason="Teste")

    def test_purchase_receipts_are_partial_and_do_not_overreceive(self):
        supplier = Supplier.objects.create(**self.scope, name="Fornecedor")
        purchase = PurchaseRequest.objects.create(**self.scope, justification="Necessidade operacional", destination="Escritório")
        self.action("compras", purchase, "add_item", description="Papel", quantity="10", unit="un", stock_item=str(self.item.pk))
        self.action("compras", purchase, "submit")
        self.action("compras", purchase, "approve", actor=self.reviewer)
        order = PurchaseOrder.objects.create(**self.scope, purchase_request=purchase, supplier=supplier, amount_cents=10000)
        self.action("pedidos", order, "approve", actor=self.reviewer)
        self.assertEqual(Obligation.objects.filter(origin_id=order.pk).count(), 1)
        item = purchase.items.get()
        self.action("pedidos", order, "receive", item=str(item.pk), quantity="6", warehouse=str(self.warehouse.pk), evidence_reference="TESTE-001")
        order.refresh_from_db()
        self.assertEqual(order.status, "partially_received")
        with self.assertRaises(ValidationError):
            self.action("pedidos", order, "receive", item=str(item.pk), quantity="5", warehouse=str(self.warehouse.pk), evidence_reference="TESTE-002")
        self.action("pedidos", order, "receive", item=str(item.pk), quantity="4", warehouse=str(self.warehouse.pk), evidence_reference="TESTE-003")
        order.refresh_from_db()
        self.assertEqual(order.status, "received")
        self.assertEqual(StockBalance.objects.get(item=self.item).physical_quantity, Decimal("10"))

    def test_reconciliation_cannot_overallocate_across_bank_entries(self):
        account = BankAccount.objects.create(**self.scope, name="Conta", funding_source="Teste")
        payment = PaymentRecord.objects.create(**self.scope, external_reference="PAY", amount_cents=10000, paid_at=timezone.now())
        entries = [BankEntry.objects.create(**self.scope, account=account, external_id=str(i), occurred_at=timezone.now(), amount_cents=-8000, original_line_hash="a" * 64) for i in range(2)]
        reconcile_bank_entry(actor=self.actor, entry_id=entries[0].pk, payment_id=payment.pk, amount_cents=8000)
        with self.assertRaises(ValidationError):
            reconcile_bank_entry(actor=self.actor, entry_id=entries[1].pk, payment_id=payment.pk, amount_cents=8000)

    def test_document_without_antivirus_stays_quarantined(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=__import__('pathlib').Path(directory), CLAMAV_HOST=""):
            doc = Document(**self.scope, display_name="Teste", classification="internal")
            version = upload_document(self.actor, doc, SimpleUploadedFile("test.pdf", b"%PDF-1.4\nTest"))
            self.assertEqual(doc.status, "quarantined")
            response = self.client.get(reverse("document_download", args=[self.campaign.pk, doc.pk, version.pk]))
            self.assertEqual(response.status_code, 404)

    def test_scanned_document_download_rechecks_membership(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=Path(directory)), patch("apps.workspace.document_services.scan_stream", return_value="clean"):
            doc = Document(**self.scope, display_name="Arquivo teste", classification="internal")
            version = upload_document(self.actor, doc, SimpleUploadedFile("test.pdf", b"%PDF-1.4\nTest"))
            url = reverse("document_download", args=[self.campaign.pk, doc.pk, version.pk])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            # Consume through Django's test-client iterator so request_finished
            # doesn't close PostgreSQL's enclosing TestCase transaction.
            self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4\nTest")
            self.assertTrue(response.closed)
            self.member.revoke()
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_aggregate_csv_import_and_duplicate_rejection(self):
        dataset = OfficialDataset(**self.scope, title="Agregado", source_url="https://example.org/source", reference_year=2024, coverage="Teste", methodology="Base fictícia")
        data = b"geography_code,geography_name,metric,value,denominator\n01,Teste,turnout,70,100\n"
        with transaction.atomic():
            import_aggregate_csv(dataset, SimpleUploadedFile("base.csv", data))
        self.assertEqual(dataset.results.count(), 1)
        self.assertEqual(dataset.file_hash, hashlib.sha256(data).hexdigest())
        bad = OfficialDataset(**self.scope, title="Duplicado", source_url="https://example.org/source", reference_year=2024, coverage="Teste", methodology="Teste")
        with self.assertRaises(ValidationError), transaction.atomic():
            import_aggregate_csv(bad, SimpleUploadedFile("base.csv", data + b"01,Teste,turnout,70,100\n"))

    def test_csv_formula_injection_and_export_permission(self):
        self.assertTrue(csv_safe(" =1+1").startswith("'"))
        self.project.title = "=HYPERLINK(test)"
        self.project.save()
        Task.objects.create(**self.scope, project=self.project, title="=HYPERLINK(test)")
        response = self.client.post(reverse("reports", args=[self.campaign.pk]), {"module": "tarefas"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"'=HYPERLINK(test)", response.content)
        self.role.permissions.remove(Permission.objects.get(code="reports.export.campaign"))
        self.assertEqual(self.client.post(reverse("reports", args=[self.campaign.pk]), {"module": "tarefas"}).status_code, 403)

    def test_post_requires_csrf_and_logout_is_not_get(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        response = client.post(reverse("module_create", args=[self.campaign.pk, "projetos"]), {"title": "Sem CSRF"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get(reverse("logout")).status_code, 405)

    def test_archived_campaign_is_readonly(self):
        self.campaign.phase = "archived"
        self.campaign.save()
        self.assertEqual(self.client.get(reverse("module_list", args=[self.campaign.pk, "projetos"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("module_create", args=[self.campaign.pk, "projetos"])).status_code, 403)

    def test_full_public_form_review_publish_receive_flow(self):
        retention = RetentionPolicy.objects.create(tenant=self.tenant, code="test", name="Política teste", retention_days=30, status="active")
        purpose = ProcessingPurpose.objects.create(**self.scope, code="service", description="Teste", legal_basis_ref="Referência fictícia", allowed_fields=["name", "email", "message", "adult_declaration", "consent"], retention_policy=retention)
        form = Form.objects.create(**self.scope, purpose=purpose, title="Atendimento", slug="atendimento")
        builder = reverse("form_builder", args=[self.campaign.pk, form.pk])
        response = self.client.post(builder, {"action": "draft", "row_version": form.row_version, "fields": ["name", "email", "message", "adult_declaration", "consent"], "notice": "Aviso fictício para solicitações administrativas. Retenção de teste. Direitos com a equipe responsável."})
        self.assertEqual(response.status_code, 302)
        version = form.versions.get()
        self.client.force_login(self.reviewer)
        form.refresh_from_db()
        self.client.post(builder, {"action": "approve", "row_version": form.row_version, "version": version.pk})
        version.refresh_from_db()
        self.assertEqual(version.status, "approved")
        form.refresh_from_db()
        self.client.post(builder, {"action": "publish", "row_version": form.row_version, "version": version.pk})
        form.refresh_from_db()
        self.assertEqual(form.status, "published")
        self.client.post(builder, {"action": "link", "row_version": form.row_version})
        link = form.source_links.get()
        self.client.logout()
        response = self.client.get(reverse("public_form", args=[link.public_code]))
        self.assertEqual(response.status_code, 200)
        presentation = response.context["presentation"]
        data = {"presentation": presentation, "name": "Pessoa fictícia", "email": "demo@example.test", "message": "Informação administrativa", "adult_declaration": "on", "consent": "on"}
        response = self.client.post(reverse("public_form", args=[link.public_code]), data)
        self.assertContains(response, "Solicitação recebida")
        self.assertEqual(Manifestation.objects.get().choice, "granted")
        self.client.post(reverse("public_form", args=[link.public_code]), data)
        self.assertEqual(version.submissions.count(), 1)


    def political_fixture(self):
        from .models import CampaignBase, FieldActivity, FieldWorker, Territory
        territory = Territory.objects.create(**self.scope, name="Regional de teste", municipality="Fortaleza", state="CE", coordinator=self.member)
        base = CampaignBase.objects.create(**self.scope, name="Comitê fictício", territory=territory, base_type="committee", public_address="Local ilustrativo público", latitude="-3.73", longitude="-38.52", public_location_confirmed=True)
        worker = FieldWorker.objects.create(**self.scope, name="Integrante fictício", function="field_organizer", territory=territory, supervisor=self.member, onboarding_reference="TESTE", training_status="completed")
        activity = FieldActivity.objects.create(**self.scope, title="Plantão fictício", activity_type="committee_shift", territory=territory, base=base, starts_at=timezone.now(), ends_at=timezone.now() + timedelta(hours=3), required_staff=2, operational_checklist="Conferir material", status="approved")
        return territory, base, worker, activity

    def elector_fixture(self, owner=None):
        from .models import ElectorRegistration
        retention = RetentionPolicy.objects.create(tenant=self.tenant, code=f"e-{uuid.uuid4().hex[:8]}", name="Teste", status="active")
        purpose = ProcessingPurpose.objects.create(**self.scope, code=f"e-{uuid.uuid4().hex[:8]}", description="Cadastro fictício", legal_basis_ref="Referência fictícia", allowed_fields=["name", "email", "phone", "message", "adult_declaration", "consent"], retention_policy=retention, status="active")
        from apps.forms.models import Person
        person = Person.objects.create(**self.scope, retention_policy=retention, display_name_ciphertext=encrypt_json({"value": "Nome sensível fictício"}))
        return ElectorRegistration.objects.create(**self.scope, person=person, purpose=purpose, owner=owner or self.member, municipality="Fortaleza", source="assisted", evidence_reference="Manifestação fictícia")

    def test_map_includes_only_operational_places_not_electors(self):
        territory, base, worker, activity = self.political_fixture()
        registration = self.elector_fixture()
        response = self.client.get(reverse("campaign_map", args=[self.campaign.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.context["map_data"]
        self.assertEqual(len(data["points"]), 1)
        self.assertEqual(data["points"][0]["name"], "Comitê fictício")
        self.assertEqual(len(data["activities"]), 1)
        serialized = str(data)
        self.assertNotIn(str(registration.person_id), serialized)
        self.assertNotIn("Nome sensível", serialized)
        self.assertNotIn(worker.name, serialized)
        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_map_campaign_isolation(self):
        self.political_fixture()
        self.member.revoke()
        self.assertEqual(self.client.get(reverse("campaign_map", args=[self.campaign.pk])).status_code, 404)

    def test_map_rejects_invalid_coordinates_and_nonpublic_location(self):
        from .models import CampaignBase
        territory, _, _, _ = self.political_fixture()
        with self.assertRaises(ValidationError):
            CampaignBase.objects.create(**self.scope, territory=territory, name="Inválido", public_address="Teste", latitude=100, longitude=-38, public_location_confirmed=True)
        with self.assertRaises(ValidationError):
            CampaignBase.objects.create(**self.scope, territory=territory, name="Residência", public_address="Privado", latitude=-3, longitude=-38)

    def test_field_assignment_rejects_overlapping_shifts(self):
        from .models import FieldActivity, FieldAssignment
        territory, base, worker, activity = self.political_fixture()
        FieldAssignment.objects.create(**self.scope, activity=activity, worker=worker, role_description="Recepção")
        second = FieldActivity.objects.create(**self.scope, title="Sobreposição", activity_type="street_team", territory=territory, base=base, starts_at=activity.starts_at, ends_at=activity.ends_at, operational_checklist="Teste", status="approved")
        with self.assertRaises(ValidationError):
            validate_booking(FieldAssignment(**self.scope, activity=second, worker=worker, role_description="Outra escala"))

    def test_field_assignment_presence_flow(self):
        from .models import FieldAssignment
        _, _, worker, activity = self.political_fixture()
        assignment = FieldAssignment.objects.create(**self.scope, activity=activity, worker=worker, role_description="Recepção")
        self.action("escalas-de-campo", assignment, "confirm")
        self.action("escalas-de-campo", assignment, "checkin")
        self.action("escalas-de-campo", assignment, "complete")
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, "completed")
        self.assertIsNotNone(assignment.checked_in_at)
        self.assertIsNotNone(assignment.completed_at)

    def test_elector_create_encrypts_identity_and_stays_pending(self):
        from .models import ElectorRegistration
        template = self.elector_fixture()
        response = self.client.post(reverse("module_create", args=[self.campaign.pk, "eleitores"]), {"command_id": str(uuid.uuid4()), "purpose": template.purpose_id, "owner": self.member.pk, "municipality": "Fortaleza", "evidence_reference": "TERMO-NEW-001", "registration_name": "Pessoa voluntária fictícia", "registration_email": "voluntario@example.test", "registration_phone": "", "adult_declaration": "on", "requested_registration": "on"})
        self.assertEqual(response.status_code, 302)
        registration = ElectorRegistration.objects.get(evidence_reference="TERMO-NEW-001")
        self.assertEqual(registration.status, "pending")
        self.assertEqual(registration.source, "assisted")
        self.assertIsNone(registration.consent_verified_at)
        self.assertNotIn(b"Pessoa volunt", bytes(registration.person.display_name_ciphertext))
        self.assertEqual(self.client.get(response.url).status_code, 200)

    def test_elector_assigned_scope_and_suppression(self):
        from apps.forms.models import ContactPoint, Suppression
        own = self.elector_fixture()
        other = self.elector_fixture(owner=self.reviewer_member)
        self.role.permissions.remove(Permission.objects.get(code="electors.read.campaign"))
        self.assertEqual(self.client.get(reverse("module_detail", args=[self.campaign.pk, "eleitores", other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("module_detail", args=[self.campaign.pk, "eleitores", own.pk])).status_code, 200)
        ContactPoint.objects.create(person=own.person, type="email", value_ciphertext=encrypt_json({"value": "teste@example.test"}), match_hmac="a" * 64)
        self.action("eleitores", own, "suppress")
        self.assertEqual(Suppression.objects.filter(purpose=own.purpose).count(), 1)
        own.refresh_from_db()
        self.assertEqual(own.status, "suppressed")

    def test_budget_lines_and_independent_approval(self):
        from apps.finance.models import BudgetVersion
        budget = BudgetVersion.objects.create(**self.scope, version_number=1)
        self.action("orcamentos", budget, "add_line", cost_center="Comitê", funding_source="Fonte fictícia", amount_cents="50000")
        with self.assertRaises(ValidationError):
            self.action("orcamentos", budget, "approve")
        self.action("orcamentos", budget, "approve", actor=self.reviewer)
        budget.refresh_from_db()
        self.assertEqual(budget.status, "approved")

    def test_accounting_snapshot_export_is_not_delivery(self):
        from apps.finance.models import AccountingBatch
        batch = AccountingBatch(**self.scope, cutoff_at=timezone.now())
        prepare_create(batch, self.actor)
        batch.save()
        self.action("contabilidade", batch, "approve", actor=self.reviewer)
        response = self.client.post(reverse("accounting_export", args=[self.campaign.pk, batch.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["manifest"]["official_filing"])
        batch.refresh_from_db()
        self.assertEqual(batch.status, "exported")
        self.assertEqual(batch.filings.count(), 0)


class SecurityTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_rfc6238_vector(self):
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(totp(secret, 59 // 30, digits=8), "94287082")
        self.assertEqual(totp(secret, 1111111109 // 30, digits=8), "07081804")

    def test_totp_replay_and_attempt_limit(self):
        user = User.objects.create_user("mfa")
        secret = new_totp_secret()
        profile = SecurityProfile.objects.create(user=user, totp_secret_ciphertext=encrypt_json({"secret": secret}), enabled_at=timezone.now())
        code = totp(secret, int(timezone.now().timestamp()) // 30)
        self.assertTrue(verify_second_factor(user, code))
        self.assertFalse(verify_second_factor(user, code))
        for _ in range(4):
            verify_second_factor(user, "invalid")
        profile.refresh_from_db()
        self.assertIsNotNone(profile.locked_until)

    @override_settings(MFA_REQUIRED=True)
    def test_mfa_required_for_browser_and_api(self):
        user = User.objects.create_user("needs-mfa")
        self.client.force_login(user)
        self.assertRedirects(self.client.get("/"), "/seguranca/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 403)

    def test_login_rate_limit(self):
        User.objects.create_user("locked", password="valid-test-password")
        for _ in range(5):
            self.client.post("/entrar/", {"username": "locked", "password": "wrong"})
        response = self.client.post("/entrar/", {"username": "locked", "password": "valid-test-password"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
