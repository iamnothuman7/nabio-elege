from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant

from .models import Project, StockItem, StockMovement, Task, Warehouse
from .services import add_task_dependency, apply_stock_movement


class OperationsIntegrityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("operator")
        self.tenant = Tenant.objects.create(name="Organização", slug="operations-org")
        self.campaign = Campaign.objects.create(
            tenant=self.tenant,
            code="campaign",
            name="Campanha",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        role = Role.objects.create(tenant=self.tenant, code="operator", name="Operador")
        role.permissions.add(
            Permission.objects.get(code="tasks.manage.campaign"),
            Permission.objects.get(code="stock.manage.campaign"),
        )
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            campaign=self.campaign,
            role=role,
            status=Membership.Status.ACTIVE,
        )
        self.project = Project.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            title="Projeto fictício",
        )

    def create_task(self, title):
        return Task.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            project=self.project,
            title=title,
        )

    def test_task_dependency_cycle_is_rejected(self):
        task_a = self.create_task("A")
        task_b = self.create_task("B")
        task_c = self.create_task("C")
        add_task_dependency(actor=self.user, task_id=task_b.id, depends_on_id=task_a.id)
        add_task_dependency(actor=self.user, task_id=task_c.id, depends_on_id=task_b.id)
        with self.assertRaises(ValidationError):
            add_task_dependency(
                actor=self.user, task_id=task_a.id, depends_on_id=task_c.id
            )

    def test_stock_cannot_become_negative(self):
        item = StockItem.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            name="Material",
            sku="material-1",
            unit="un",
        )
        warehouse = Warehouse.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            name="Depósito",
            code="main",
        )
        apply_stock_movement(
            actor=self.user,
            item_id=item.id,
            warehouse_id=warehouse.id,
            kind=StockMovement.Kind.ENTRY,
            quantity="10",
            reason="Entrada de teste",
        )
        _, balance = apply_stock_movement(
            actor=self.user,
            item_id=item.id,
            warehouse_id=warehouse.id,
            kind=StockMovement.Kind.EXIT,
            quantity="8",
            reason="Saída de teste",
        )
        self.assertEqual(balance.physical_quantity, 2)
        with self.assertRaises(ValidationError):
            apply_stock_movement(
                actor=self.user,
                item_id=item.id,
                warehouse_id=warehouse.id,
                kind=StockMovement.Kind.EXIT,
                quantity="3",
                reason="Saída acima do saldo",
            )
