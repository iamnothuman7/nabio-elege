from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.operations.models import StockBalance, StockItem, Warehouse
from apps.operations.services import apply_stock_movement


@skipUnless(connection.vendor == "postgresql", "Requer PostgreSQL e bloqueios reais de linha")
class PostgreSQLConcurrencyTests(TransactionTestCase):
    def test_concurrent_exits_cannot_spend_same_stock(self):
        actor = User.objects.create_user("concurrent")
        tenant = Tenant.objects.create(name="Teste", slug="concurrent")
        campaign = Campaign.objects.create(tenant=tenant, code="concurrent", name="Concorrência", election_id="test", office_code="test", jurisdiction_code="test")
        role = Role.objects.create(tenant=tenant, code="stock", name="Estoque")
        permission, _ = Permission.objects.get_or_create(code="stock.manage.campaign", defaults={"resource": "stock", "action": "manage", "scope": "campaign"})
        role.permissions.add(permission)
        Membership.objects.create(user=actor, tenant=tenant, campaign=campaign, role=role, status="active")
        item = StockItem.objects.create(tenant=tenant, campaign=campaign, name="Teste", sku="CONC", unit="un")
        warehouse = Warehouse.objects.create(tenant=tenant, campaign=campaign, name="Depósito", code="main")
        apply_stock_movement(actor=actor, item_id=item.pk, warehouse_id=warehouse.pk, kind="entry", quantity=10, reason="Carga de teste")
        barrier = Barrier(2, timeout=10)
        def exit_stock():
            close_old_connections()
            try:
                user = User.objects.get(pk=actor.pk)
                barrier.wait()
                apply_stock_movement(actor=user, item_id=item.pk, warehouse_id=warehouse.pk, kind="exit", quantity=7, reason="Saída concorrente")
                return "ok"
            except ValidationError:
                return "insufficient"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(exit_stock) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        self.assertCountEqual(results, ["ok", "insufficient"])
        self.assertEqual(StockBalance.objects.get(item=item).physical_quantity, 3)
