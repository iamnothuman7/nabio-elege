import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.campaigns.models import Membership, Permission, Role
from apps.core.crypto import decrypt_json
from apps.core.models import AuditEvent
from apps.operations.models import StockBalance, StockItem, StockMovement, Warehouse
from .access_choices import LABELS, permission_label
from .materials import record_movement
from .models import CampaignBase, ElectorRegistration, Territory
from .platform_services import create_customer_access, create_selected_access


class SimplificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .tests import WorkspaceTests

        WorkspaceTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.actor)

    def movement_data(self, **extra):
        return {
            "item": str(self.item.pk),
            "kind": "entry",
            "quantity": "10",
            "command_id": str(uuid.uuid4()),
            **extra,
        }

    def elector_data(self, **extra):
        return {
            "registration_name": "Pessoa fictícia QA",
            "municipality": "Fortaleza",
            "adult_declaration": "on",
            "requested_registration": "on",
            "command_id": str(uuid.uuid4()),
            **extra,
        }

    def purpose(self, allow_title=False):
        from .tests import WorkspaceTests

        purpose = WorkspaceTests.elector_fixture(self).purpose
        if allow_title:
            purpose.allowed_fields += ["first_vote", "voter_title"]
            purpose.save()
        return purpose

    def test_help_escaped_and_available_in_each_module(self):
        from .registry import MODULES
        from django.template.loader import render_to_string

        html = render_to_string(
            "workspace/help.html",
            {
                "help_text": '<script>alert("x")</script>',
                "help_label": '"x',
                "help_id": "qa-help",
            },
        )
        self.assertNotIn("<script>", html)
        self.assertIn('role="tooltip"', html)
        for module in MODULES:
            response = self.client.get(
                reverse("module_list", args=[self.campaign.pk, module.key])
            )
            self.assertContains(response, "Como usar esta tela")
            self.assertContains(response, "workspace/guidance.js")

    def test_name_only_stock_item_generates_code_and_unit(self):
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "itens"]),
            {"name": "Material novo", "command_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, 302)
        item = StockItem.objects.get(name="Material novo")
        self.assertTrue(item.sku.startswith("MAT-"))
        self.assertEqual(item.unit, "un")
        response = self.client.post(
            reverse("module_edit", args=[self.campaign.pk, "itens", item.pk]),
            {
                "name": "Material renomeado",
                "row_version": item.row_version,
                "command_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, 302)
        old_sku = item.sku
        item.refresh_from_db()
        self.assertEqual(item.sku, old_sku)

    def test_movement_without_reason_or_depot_with_one_depot(self):
        response = self.client.post(
            reverse("stock_movement", args=[self.campaign.pk]), self.movement_data()
        )
        self.assertRedirects(
            response, reverse("stock_movement", args=[self.campaign.pk])
        )
        movement = StockMovement.objects.get()
        self.assertEqual(movement.warehouse_id, self.warehouse.pk)
        self.assertEqual(movement.reason, "Entrada manual de material")
        self.assertEqual(StockBalance.objects.get().physical_quantity, 10)

    def test_empty_inventory_creates_depot_only_on_success(self):
        self.warehouse.delete()
        self.client.get(reverse("stock_movement", args=[self.campaign.pk]))
        self.assertFalse(Warehouse.objects.exists())
        with self.assertRaises(ValidationError):
            record_movement(
                actor=self.actor,
                campaign=self.campaign,
                data=self.movement_data(kind="exit"),
            )
        self.assertFalse(Warehouse.objects.exists())
        record_movement(
            actor=self.actor, campaign=self.campaign, data=self.movement_data()
        )
        self.assertEqual(Warehouse.objects.get().name, "Estoque principal")

    def test_multiple_depots_require_choice_and_retain_form(self):
        Warehouse.objects.create(**self.scope, name="Outro local", code="outro")
        response = self.client.post(
            reverse("stock_movement", args=[self.campaign.pk]), self.movement_data()
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("warehouse", response.context["form"].errors)
        self.assertEqual(response.context["form"]["quantity"].value(), "10")
        self.assertFalse(StockMovement.objects.exists())

    def test_repeated_movement_does_not_duplicate_and_different_retry_rejected(self):
        data = self.movement_data()
        self.assertTrue(
            record_movement(actor=self.actor, campaign=self.campaign, data=data)
        )
        self.assertFalse(
            record_movement(actor=self.actor, campaign=self.campaign, data=data)
        )
        with self.assertRaises(ValidationError):
            record_movement(
                actor=self.actor,
                campaign=self.campaign,
                data={**data, "quantity": "12"},
            )
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(StockBalance.objects.get().physical_quantity, 10)

    def test_exit_cannot_consume_reserved_stock(self):
        StockBalance.objects.create(
            item=self.item,
            warehouse=self.warehouse,
            physical_quantity=10,
            reserved_quantity=8,
        )
        with self.assertRaises(ValidationError):
            record_movement(
                actor=self.actor,
                campaign=self.campaign,
                data=self.movement_data(kind="exit", quantity="3"),
            )
        self.assertEqual(StockBalance.objects.get().physical_quantity, 10)
        self.assertFalse(StockMovement.objects.exists())

    def test_invalid_quantities_and_foreign_item_do_not_write(self):
        for quantity in ["0", "-1", "NaN", "Infinity", "0.00001", "100000000000000"]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                record_movement(
                    actor=self.actor,
                    campaign=self.campaign,
                    data=self.movement_data(quantity=quantity),
                )
        with self.assertRaises(ValidationError):
            record_movement(
                actor=self.actor,
                campaign=self.campaign,
                data=self.movement_data(item=str(uuid.uuid4())),
            )
        self.assertFalse(StockMovement.objects.exists())

    def test_materials_post_requires_csrf_and_permission(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        path = reverse("stock_movement", args=[self.campaign.pk])
        self.assertEqual(client.post(path, self.movement_data()).status_code, 403)
        self.role.permissions.remove(
            Permission.objects.get(code="stock.manage.campaign")
        )
        self.assertEqual(self.client.get(path).status_code, 403)

    def test_point_without_coordinates_is_saved_and_listed_not_mapped(self):
        territory = Territory.objects.create(
            **self.scope, name="Centro", municipality="Fortaleza", state="CE"
        )
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "comites"]),
            {
                "command_id": str(uuid.uuid4()),
                "name": "Ponto sem coordenadas",
                "territory": territory.pk,
                "base_type": "committee",
                "public_address": "Local público fictício",
                "public_location_confirmed": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        base = CampaignBase.objects.get()
        self.assertIsNone(base.latitude)
        self.assertIsNone(base.longitude)
        response = self.client.get(reverse("campaign_map", args=[self.campaign.pk]))
        self.assertContains(response, "Ponto sem coordenadas")
        self.assertEqual(response.context["map_data"]["points"], [])
        self.assertEqual(response.context["unlocated_count"], 1)
        self.assertEqual(
            self.client.get(reverse("dashboard", args=[self.campaign.pk])).status_code,
            200,
        )
        base.latitude = Decimal("-3")
        with self.assertRaises(ValidationError):
            base.full_clean()

    def test_simple_elector_defaults_are_truthful_and_pending(self):
        purpose = self.purpose()
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "eleitores"]),
            self.elector_data(),
        )
        self.assertEqual(response.status_code, 302)
        obj = ElectorRegistration.objects.order_by("-created_at").first()
        self.assertEqual(obj.owner, self.member)
        self.assertEqual(obj.purpose, purpose)
        self.assertEqual(obj.status, "pending")
        self.assertIn("declarada pelo operador", obj.evidence_reference)
        self.assertIsNone(obj.first_vote)
        self.assertIsNone(obj.voter_title_ciphertext)
        self.assertIsNone(obj.consent_verified_at)

    def test_title_is_encrypted_optional_scoped_and_not_logged(self):
        self.purpose(allow_title=True)
        title = "123456789012"  # Synthetic, format only; not an official validity test.
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "eleitores"]),
            self.elector_data(first_vote="false", voter_title=title),
        )
        self.assertEqual(response.status_code, 302)
        obj = ElectorRegistration.objects.order_by("-created_at").first()
        self.assertFalse(obj.first_vote)
        self.assertNotIn(title.encode(), bytes(obj.voter_title_ciphertext))
        self.assertEqual(decrypt_json(obj.voter_title_ciphertext)["value"], title)
        self.assertContains(self.client.get(response.url), title)
        self.assertNotContains(
            self.client.get(
                reverse("module_list", args=[self.campaign.pk, "eleitores"])
            ),
            title,
        )
        self.assertNotIn(
            title, str(list(AuditEvent.objects.values("minimized_diff", "reason")))
        )
        self.role.permissions.remove(
            Permission.objects.get(code="electors.read.campaign")
        )
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(response.url).status_code, 404)

    def test_unauthorized_extra_elector_fields_are_not_stored(self):
        self.purpose()
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "eleitores"]),
            self.elector_data(first_vote="true", voter_title="123456789012"),
        )
        self.assertContains(response, "ainda não está autorizado")
        self.assertEqual(ElectorRegistration.objects.count(), 1)

    def test_missing_privacy_configuration_does_not_fabricate_purpose(self):
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "eleitores"]),
            self.elector_data(),
        )
        self.assertContains(response, "responsável pela privacidade")
        self.assertFalse(ElectorRegistration.objects.exists())

    def test_multiple_purposes_are_not_chosen_arbitrarily(self):
        self.purpose()
        self.purpose()
        response = self.client.post(
            reverse("module_create", args=[self.campaign.pk, "eleitores"]),
            self.elector_data(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("purpose", response.context["form"].errors)

    def test_selected_access_does_not_change_existing_roles_or_accounts(self):
        old_permissions = set(self.role.permissions.values_list("code", flat=True))
        response = self.client.post(
            reverse("team", args=[self.campaign.pk]),
            {
                "action": "create_access",
                "username": "qa.materials",
                "password": "Only-Synthetic-Testing-849!",
                "permission_codes": ["stock.manage.campaign"],
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="qa.materials")
        member = Membership.objects.get(user=user)
        self.assertEqual(
            set(member.role.permissions.values_list("code", flat=True)),
            {"stock.manage.campaign"},
        )
        self.assertEqual(
            set(self.role.permissions.values_list("code", flat=True)), old_permissions
        )
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertNotEqual(member.role_id, self.role.pk)
        self.assertTrue(user.securityprofile.password_change_required)

    def test_manager_cannot_delegate_unowned_permissions_even_direct_service(self):
        self.role.permissions.remove(
            Permission.objects.get(code="finance.read.campaign")
        )
        with self.assertRaises(ValidationError):
            create_selected_access(
                actor=self.actor,
                campaign=self.campaign,
                username="qa.invalid",
                password="Only-Synthetic-Testing-849!",
                permission_codes=["finance.read.campaign"],
            )
        self.assertFalse(User.objects.filter(username="qa.invalid").exists())
        self.member.revoke()
        with self.assertRaises(PermissionDenied):
            create_selected_access(
                actor=self.actor,
                campaign=self.campaign,
                username="qa.invalid",
                password="Only-Synthetic-Testing-849!",
                permission_codes=["stock.manage.campaign"],
            )

    def test_dependency_must_be_explicit_and_bad_account_rolls_back_role(self):
        roles_before = Role.objects.count()
        for codes, username in [
            (["electors.create.assigned"], "qa.invalid"),
            (["stock.manage.campaign"], self.actor.username),
            ([], "qa.none"),
            (["bogus.permission"], "qa.bogus"),
        ]:
            with self.assertRaises(ValidationError):
                create_selected_access(
                    actor=self.actor,
                    campaign=self.campaign,
                    username=username,
                    password="Only-Synthetic-Testing-849!",
                    permission_codes=codes,
                )
        self.assertEqual(Role.objects.count(), roles_before)

    def test_platform_selected_access_scopes_to_customer(self):
        admin = User.objects.create_superuser(
            "qa.platform", "", "Only-Synthetic-Testing-849!"
        )
        user = create_customer_access(
            actor=admin,
            campaign=self.campaign,
            username="qa.client",
            password="Only-Synthetic-Testing-849!",
            permission_codes=["tasks.manage.campaign"],
        )
        self.assertEqual(Membership.objects.get(user=user).campaign, self.campaign)
        self.assertFalse(user.is_superuser)
        self.assertNotIn(
            "Only-Synthetic",
            str(list(AuditEvent.objects.values("minimized_diff", "reason"))),
        )

    def test_permission_catalog_covers_all_database_permissions(self):
        for code in Permission.objects.values_list("code", flat=True):
            self.assertTrue(code in LABELS or code.rsplit(".", 1)[0] in LABELS, code)
            self.assertNotIn("Permissão administrativa:", permission_label(code))
