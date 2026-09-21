"""Inventory transitions. Campaign locks serialize UI actions and worker cleanup."""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.core.services import append_audit_event
from apps.operations.models import StockBalance, StockItem, Warehouse
from apps.operations.services import apply_stock_movement, lock_stock_item
from .models import StockReservation, StockTransfer, StockTransferReceipt


def expire_item_reservations_locked(item, *, now=None):
    """Internal: caller must already hold this campaign and item lock."""
    now = now or timezone.now()
    count = 0
    reservations = StockReservation.objects.select_for_update().filter(
        campaign_id=item.campaign_id, item=item, status="active", expires_at__lte=now,
    ).order_by("warehouse_id", "id")
    for reservation in reservations:
        Warehouse.objects.select_for_update().get(pk=reservation.warehouse_id)
        balance = StockBalance.objects.select_for_update().get(item=item, warehouse_id=reservation.warehouse_id)
        balance.reserved_quantity -= reservation.quantity
        balance.full_clean()
        balance.save(update_fields=["reserved_quantity", "updated_at"])
        reservation.status = "expired"
        reservation.save()
        append_audit_event(actor=None, tenant=item.tenant, campaign=item.campaign,
                           action="stock.reservation_expired", resource_type="workspace.stockreservation",
                           resource_id=reservation.pk, reason="Prazo de reserva encerrado.",
                           minimized_diff={"quantity_released": str(reservation.quantity)})
        count += 1
    return count


def expire_due_reservations(*, limit=500, now=None):
    """Retry-safe periodic cleanup; archived and inactive campaigns stay untouched."""
    from apps.core.rls import current_scope, database_scope

    campaigns = Campaign.objects.filter(tenant__status="active").exclude(phase="archived").order_by("pk")
    if current_scope().campaign_id:
        campaigns = campaigns.filter(pk=current_scope().campaign_id)
    count = 0
    for campaign in campaigns.iterator():
        if count >= limit:
            break
        with database_scope(campaign=campaign):
            count += _expire_campaign_reservations(limit=limit - count, now=now)
    return count


def _expire_campaign_reservations(*, limit, now):
    from apps.core.rls import current_scope
    now = now or timezone.now()
    item_ids = list(StockReservation.objects.filter(
        status="active", expires_at__lte=now, campaign__tenant__status="active", campaign_id=current_scope().campaign_id,
    ).exclude(campaign__phase="archived").order_by("item_id").values_list("item_id", flat=True).distinct()[:limit])
    count = 0
    for item_id in item_ids:
        with transaction.atomic():
            campaign_id = StockItem.objects.values_list("campaign_id", flat=True).get(pk=item_id)
            campaign = Campaign.objects.select_for_update().get(pk=campaign_id)
            if campaign.phase == "archived" or campaign.tenant.status != "active":
                continue
            item = StockItem.objects.select_for_update().get(pk=item_id, campaign=campaign)
            item.campaign = campaign
            count += expire_item_reservations_locked(item, now=now)
    return count


def transfer_action(actor, obj, action, data, reason):
    """Called inside execute_action's permission/version/idempotency transaction."""
    lock_stock_item(actor=actor, item_id=obj.item_id)
    if action == "cancel" and obj.status == StockTransfer.Status.DRAFT:
        obj.status = StockTransfer.Status.CANCELLED
        obj.completed_at = timezone.now()
    elif action == "dispatch" and obj.status == StockTransfer.Status.DRAFT:
        apply_stock_movement(actor=actor, item_id=obj.item_id, warehouse_id=obj.source_warehouse_id,
                             kind="exit", quantity=obj.quantity, reason=reason,
                             origin_type="stock_transfer_dispatch", origin_id=obj.pk)
        obj.status = StockTransfer.Status.IN_TRANSIT
        obj.dispatched_at = timezone.now()
        obj.dispatched_by = actor
    elif action in {"receive_transfer", "return_transfer"} and obj.status == StockTransfer.Status.IN_TRANSIT:
        if actor.pk == obj.dispatched_by_id:
            raise ValidationError("Outra pessoa autorizada deve conferir o recebimento ou a devolução física.")
        evidence = data.get("evidence_reference", "").strip()
        if not 3 <= len(evidence) <= 180:
            raise ValidationError("Informe uma referência de comprovante entre 3 e 180 caracteres.")
        try:
            quantity = Decimal(str(data.get("quantity", "")))
            if not quantity.is_finite() or quantity <= 0 or quantity > obj.in_transit_quantity or quantity != quantity.quantize(Decimal("0.0001")):
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("A quantidade deve ser positiva, com até quatro casas decimais e não superar o saldo em trânsito.")
        returned = action == "return_transfer"
        movement, _ = apply_stock_movement(
            actor=actor, item_id=obj.item_id,
            warehouse_id=obj.source_warehouse_id if returned else obj.destination_warehouse_id,
            kind="return" if returned else "entry", quantity=quantity, reason=reason,
            origin_type="stock_transfer_return" if returned else "stock_transfer_receipt", origin_id=obj.pk,
        )
        StockTransferReceipt.objects.create(
            tenant=obj.tenant, campaign=obj.campaign, created_by=actor, transfer=obj,
            kind="return" if returned else "receive", quantity=quantity,
            evidence_reference=evidence, movement=movement,
        )
        if returned:
            obj.returned_quantity += quantity
        else:
            obj.received_quantity += quantity
        if obj.received_quantity + obj.returned_quantity == obj.quantity:
            obj.status = StockTransfer.Status.RETURNED if obj.returned_quantity else StockTransfer.Status.RECEIVED
            obj.completed_at = timezone.now()
    else:
        raise ValidationError("Esta ação não está disponível para a transferência.")
    obj.save()
