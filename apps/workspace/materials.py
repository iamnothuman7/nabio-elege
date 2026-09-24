"""Simple manual ledger UI; the existing inventory service remains authoritative."""

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.campaigns.services import require_campaign_permission
from apps.core.models import IdempotencyRecord
from apps.core.services import canonical_json_hash
from apps.operations.models import StockItem, StockMovement, Warehouse
from apps.operations.services import apply_stock_movement
from .guidance import attach_guidance
from .services import require_writable


class MovementForm(forms.Form):
    item = forms.ModelChoiceField(label="Material", queryset=StockItem.objects.none())
    kind = forms.ChoiceField(
        label="O que aconteceu?",
        choices=[
            ("entry", "Entrada de material"),
            ("exit", "Saída de material"),
            ("return", "Devolução ao estoque"),
        ],
    )
    quantity = forms.DecimalField(
        label="Quantidade",
        min_value=Decimal("0.0001"),
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"step": "0.0001"}),
    )
    warehouse = forms.ModelChoiceField(
        label="Depósito", required=False, queryset=Warehouse.objects.none()
    )
    reason = forms.CharField(
        label="Observação",
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    command_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, campaign, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = StockItem.objects.filter(
            campaign=campaign
        ).order_by("name")
        self.fields["item"].label_from_instance = lambda item: (
            f"{item.name} · {item.unit}"
        )
        warehouses = Warehouse.objects.filter(campaign=campaign).order_by("name")
        self.fields["warehouse"].queryset = warehouses
        self.warehouse_count = warehouses.count()
        self.fields["warehouse"].required = self.warehouse_count > 1
        self.single_warehouse = (
            warehouses.first() if self.warehouse_count == 1 else None
        )
        if self.single_warehouse:
            self.fields["warehouse"].initial = self.single_warehouse.pk
        self.fields["command_id"].initial = uuid.uuid4()
        attach_guidance(self)


@transaction.atomic
def record_movement(*, actor, campaign, data):
    campaign = Campaign.objects.select_for_update().get(pk=campaign.pk)
    require_writable(campaign)
    require_campaign_permission(actor, campaign, "stock.manage.campaign")
    # Revalidate scoped choices inside the campaign lock, including depot count.
    form = MovementForm(data, campaign=campaign)
    if not form.is_valid():
        raise ValidationError("Confira o material, a quantidade e o depósito.")
    values = form.cleaned_data
    digest = canonical_json_hash(
        {
            name: str(values.get(name) or "")
            for name in ["item", "warehouse", "kind", "quantity", "reason"]
        }
        | {
            "item_id": str(values["item"].pk),
            "warehouse_id": str(values["warehouse"].pk) if values["warehouse"] else "",
        }
    )
    key_hash = hashlib.sha256(str(values["command_id"]).encode()).hexdigest()
    route = "workspace/materials/movement"
    existing = IdempotencyRecord.objects.filter(
        campaign=campaign,
        actor_scope=f"user:{actor.pk}",
        route=route,
        key_hash=key_hash,
    ).first()
    if existing:
        if existing.request_hash != digest:
            raise ValidationError(
                "Este envio já foi registrado com outros dados. Reabra a tela para fazer uma nova movimentação."
            )
        return False
    # Preserve old UI command IDs across a deployment.
    if StockMovement.objects.filter(
        campaign=campaign, origin_type="manual", origin_id=values["command_id"]
    ).exists():
        raise ValidationError(
            "Este comando já foi registrado. Consulte o histórico antes de enviar novamente."
        )
    warehouse = values["warehouse"] or form.single_warehouse
    if warehouse is None:
        warehouse = Warehouse.objects.create(
            tenant=campaign.tenant,
            campaign=campaign,
            created_by=actor,
            name="Estoque principal",
            code=f"principal-{uuid.uuid4().hex[:12]}",
        )
    movement, _ = apply_stock_movement(
        actor=actor,
        item_id=values["item"].pk,
        warehouse_id=warehouse.pk,
        kind=values["kind"],
        quantity=values["quantity"],
        reason=values["reason"]
        or {
            "entry": "Entrada manual de material",
            "exit": "Saída manual de material",
            "return": "Devolução manual de material",
        }[values["kind"]],
        origin_type="manual",
        origin_id=values["command_id"],
    )
    IdempotencyRecord.objects.create(
        tenant=campaign.tenant,
        campaign=campaign,
        actor_scope=f"user:{actor.pk}",
        route=route,
        key_hash=key_hash,
        request_hash=digest,
        status_code=201,
        result_ref={"object_id": str(movement.pk)},
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return True
