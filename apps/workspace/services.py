import csv
import hashlib
import io
import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.campaigns.services import require_campaign_permission
from apps.core.models import Document, IdempotencyRecord
from apps.core.services import append_audit_event, canonical_json_hash
from apps.finance.models import AccountingBatch, BankEntry, BudgetLine, BudgetVersion, FilingRecord, Obligation, PaymentRecord
from apps.finance.services import allocate_payment, decide_obligation, reconcile_bank_entry, submit_obligation
from apps.forms.models import Form, ProcessingPurpose, ServiceRequest
from apps.operations.models import PurchaseItem, PurchaseOrder, StockBalance, StockMovement, Task
from apps.operations.services import add_task_dependency, apply_stock_movement
from .models import AggregateResult, AssetBooking, BrandAsset, CampaignEvent, ClosureItem, EditorialContent, ElectionShift, LogisticsTrip, Occurrence, PurchaseReceipt, Reviewable, ReviewDecision, StockReservation
from .models import ElectorRegistration, FieldActivity, FieldAssignment, FieldWorker


def require_writable(campaign):
    if campaign.phase == Campaign.Phase.ARCHIVED or campaign.tenant.status != "active":
        raise ValidationError("Esta campanha está em modo somente leitura.")


def audit(actor, obj, action, reason="", **diff):
    append_audit_event(actor=actor, tenant=obj.tenant, campaign=obj.campaign, action=action, resource_type=obj._meta.label_lower, resource_id=obj.pk, reason=reason, minimized_diff=diff)


def check_version(obj, version):
    if str(obj.row_version) != str(version):
        raise ValidationError("O registro mudou desde que você abriu a página. Recarregue antes de continuar.")


def check_independent(actor, obj):
    if obj.created_by_id == actor.pk:
        raise ValidationError("A aprovação final deve ser realizada por outra pessoa autorizada.")


def can_edit(obj):
    if isinstance(obj, FieldAssignment):
        return obj.status == "scheduled"
    if isinstance(obj, AssetBooking):
        return obj.status == "reserved"
    if isinstance(obj, ServiceRequest):
        return obj.status != "closed"
    if isinstance(obj, BudgetVersion):
        return obj.status == "draft" and not obj.lines.exists()
    if isinstance(obj, Reviewable):
        return obj.status == "draft"
    if isinstance(obj, Obligation):
        return obj.approval_status == "draft"
    if isinstance(obj, Form):
        return obj.status == "draft"
    if isinstance(obj, ProcessingPurpose):
        return obj.status == "draft"
    if isinstance(obj, ClosureItem):
        return not obj.completed_at
    if obj._meta.model_name in {"purchaserequest", "purchaseorder"}:
        return obj.status == "draft"
    if obj._meta.model_name == "financialreceipt":
        return obj.status == "pending"
    if obj._meta.model_name == "inkindcontribution":
        return not obj.reviewed
    return True


def validate_booking(obj):
    if isinstance(obj, FieldAssignment):
        if obj.activity.status not in {"approved", "active"}:
            raise ValidationError("A ação precisa estar aprovada antes de montar a escala.")
        if obj.worker.training_status != "completed" and obj.activity.activity_type != "training":
            raise ValidationError("Conclua a capacitação do integrante antes de escalá-lo.")
        if FieldAssignment.objects.filter(worker=obj.worker, status__in=["scheduled", "confirmed", "checked_in"], activity__starts_at__lt=obj.activity.ends_at, activity__ends_at__gt=obj.activity.starts_at).exclude(pk=obj.pk).exists():
            raise ValidationError("O integrante já está escalado para outra ação nesse horário.")
    if isinstance(obj, AssetBooking) and obj.status in {"reserved", "accepted"}:
        if obj.asset.condition != "available":
            raise ValidationError("O bem não está disponível para reserva.")
        if obj.asset.document_due and obj.asset.document_due < obj.ends_at.date():
            raise ValidationError("O documento do bem vence antes do final da reserva.")
        if AssetBooking.objects.filter(asset=obj.asset, status__in=["reserved", "accepted"], starts_at__lt=obj.ends_at, ends_at__gt=obj.starts_at).exclude(pk=obj.pk).exists():
            raise ValidationError("O bem já está reservado nesse período.")
        if LogisticsTrip.objects.filter(vehicle=obj.asset, status__in=["approved", "active"], departure_at__lt=obj.ends_at, return_at__gt=obj.starts_at).exists():
            raise ValidationError("O bem já está reservado para uma viagem nesse período.")
    if isinstance(obj, LogisticsTrip) and obj.status in {"approved", "active"}:
        if obj.vehicle.condition != "available":
            raise ValidationError("O veículo não está disponível.")
        if obj.vehicle.document_due and obj.vehicle.document_due < obj.return_at.date():
            raise ValidationError("A documentação vence antes do retorno.")
        overlap = LogisticsTrip.objects.filter(campaign=obj.campaign, status__in=["approved", "active"], departure_at__lt=obj.return_at, return_at__gt=obj.departure_at).exclude(pk=obj.pk)
        if overlap.filter(models.Q(vehicle=obj.vehicle) | models.Q(driver=obj.driver)).exists():
            raise ValidationError("Veículo ou motorista com viagem sobreposta.")
        if AssetBooking.objects.filter(asset=obj.vehicle, status__in=["reserved", "accepted"], starts_at__lt=obj.return_at, ends_at__gt=obj.departure_at).exists():
            raise ValidationError("O veículo já possui uma reserva patrimonial.")
    if isinstance(obj, ElectionShift) and obj.responsible_id and obj.status in {"approved", "active"}:
        if ElectionShift.objects.filter(campaign=obj.campaign, responsible=obj.responsible, status__in=["approved", "active"], starts_at__lt=obj.ends_at, ends_at__gt=obj.starts_at).exclude(pk=obj.pk).exists():
            raise ValidationError("O responsável já possui uma escala nesse período.")


def quantity_value(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0 or result >= Decimal("100000000000000") or result != result.quantize(Decimal("0.0001")):
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Informe quantidade positiva com até quatro casas decimais.")


def reserve_stock(obj):
    obj.quantity = quantity_value(obj.quantity)
    if obj.expires_at <= timezone.now():
        raise ValidationError("A reserva precisa expirar no futuro.")
    # Same lock order as apply_stock_movement, including reservations created via forms.
    type(obj.item).objects.select_for_update().get(pk=obj.item_id)
    type(obj.warehouse).objects.select_for_update().get(pk=obj.warehouse_id)
    balance, _ = StockBalance.objects.select_for_update().get_or_create(item=obj.item, warehouse=obj.warehouse)
    if balance.available_quantity < obj.quantity:
        raise ValidationError("Saldo disponível insuficiente para a reserva.")
    balance.reserved_quantity += obj.quantity
    balance.full_clean()
    balance.save()


def prepare_create(obj, actor):
    if isinstance(obj, AccountingBatch):
        if obj.cutoff_at > timezone.now():
            raise ValidationError("A data de corte não pode estar no futuro.")
        def snapshot(queryset, fields):
            return [{key: str(value) if isinstance(value, uuid.UUID) or hasattr(value, "isoformat") else value for key, value in row.items()} for row in queryset.order_by("id").values(*fields)]
        obligations = Obligation.objects.filter(campaign=obj.campaign, created_at__lte=obj.cutoff_at)
        payments = PaymentRecord.objects.filter(campaign=obj.campaign, paid_at__lte=obj.cutoff_at)
        obj.manifest_json = {"schema": "nabio.accounting.v1", "campaign_id": str(obj.campaign_id), "cutoff_at": obj.cutoff_at.isoformat(), "generated_at": timezone.now().isoformat(), "official_filing": False, "obligations": snapshot(obligations, ["id", "origin_type", "origin_id", "amount_cents", "currency", "approval_status", "documentation_status"]), "payments": snapshot(payments, ["id", "amount_cents", "currency", "paid_at", "status"])}
        from apps.finance.models import PaymentAllocation, ReconciliationLink
        obj.manifest_json["allocations"] = snapshot(PaymentAllocation.objects.filter(payment__in=payments, created_at__lte=obj.cutoff_at), ["id", "payment_id", "obligation_id", "amount_cents"])
        obj.manifest_json["reconciliations"] = snapshot(ReconciliationLink.objects.filter(payment__in=payments, created_at__lte=obj.cutoff_at), ["id", "payment_id", "entry_id", "amount_cents", "reversed_at"])
        obj.manifest_hash = canonical_json_hash(obj.manifest_json)
    if isinstance(obj, Obligation):
        obj.origin_type = "manual"
        obj.origin_id = uuid.uuid4()
    if isinstance(obj, BankEntry):
        obj.original_line_hash = canonical_json_hash({"account": str(obj.account_id), "id": obj.external_id, "date": obj.occurred_at.isoformat(), "amount": obj.amount_cents})
    if isinstance(obj, StockReservation):
        reserve_stock(obj)
    validate_booking(obj)


def review_action(actor, obj, action, reason):
    transitions = {("draft", "submit"): "in_review", ("in_review", "approve"): "approved", ("in_review", "reject"): "draft", ("approved", "start"): "active", ("active", "complete"): "completed"}
    if action == "cancel" and obj.status not in {"completed", "cancelled"}:
        target = "cancelled"
    else:
        target = transitions.get((obj.status, action))
    if not target:
        raise ValidationError("Esta ação não está disponível no estado atual.")
    if action == "approve":
        check_independent(actor, obj)
        if isinstance(obj, BrandAsset) and not obj.document_id:
            raise ValidationError("Associe um documento antes da aprovação.")
        for field in ("document", "restricted_document"):
            doc = getattr(obj, field, None)
            if doc and doc.status != Document.Status.AVAILABLE:
                raise ValidationError("O documento precisa passar pela verificação antivírus.")
        digest = canonical_json_hash({field.name: str(field.value_from_object(obj)) for field in obj._meta.fields if field.name not in {"updated_at", "row_version", "status"}})
        ReviewDecision.objects.create(tenant=obj.tenant, campaign=obj.campaign, created_by=actor, resource_type=obj._meta.label_lower, resource_id=obj.pk, resource_version=obj.row_version, content_hash=digest, decision="approved", reason=reason)
        if isinstance(obj, EditorialContent):
            obj.approved_hash = canonical_json_hash({"body": obj.body, "rights": obj.rights_reference})
        if isinstance(obj, Occurrence):
            obj.verification = "verified"
    if isinstance(obj, EditorialContent) and action == "complete" and not obj.publication_url:
        raise ValidationError("Registre a URL da publicação externa antes de concluir.")
    if isinstance(obj, CampaignEvent) and action == "cancel":
        for booking in AssetBooking.objects.filter(event=obj, status="reserved"):
            booking.status = "cancelled"
            booking.save()
            audit(actor, booking, "asset_booking.event_cancelled", reason)
    if isinstance(obj, FieldActivity):
        if action == "complete" and obj.assignments.exclude(status__in=["completed", "cancelled"]).exists():
            raise ValidationError("Conclua ou cancele as escalas antes de encerrar a ação.")
        if action == "cancel":
            if obj.assignments.filter(status="checked_in").exists():
                raise ValidationError("Encerre a presença dos integrantes antes de cancelar.")
            for assignment in obj.assignments.filter(status__in=["scheduled", "confirmed"]):
                assignment.status = "cancelled"
                assignment.save()
                audit(actor, assignment, "field_assignment.activity_cancelled", reason)
    obj.status = target
    validate_booking(obj)
    obj.save()


def task_action(obj, action, reason):
    transitions = {("open", "start"): "in_progress", ("blocked", "start"): "in_progress", ("in_progress", "block"): "blocked", ("in_progress", "review"): "in_review", ("in_review", "complete"): "completed", ("completed", "reopen"): "open", ("in_review", "reopen"): "open"}
    target = transitions.get((obj.status, action))
    if action == "cancel" and obj.status not in {"cancelled", "completed"}:
        target = "cancelled"
    if not target:
        raise ValidationError("Transição de tarefa não permitida.")
    if action in {"start", "complete"} and obj.dependencies.exclude(depends_on__status="completed").exists():
        raise ValidationError("Conclua as dependências antes de avançar.")
    if action == "complete" and obj.evidence_document_id and obj.evidence_document.status != "available":
        raise ValidationError("A evidência precisa estar disponível e verificada.")
    obj.status = target
    obj.save()


def purchase_action(actor, obj, action, data, reason):
    if obj._meta.model_name == "purchaserequest":
        if action == "add_item" and obj.status == "draft":
            stock_item = None
            if data.get("stock_item"):
                from apps.operations.models import StockItem
                stock_item = StockItem.objects.get(pk=data["stock_item"], campaign=obj.campaign)
            unit = data.get("unit", "").strip()
            if not unit or not data.get("description", "").strip():
                raise ValidationError("Informe a descrição e a unidade do item.")
            if stock_item and stock_item.unit != unit:
                raise ValidationError("A unidade deve coincidir com a do item de estoque.")
            item = PurchaseItem(request=obj, description=data["description"], quantity=quantity_value(data.get("quantity")), unit=unit, stock_item=stock_item)
            item.full_clean()
            item.save()
            obj.save()
            return
        transitions = {("draft", "submit"): "submitted", ("submitted", "approve"): "approved", ("submitted", "reject"): "rejected"}
        target = transitions.get((obj.status, action))
        if not target or not obj.items.exists():
            raise ValidationError("Inclua os itens e confira o estado da solicitação.")
        if action in {"approve", "reject"}:
            check_independent(actor, obj)
        obj.status = target
        obj.save()
        return
    if action == "approve" and obj.status == "draft":
        check_independent(actor, obj)
        if obj.purchase_request.status != "approved" or obj.supplier.status != "active":
            raise ValidationError("O pedido exige uma solicitação aprovada e fornecedor ativo.")
        obj.status = "active"
        obj.save()
        Obligation.objects.create(tenant=obj.tenant, campaign=obj.campaign, created_by=actor, origin_type="purchase_order", origin_id=obj.pk, creditor_ref=obj.supplier.name, description=f"Pedido {str(obj.pk)[:8]}", amount_cents=obj.amount_cents)
        return
    if action == "receive" and obj.status in {"active", "partially_received"}:
        require_campaign_permission(actor, obj.campaign, "purchases.receive.campaign")
        item = PurchaseItem.objects.get(pk=data.get("item"), request=obj.purchase_request)
        quantity = quantity_value(data.get("quantity"))
        received = obj.receipts.filter(item=item).aggregate(total=models.Sum("quantity"))["total"] or Decimal("0")
        if received + quantity > item.quantity:
            raise ValidationError("O recebimento supera a quantidade contratada.")
        from apps.operations.models import Warehouse
        warehouse = Warehouse.objects.get(pk=data.get("warehouse"), campaign=obj.campaign) if item.stock_item_id else None
        receipt = PurchaseReceipt.objects.create(tenant=obj.tenant, campaign=obj.campaign, created_by=actor, order=obj, item=item, warehouse=warehouse, quantity=quantity, evidence_reference=data.get("evidence_reference", ""))
        if item.stock_item_id:
            apply_stock_movement(actor=actor, item_id=item.stock_item_id, warehouse_id=warehouse.pk, kind="entry", quantity=quantity, reason="Recebimento de pedido", origin_type="purchase_receipt", origin_id=receipt.pk)
        complete = all((obj.receipts.filter(item=i).aggregate(total=models.Sum("quantity"))["total"] or 0) >= i.quantity for i in obj.purchase_request.items.all())
        obj.status = "received" if complete else "partially_received"
        obj.save()
        return
    raise ValidationError("Ação não disponível para esta compra.")


def run_domain_action(actor, config, obj, action, data, reason):
    if isinstance(obj, FieldWorker):
        if action == "train" and obj.training_status == "pending":
            obj.training_status = "completed"
        elif action == "pause" and obj.status == "active":
            if obj.assignments.filter(status__in=["scheduled", "confirmed", "checked_in"]).exists():
                raise ValidationError("Finalize ou cancele as escalas pendentes antes de pausar.")
            obj.status = "paused"
        elif action == "resume" and obj.status == "paused":
            obj.status = "active"
        else:
            raise ValidationError("Ação indisponível para este integrante.")
        obj.save()
    elif isinstance(obj, FieldAssignment):
        transitions = {("scheduled", "confirm"): "confirmed", ("confirmed", "checkin"): "checked_in", ("checked_in", "complete"): "completed", ("scheduled", "cancel"): "cancelled", ("confirmed", "cancel"): "cancelled"}
        target = transitions.get((obj.status, action))
        if not target:
            raise ValidationError("Transição de escala não permitida.")
        if action in {"confirm", "checkin"} and (obj.worker.status != "active" or obj.activity.status not in {"approved", "active"}):
            raise ValidationError("Integrante ou ação indisponível.")
        if action == "checkin":
            if not obj.activity.starts_at - timezone.timedelta(hours=2) <= timezone.now() <= obj.activity.ends_at:
                raise ValidationError("A presença pode ser registrada entre duas horas antes do início e o fim da ação.")
            obj.checked_in_at = timezone.now()
        if action == "complete":
            obj.completed_at = timezone.now()
        obj.status = target
        obj.save()
    elif isinstance(obj, ElectorRegistration):
        if action == "verify" and obj.status == "pending":
            require_campaign_permission(actor, obj.campaign, "electors.review.campaign")
            check_independent(actor, obj)
            obj.status = "registered"
            obj.consent_verified_at = timezone.now()
        elif action == "suppress" and obj.status != "suppressed":
            require_campaign_permission(actor, obj.campaign, "privacy.handle.campaign")
            from apps.forms.models import Suppression
            for contact in obj.person.contact_points.all():
                Suppression.objects.get_or_create(tenant=obj.tenant, campaign=obj.campaign, purpose=obj.purpose, contact_hmac=contact.match_hmac, defaults={"created_by": actor, "reason": "Solicitação administrativa de supressão", "source_request_id": str(obj.pk)})
            obj.status = "suppressed"
        else:
            raise ValidationError("Ação indisponível para este cadastro.")
        obj.save()
    elif isinstance(obj, BudgetVersion):
        if action == "add_line" and obj.status == "draft":
            from apps.finance.services import positive_cents
            line = BudgetLine(budget_version=obj, cost_center=data.get("cost_center", ""), funding_source=data.get("funding_source", ""), amount_cents=positive_cents(data.get("amount_cents")))
            line.full_clean()
            line.save()
            obj.save()
        elif action == "approve" and obj.status == "draft" and obj.lines.exists():
            check_independent(actor, obj)
            for previous in BudgetVersion.objects.filter(campaign=obj.campaign, status="approved"):
                previous.status = "superseded"
                previous.save()
            obj.status = "approved"
            obj.approved_by = actor
            obj.save()
        else:
            raise ValidationError("Inclua as linhas antes da aprovação independente do orçamento.")
    elif isinstance(obj, AccountingBatch):
        if action == "approve" and obj.status == "building":
            check_independent(actor, obj)
            if canonical_json_hash(obj.manifest_json) != obj.manifest_hash:
                raise ValidationError("O manifesto não passou na verificação de integridade.")
            obj.status = "reviewed"
            obj.save()
        elif action == "file" and obj.status == "exported":
            require_campaign_permission(actor, obj.campaign, "finance.approve.campaign")
            document = Document.objects.get(pk=data.get("evidence_document"), campaign=obj.campaign, status="available", classification="financial")
            from .document_services import require_document_access
            require_document_access(actor, document)
            filing = FilingRecord(batch=obj, protocol_ref=data.get("protocol_ref", ""), delivered_at=timezone.now(), evidence_document=document)
            filing.full_clean()
            filing.save()
            obj.status = "delivered"
            obj.save()
        else:
            raise ValidationError("O dossiê precisa ser conferido e exportado antes do registro de entrega externa.")
    elif isinstance(obj, Reviewable):
        if action == "publication" and isinstance(obj, EditorialContent) and obj.status in {"approved", "active"}:
            from django.core.validators import URLValidator
            url = data.get("publication_url", "")
            URLValidator(schemes=["https"])(url)
            if obj.approved_hash != canonical_json_hash({"body": obj.body, "rights": obj.rights_reference}):
                raise ValidationError("O conteúdo foi alterado após aprovação.")
            obj.publication_url = url
            obj.published_at = timezone.now()
            obj.status = "completed"
            obj.save()
        else:
            review_action(actor, obj, action, reason)
    elif isinstance(obj, Task):
        if action == "dependency":
            predecessor = Task.objects.get(pk=data.get("depends_on"), campaign=obj.campaign)
            add_task_dependency(actor=actor, task_id=obj.pk, depends_on_id=predecessor.pk)
            obj.save()
        else:
            task_action(obj, action, reason)
    elif isinstance(obj, Obligation):
        if action == "submit":
            submit_obligation(actor=actor, obligation_id=obj.pk, expected_version=obj.row_version)
        elif action in {"approve", "reject"}:
            decide_obligation(actor=actor, obligation_id=obj.pk, expected_version=obj.row_version, decision="approved" if action == "approve" else "rejected", reason=reason)
        else:
            raise ValidationError("Ação inválida.")
    elif isinstance(obj, PaymentRecord):
        if action == "allocate":
            obligation = Obligation.objects.get(pk=data.get("obligation"), campaign=obj.campaign)
            allocate_payment(actor=actor, payment_id=obj.pk, obligation_id=obligation.pk, amount_cents=data.get("amount_cents"))
            obj.save()
        elif action == "reverse" and obj.status != "reversed":
            links = obj.reconciliations.filter(reversed_at__isnull=True)
            for link in links:
                link.reversed_at = timezone.now()
                link.reason = reason
                link.save()
                entry = BankEntry.objects.select_for_update().get(pk=link.entry_id)
                total = entry.reconciliations.filter(reversed_at__isnull=True).aggregate(total=models.Sum("amount_cents"))["total"] or 0
                entry.status = "partial" if total else "unreconciled"
                entry.save()
            obj.status = "reversed"
            obj.save()
        else:
            raise ValidationError("Ação inválida.")
    elif isinstance(obj, BankEntry):
        if action != "reconcile":
            raise ValidationError("Ação inválida.")
        payment = PaymentRecord.objects.get(pk=data.get("payment"), campaign=obj.campaign)
        reconcile_bank_entry(actor=actor, entry_id=obj.pk, payment_id=payment.pk, amount_cents=data.get("amount_cents"))
    elif obj._meta.model_name in {"purchaserequest", "purchaseorder"}:
        purchase_action(actor, obj, action, data, reason)
    elif isinstance(obj, StockReservation):
        if action not in {"release", "consume"} or obj.status != "active":
            raise ValidationError("Esta reserva não está ativa.")
        type(obj.item).objects.select_for_update().get(pk=obj.item_id)
        type(obj.warehouse).objects.select_for_update().get(pk=obj.warehouse_id)
        balance = StockBalance.objects.select_for_update().get(item=obj.item, warehouse=obj.warehouse)
        if action == "consume" and obj.expires_at <= timezone.now():
            raise ValidationError("A reserva expirou. Libere o saldo.")
        balance.reserved_quantity -= obj.quantity
        balance.full_clean()
        balance.save()
        if action == "consume":
            apply_stock_movement(actor=actor, item_id=obj.item_id, warehouse_id=obj.warehouse_id, kind="exit", quantity=obj.quantity, reason=reason, origin_type="reservation", origin_id=obj.pk)
        obj.status = "consumed" if action == "consume" else "released"
        obj.save()
    elif isinstance(obj, AssetBooking):
        transitions = {("reserved", "accept"): "accepted", ("accepted", "return"): "returned", ("reserved", "cancel"): "cancelled"}
        target = transitions.get((obj.status, action))
        if not target:
            raise ValidationError("Transição não permitida.")
        if action == "accept" and obj.custodian.user_id != actor.pk:
            raise ValidationError("Somente o custodiante pode aceitar a responsabilidade.")
        obj.status = target
        if action == "return":
            obj.return_condition = reason
        obj.save()
    elif isinstance(obj, ServiceRequest):
        transitions = {("received", "triage"): "triage", ("triage", "start"): "in_progress", ("in_progress", "wait"): "waiting_person", ("waiting_person", "start"): "in_progress", ("in_progress", "resolve"): "resolved", ("resolved", "close"): "closed"}
        target = transitions.get((obj.status, action))
        if not target or (action == "resolve" and not obj.resolution_summary):
            raise ValidationError("Confira o estado e registre um resumo antes de resolver.")
        obj.status = target
        obj.save()
    elif isinstance(obj, ClosureItem):
        if action != "complete" or obj.completed_at or not obj.evidence_reference:
            raise ValidationError("Informe a evidência antes de concluir um item pendente.")
        obj.completed_at = timezone.now()
        obj.completed_by = actor
        obj.save()
    elif obj._meta.model_name in {"financialreceipt", "inkindcontribution"}:
        if action != "approve":
            raise ValidationError("Ação inválida.")
        check_independent(actor, obj)
        if obj._meta.model_name == "financialreceipt":
            if obj.status != "pending" or not obj.documentation_ref:
                raise ValidationError("Receita pendente exige referência documental.")
            obj.status = "reviewed"
        else:
            if obj.reviewed:
                raise ValidationError("Esta contribuição já foi revisada.")
            obj.reviewed = True
        obj.save()
    else:
        raise ValidationError("Ação não implementada para este registro.")


@transaction.atomic
def execute_action(*, actor, campaign, config, object_id, action, version, command_id, data):
    Campaign.objects.select_for_update().get(pk=campaign.pk)
    require_writable(campaign)
    permission = config.review if action in {"approve", "reject"} and config.review else config.write
    require_campaign_permission(actor, campaign, permission)
    try:
        uuid.UUID(command_id)
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Comando inválido. Recarregue a página.")
    route = f"workspace/{config.key}/{object_id}/{action}"
    key_hash = hashlib.sha256(command_id.encode()).hexdigest()
    digest = canonical_json_hash(dict(data))
    existing = IdempotencyRecord.objects.filter(campaign=campaign, actor_scope=f"user:{actor.pk}", route=route, key_hash=key_hash).first()
    if existing:
        if existing.request_hash != digest:
            raise ValidationError("Este comando já foi usado com outro conteúdo.")
        return False
    obj = config.model.objects.select_for_update().get(pk=object_id, campaign=campaign)
    if isinstance(obj, ElectorRegistration) and obj.owner.user_id != actor.pk:
        require_campaign_permission(actor, campaign, "electors.read.campaign")
    check_version(obj, version)
    reason = data.get("reason", "").strip()
    if len(reason) < 3 or len(reason) > 500:
        raise ValidationError("Registre um motivo entre 3 e 500 caracteres, sem dados pessoais.")
    run_domain_action(actor, config, obj, action, data, reason)
    audit(actor, obj, f"{config.key}.{action}", reason)
    from datetime import timedelta
    IdempotencyRecord.objects.create(tenant=campaign.tenant, campaign=campaign, actor_scope=f"user:{actor.pk}", route=route, key_hash=key_hash, request_hash=digest, status_code=200, result_ref={"object_id": str(obj.pk)}, expires_at=timezone.now() + timedelta(hours=24))
    return True


def import_aggregate_csv(dataset, uploaded):
    if not uploaded or uploaded.size > 2 * 1024 * 1024:
        raise ValidationError("Envie um CSV UTF-8 com até 2 MB.")
    raw = uploaded.read()
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames != ["geography_code", "geography_name", "metric", "value", "denominator"]:
            raise ValidationError("Cabeçalho esperado: geography_code,geography_name,metric,value,denominator")
        rows = []
        keys = set()
        for line, row in enumerate(reader, start=2):
            if line > 10001:
                raise ValidationError("Limite de 10.000 linhas por base.")
            if row["metric"] not in {"electorate", "turnout", "abstentions", "valid_votes", "blank_votes", "null_votes"}:
                raise ValidationError(f"Linha {line}: métrica agregada não permitida.")
            if not row["value"].isdigit() or (row["denominator"] and not row["denominator"].isdigit()):
                raise ValidationError(f"Linha {line}: valores devem ser inteiros não negativos.")
            denominator = int(row["denominator"]) if row["denominator"] else None
            if denominator is not None and (denominator <= 0 or int(row["value"]) > denominator):
                raise ValidationError(f"Linha {line}: denominador inválido.")
            key = (row["geography_code"], row["metric"])
            if key in keys:
                raise ValidationError(f"Linha {line}: dimensão duplicada.")
            keys.add(key)
            result = AggregateResult(dataset=dataset, geography_code=row["geography_code"], geography_name=row["geography_name"], metric=row["metric"], value=int(row["value"]), denominator=denominator)
            result.full_clean(exclude=["dataset"])
            rows.append(result)
    except (UnicodeDecodeError, csv.Error, KeyError, TypeError, AttributeError, ValueError):
        raise ValidationError("Arquivo inválido. Use o modelo CSV indicado.")
    if not rows:
        raise ValidationError("A base precisa conter ao menos uma linha.")
    dataset.file_hash = hashlib.sha256(raw).hexdigest()
    dataset.row_count = len(rows)
    dataset.save()
    AggregateResult.objects.bulk_create(rows)
