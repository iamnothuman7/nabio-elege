from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.campaigns.services import require_campaign_permission
from apps.core.services import append_audit_event, enqueue_outbox_event

from .models import StockBalance, StockItem, StockMovement, Task, TaskDependency, Warehouse


@transaction.atomic
def add_task_dependency(*, actor, task_id, depends_on_id):
    task = Task.objects.select_for_update().select_related("campaign").get(pk=task_id)
    predecessor = Task.objects.select_for_update().get(pk=depends_on_id)
    require_campaign_permission(actor, task.campaign, "tasks.manage.campaign")
    if task.campaign_id != predecessor.campaign_id:
        raise ValidationError("Dependências devem pertencer à mesma campanha.")
    if task.id == predecessor.id:
        raise ValidationError("Uma tarefa não pode depender de si mesma.")

    frontier = [predecessor.id]
    visited = set()
    while frontier:
        current = frontier.pop()
        if current == task.id:
            raise ValidationError("A dependência criaria um ciclo.")
        if current in visited:
            continue
        visited.add(current)
        frontier.extend(
            TaskDependency.objects.filter(task_id=current).values_list(
                "depends_on_id", flat=True
            )
        )

    dependency, _ = TaskDependency.objects.get_or_create(
        task=task, depends_on=predecessor
    )
    append_audit_event(
        actor=actor,
        tenant=task.tenant,
        campaign=task.campaign,
        action="task.dependency_added",
        resource_type="task",
        resource_id=task.id,
        minimized_diff={"depends_on_id": str(predecessor.id)},
    )
    return dependency


@transaction.atomic
def apply_stock_movement(
    *, actor, item_id, warehouse_id, kind, quantity, reason, origin_type="", origin_id=None
):
    try:
        quantity = Decimal(str(quantity))
    except InvalidOperation:
        raise ValidationError("Quantidade inválida.")
    if not quantity.is_finite() or quantity <= 0 or quantity >= Decimal("100000000000000") or quantity != quantity.quantize(Decimal("0.0001")):
        raise ValidationError("A quantidade deve ser positiva.")
    item = (
        StockItem.objects.select_for_update()
        .select_related("campaign", "tenant")
        .get(pk=item_id)
    )
    warehouse = Warehouse.objects.select_for_update().get(pk=warehouse_id)
    require_campaign_permission(actor, item.campaign, "stock.manage.campaign")
    if item.campaign_id != warehouse.campaign_id:
        raise ValidationError("Item e depósito devem pertencer à mesma campanha.")

    balance, _ = StockBalance.objects.select_for_update().get_or_create(
        item=item, warehouse=warehouse
    )
    if kind in {StockMovement.Kind.ENTRY, StockMovement.Kind.RETURN}:
        signed_quantity = quantity
    elif kind == StockMovement.Kind.EXIT:
        if balance.available_quantity < quantity:
            raise ValidationError("Saldo disponível insuficiente.")
        signed_quantity = -quantity
    else:
        raise ValidationError("Ajustes exigem um fluxo específico de aprovação.")

    balance.physical_quantity += signed_quantity
    balance.full_clean()
    balance.save(update_fields=["physical_quantity", "updated_at"])
    movement = StockMovement.objects.create(
        tenant=item.tenant,
        campaign=item.campaign,
        created_by=actor,
        item=item,
        warehouse=warehouse,
        kind=kind,
        signed_quantity=signed_quantity,
        reason=reason,
        origin_type=origin_type,
        origin_id=origin_id,
    )
    append_audit_event(
        actor=actor,
        tenant=item.tenant,
        campaign=item.campaign,
        action=f"stock.{kind}",
        resource_type="stock_movement",
        resource_id=movement.id,
        reason=reason,
        minimized_diff={"quantity": str(signed_quantity)},
    )
    enqueue_outbox_event(
        tenant=item.tenant,
        campaign=item.campaign,
        kind="stock.movement_recorded.v1",
        aggregate_type="stock_item",
        aggregate_id=item.id,
        payload_minimized={"movement_id": str(movement.id)},
    )
    return movement, balance
