import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.models import AuditEvent
from apps.operations.models import StockBalance, StockItem, StockMovement, Warehouse
from apps.operations.services import apply_stock_movement
from .inventory import expire_due_reservations
from .models import StockReservation, StockTransfer
from .registry import REGISTRY
from .services import execute_action, prepare_create


class InventoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user("dispatcher")
        cls.reviewer = User.objects.create_user("receiver")
        cls.tenant = Tenant.objects.create(name="Teste", slug="inventory")
        cls.campaign = Campaign.objects.create(tenant=cls.tenant, code="inventory", name="Teste", election_id="test", office_code="test", jurisdiction_code="test", phase="operation")
        role = Role.objects.create(tenant=cls.tenant, code="stock", name="Estoque")
        role.permissions.set(Permission.objects.all())
        for user in [cls.actor, cls.reviewer]:
            Membership.objects.create(user=user, tenant=cls.tenant, campaign=cls.campaign, role=role, status="active")
        cls.scope = {"tenant": cls.tenant, "campaign": cls.campaign, "created_by": cls.actor}
        cls.item = StockItem.objects.create(**cls.scope, name="Material de comitê", sku="KIT", unit="un")
        cls.source = Warehouse.objects.create(**cls.scope, name="Depósito central", code="central")
        cls.destination = Warehouse.objects.create(**cls.scope, name="Comitê regional", code="regional")

    def setUp(self):
        self.client.force_login(self.actor)
        apply_stock_movement(actor=self.actor, item_id=self.item.pk, warehouse_id=self.source.pk, kind="entry", quantity=100, reason="Carga fictícia")
        self.transfer = StockTransfer.objects.create(**self.scope, item=self.item, source_warehouse=self.source, destination_warehouse=self.destination, quantity=30, purpose="Abastecer comitê")

    def action(self, name, *, actor=None, command=None, version=None, **data):
        self.transfer.refresh_from_db()
        return execute_action(actor=actor or self.actor, campaign=self.campaign, config=REGISTRY["transferencias"], object_id=self.transfer.pk, action=name, version=version or self.transfer.row_version, command_id=command or str(uuid.uuid4()), data={"reason": "Conferência de teste", **data})

    def stock(self, warehouse):
        balance = StockBalance.objects.filter(item=self.item, warehouse=warehouse).first()
        return balance.physical_quantity if balance else Decimal("0")

    def reserve(self, quantity=20):
        with transaction.atomic():
            obj = StockReservation(**self.scope, item=self.item, warehouse=self.source, quantity=quantity, purpose="Ação fictícia", expires_at=timezone.now() + timedelta(hours=1))
            prepare_create(obj, self.actor)
            obj.save()
        return obj

    def test_dispatch_and_partial_receipt_preserve_material(self):
        self.assertEqual(self.stock(self.source), 100)
        self.action("dispatch")
        self.transfer.refresh_from_db()
        self.assertEqual((self.stock(self.source), self.stock(self.destination), self.transfer.in_transit_quantity), (70, 0, 30))
        self.action("receive_transfer", actor=self.reviewer, quantity="12", evidence_reference="REC-001")
        self.transfer.refresh_from_db()
        self.assertEqual((self.stock(self.destination), self.transfer.in_transit_quantity), (12, 18))
        self.action("receive_transfer", actor=self.reviewer, quantity="18", evidence_reference="REC-002")
        self.transfer.refresh_from_db()
        self.assertEqual((self.transfer.status, self.stock(self.source), self.stock(self.destination)), ("received", 70, 30))
        self.assertEqual(self.transfer.receipts.count(), 2)
        self.assertEqual(StockMovement.objects.filter(origin_type="stock_transfer_dispatch", origin_id=self.transfer.pk).count(), 1)

    def test_partial_receipt_then_return_remaining(self):
        self.action("dispatch")
        self.action("receive_transfer", actor=self.reviewer, quantity="10", evidence_reference="REC-001")
        self.action("return_transfer", actor=self.reviewer, quantity="20", evidence_reference="DEV-001")
        self.transfer.refresh_from_db()
        self.assertEqual((self.stock(self.source), self.stock(self.destination), self.transfer.in_transit_quantity), (90, 10, 0))
        self.assertEqual(self.transfer.status, "returned")

    def test_cancel_before_dispatch_does_not_change_stock(self):
        self.action("cancel")
        self.assertEqual(self.stock(self.source), 100)
        with self.assertRaises(ValidationError):
            self.action("dispatch")

    def test_in_transit_cannot_be_cancelled(self):
        self.action("dispatch")
        with self.assertRaises(ValidationError):
            self.action("cancel")
        self.assertEqual(self.stock(self.source), 70)

    def test_sender_cannot_confirm_receipt_or_return(self):
        self.action("dispatch")
        for action in ["receive_transfer", "return_transfer"]:
            with self.assertRaises(ValidationError):
                self.action(action, quantity="1", evidence_reference="REC-001")
        self.assertFalse(self.transfer.receipts.exists())

    def test_receipt_validation_rolls_back_everything(self):
        self.action("dispatch")
        for quantity in ["0", "-1", "31", "NaN", "Infinity", "1.00001", "garbage"]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                self.action("receive_transfer", actor=self.reviewer, quantity=quantity, evidence_reference="REC-001")
        with self.assertRaises(ValidationError):
            self.action("receive_transfer", actor=self.reviewer, quantity="1", evidence_reference="")
        self.assertEqual(self.stock(self.destination), 0)

    def test_duplicate_command_does_not_duplicate_receipt(self):
        self.action("dispatch")
        command = str(uuid.uuid4())
        self.assertTrue(self.action("receive_transfer", actor=self.reviewer, command=command, quantity="10", evidence_reference="REC-001"))
        self.assertFalse(self.action("receive_transfer", actor=self.reviewer, command=command, quantity="10", evidence_reference="REC-001"))
        with self.assertRaises(ValidationError):
            self.action("receive_transfer", actor=self.reviewer, command=command, quantity="11", evidence_reference="REC-001")
        self.assertEqual(self.stock(self.destination), 10)

    def test_stale_version_is_rejected(self):
        self.action("dispatch")
        with self.assertRaises(ValidationError):
            self.action("receive_transfer", actor=self.reviewer, version=1, quantity="1", evidence_reference="REC-001")

    def test_insufficient_or_reserved_stock_cannot_be_dispatched(self):
        self.reserve(80)
        with self.assertRaises(ValidationError):
            self.action("dispatch")
        self.assertEqual(self.stock(self.source), 100)

    def test_expiration_is_idempotent_and_audited(self):
        reservation = self.reserve()
        self.assertEqual(expire_due_reservations(now=reservation.expires_at + timedelta(seconds=1)), 1)
        self.assertEqual(expire_due_reservations(now=reservation.expires_at + timedelta(seconds=1)), 0)
        reservation.refresh_from_db()
        balance = StockBalance.objects.get(item=self.item, warehouse=self.source)
        self.assertEqual((reservation.status, balance.physical_quantity, balance.reserved_quantity), ("expired", 100, 0))
        self.assertEqual(AuditEvent.objects.filter(action="stock.reservation_expired", resource_id=str(reservation.pk)).count(), 1)

    def test_expired_reservation_released_before_stock_exit(self):
        reservation = self.reserve(90)
        with patch("apps.workspace.inventory.timezone.now", return_value=reservation.expires_at + timedelta(seconds=1)):
            self.action("dispatch")
        self.assertEqual(self.stock(self.source), 70)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, "expired")

    def test_new_reservation_reclaims_expired_capacity(self):
        reservation = self.reserve(90)
        with patch("apps.workspace.inventory.timezone.now", return_value=reservation.expires_at + timedelta(seconds=1)):
            replacement = self.reserve(80)
        balance = StockBalance.objects.get(item=self.item, warehouse=self.source)
        self.assertEqual(balance.reserved_quantity, replacement.quantity)

    def test_archived_and_suspended_campaign_cleanup_is_skipped(self):
        reservation = self.reserve()
        self.campaign.phase = "archived"
        self.campaign.save()
        self.assertEqual(expire_due_reservations(now=reservation.expires_at + timedelta(seconds=1)), 0)
        with self.assertRaises(ValidationError):
            self.action("dispatch")
        self.campaign.phase = "operation"
        self.campaign.save()
        self.tenant.status = "suspended"
        self.tenant.save()
        self.assertEqual(expire_due_reservations(now=reservation.expires_at + timedelta(seconds=1)), 0)

    def test_revoked_user_cannot_receive(self):
        self.action("dispatch")
        Membership.objects.filter(user=self.reviewer).update(revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.action("receive_transfer", actor=self.reviewer, quantity="1", evidence_reference="REC-001")

    def test_cross_campaign_and_same_warehouse_are_rejected(self):
        self.transfer.destination_warehouse = self.source
        with self.assertRaises(ValidationError):
            self.transfer.full_clean()
        campaign = Campaign.objects.create(tenant=self.tenant, code="other", name="Outra", election_id="test", office_code="test", jurisdiction_code="test")
        self.transfer.destination_warehouse = Warehouse.objects.create(tenant=self.tenant, campaign=campaign, name="Outro", code="other")
        with self.assertRaises(ValidationError):
            self.transfer.full_clean()

    def test_transfer_create_and_detail_pages(self):
        url = reverse("module_create", args=[self.campaign.pk, "transferencias"])
        data = {"item": self.item.pk, "source_warehouse": self.source.pk, "destination_warehouse": self.destination.pk, "quantity": "10", "purpose": "Nova ação", "command_id": uuid.uuid4()}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), "Conferência da remessa")
        self.action("dispatch")
        response = self.client.get(reverse("module_edit", args=[self.campaign.pk, "transferencias", self.transfer.pk]))
        self.assertEqual(response.status_code, 302)

    def test_expiration_endpoint_is_post_and_csrf_protected(self):
        url = reverse("stock_expire", args=[self.campaign.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        self.assertEqual(client.post(url).status_code, 403)

    def test_transfer_blocks_archival(self):
        self.campaign.phase = "closing"
        self.campaign.save()
        response = self.client.post(reverse("campaign_phase", args=[self.campaign.pk]), {"row_version": self.campaign.row_version, "reason": "Fechamento de teste"}, follow=True)
        self.assertContains(response, "Conclua as transferências")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.phase, "closing")
