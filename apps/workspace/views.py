import csv
import json
import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, models, transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.debug import sensitive_post_parameters

from apps.campaigns.models import Campaign, CampaignPhaseEvent, Membership, Role
from apps.campaigns.services import campaigns_for_user, has_campaign_permission, membership_for, require_campaign_permission
from apps.core.crypto import hash_token
from apps.core.models import AuditEvent, Document, IdempotencyRecord
from apps.core.services import append_audit_event, canonical_json_hash
from apps.finance.models import AccountingBatch, BankEntry, BudgetVersion, Obligation, PaymentRecord
from apps.forms.models import Form, Person, ServiceRequest
from apps.operations.models import PurchaseItem, StockBalance, StockItem, StockMovement, Task, Warehouse
from .document_services import private_storage, require_document_access, rescan_document, upload_document
from .models import AssetBooking, ClosureItem, EditorialContent, Invitation, OfficialDataset, Reviewable, StockReservation
from .models import ElectorRegistration, FieldActivity, FieldAssignment, FieldWorker
from .models import StockTransfer, LegalCase
from .legal_access import restrict_queryset, require_object_access, initialize_case_access, can_manage_access, visible_audit_events
from .registry import LABELS, MODULES, REGISTRY
from .services import audit, can_edit, check_version, execute_action, import_aggregate_csv, prepare_create, require_writable, validate_booking
from .ui_forms import model_form_class


def campaign_context(request, campaign_id):
    campaign = get_object_or_404(campaigns_for_user(request.user).select_related("tenant"), pk=campaign_id)
    member = membership_for(request.user, campaign)
    permissions = set(member.role.permissions.values_list("code", flat=True))
    navigation = []
    for config in MODULES:
        if config.read not in permissions:
            continue
        group = next((g for g in navigation if g["name"] == config.group), None)
        if group is None:
            group = {"name": config.group, "modules": []}
            navigation.append(group)
        group["modules"].append(config)
    group_order = ["Campanha eleitoral", "Operação", "Financeiro", "Suprimentos", "Governança", "Relacionamento", "Conteúdo", "Inteligência administrativa"]
    navigation.sort(key=lambda group: group_order.index(group["name"]))
    return {"campaign": campaign, "member": member, "permissions": permissions, "navigation": navigation, "local_demo": getattr(settings, "LOCAL_DEMO", False), "team_access": "memberships.manage.campaign" in permissions, "audit_access": "audit.read.campaign" in permissions, "report_access": "reports.read.campaign" in permissions, "map_access": "territories.read.campaign" in permissions}


def config_for(context, key):
    config = REGISTRY.get(key)
    if config is None:
        raise Http404
    if config.read not in context["permissions"]:
        raise PermissionDenied
    return config


def scoped_queryset(config, context):
    qs = config.model.objects.filter(campaign=context["campaign"])
    if config.model is Person:
        qs = qs.filter(servicerequest__assignee=context["member"]).distinct()
    if config.model is ElectorRegistration and "electors.read.campaign" not in context["permissions"]:
        qs = qs.filter(owner=context["member"])
    if config.model is Document:
        classes = ["internal"] + [c for c in ["personal", "financial", "legal"] if f"documents.read_{c}.campaign" in context["permissions"]]
        qs = qs.filter(classification__in=classes)
    return restrict_queryset(qs, context["member"].user, context["campaign"])


def has_write(context, config):
    return config.write in context["permissions"] and context["campaign"].phase != "archived"


def user_error(request, exc):
    if isinstance(exc, ValidationError):
        messages.error(request, " ".join(exc.messages))
    else:
        messages.error(request, "O registro não está disponível, foi alterado ou o comando já foi utilizado. Recarregue a página.")


def home(request):
    if not request.user.is_authenticated:
        from .marketing_views import landing
        return landing(request)
    if request.user.is_active and request.user.is_staff and request.user.is_superuser:
        return redirect("platform_dashboard")
    campaigns = campaigns_for_user(request.user).select_related("tenant").order_by("name")
    if campaigns.count() == 1:
        return redirect("dashboard", campaign_id=campaigns.first().pk)
    return render(request, "workspace/campaigns.html", {"campaigns": campaigns})


@login_required
def dashboard(request, campaign_id):
    context = campaign_context(request, campaign_id)
    campaign = context["campaign"]
    permissions = context["permissions"]
    metrics, tasks, activity, events, pending = [], [], [], [], []
    if "tasks.manage.campaign" in permissions:
        open_tasks = Task.objects.filter(campaign=campaign).exclude(status__in=["completed", "cancelled"])
        metrics.append({"label": "Tarefas em aberto", "value": open_tasks.count(), "note": f"{open_tasks.filter(due_at__lt=timezone.now()).count()} com prazo vencido", "key": "tarefas"})
        tasks = open_tasks.select_related("assignee__user").order_by(models.F("due_at").asc(nulls_last=True), "created_at")[:6]
    if "finance.read.campaign" in permissions:
        obligations = Obligation.objects.filter(campaign=campaign).exclude(approval_status__in=["cancelled", "rejected"])
        amount = obligations.aggregate(value=models.Sum("amount_cents"))["value"] or 0
        metrics.append({"label": "Obrigações registradas", "value": currency(amount), "note": f"{obligations.filter(approval_status='submitted').count()} aguardando decisão", "key": "obrigacoes"})
        pending = list(obligations.filter(approval_status="submitted").order_by("created_at")[:4])
    if "stock.manage.campaign" in permissions:
        metrics.append({"label": "Itens de estoque", "value": StockItem.objects.filter(campaign=campaign).count(), "note": "Saldos por depósito", "key": "itens"})
    if "service.manage.campaign" in permissions:
        metrics.append({"label": "Atendimentos abertos", "value": ServiceRequest.objects.filter(campaign=campaign).exclude(status__in=["resolved", "closed"]).count(), "note": "Demandas administrativas", "key": "atendimentos"})
    if "events.manage.campaign" in permissions:
        from .models import CampaignEvent
        events = CampaignEvent.objects.filter(campaign=campaign, ends_at__gte=timezone.now()).exclude(status="cancelled").order_by("starts_at")[:4]
    if "audit.read.campaign" in permissions:
        activity = visible_audit_events(request.user, campaign).select_related("actor")[:6]
    context.update(title="Central de comando", active="dashboard", metrics=metrics, tasks=tasks, activity=activity, events=events, pending=pending)
    return render(request, "workspace/dashboard.html", context)


def currency(value):
    return "R$ " + f"{Decimal(value) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@login_required
def module_list(request, campaign_id, key):
    context = campaign_context(request, campaign_id)
    config = config_for(context, key)
    qs = scoped_queryset(config, context)
    sensitive_search = config.model is ElectorRegistration
    query = (request.POST.get("q", "") if sensitive_search else request.GET.get("q", "")).strip()[:254]
    status = (request.POST if sensitive_search and request.method == "POST" else request.GET).get("status", "")
    status_field = next((f for f in config.model._meta.fields if f.name in {"status", "approval_status", "verification_status", "condition"}), None)
    if query and config.search:
        criteria = models.Q()
        for field in config.search:
            criteria |= models.Q(**{f"{field}__icontains": query})
        qs = qs.filter(criteria)
    if query and config.model is ElectorRegistration:
        from apps.core.crypto import blind_index
        qs = qs.filter(person__contact_points__match_hmac=blind_index(query, campaign_id=campaign_id)).distinct()
    choices = status_field.choices if status_field and status_field.choices else []
    if status and status_field and status in dict(choices):
        qs = qs.filter(**{status_field.name: status})
    page = Paginator(qs.order_by("-created_at", "-id"), 25).get_page(request.POST.get("page") if sensitive_search and request.method == "POST" else request.GET.get("page"))
    context.update(title=config.title, config=config, active=key, page=page, query=query, sensitive_search=sensitive_search, selected_status=status, status_choices=choices, can_create=bool(config.fields) and has_write(context, config))
    if sensitive_search:
        append_audit_event(actor=request.user, tenant=context["campaign"].tenant, campaign=context["campaign"], action="elector.list_viewed", resource_type="elector_registration", resource_id="", minimized_diff={"page": page.number, "filtered": bool(query)})
    if config.model is StockItem:
        context["balances"] = StockBalance.objects.filter(item__campaign=context["campaign"]).select_related("item", "warehouse").order_by("item__name")[:100]
    return render(request, "workspace/list.html", context)


@login_required
@sensitive_post_parameters("registration_name", "registration_email", "registration_phone", "voter_title")
def module_edit(request, campaign_id, key, object_id=None):
    context = campaign_context(request, campaign_id)
    config = config_for(context, key)
    if not has_write(context, config) or not config.fields or (object_id and not config.editable):
        raise PermissionDenied
    instance = get_object_or_404(scoped_queryset(config, context), pk=object_id) if object_id else None
    if instance and not can_edit(instance):
        messages.error(request, "Este registro está protegido pelo fluxo de revisão e não pode ser editado.")
        return redirect("module_detail", campaign_id=campaign_id, key=key, object_id=instance.pk)
    form_cls = model_form_class(config)
    form = form_cls(request.POST if request.method == "POST" else None, instance=instance, campaign=context["campaign"], actor=request.user)
    if key == "territorios" and request.method == "GET" and not instance:
        from .address_lookup import UF_CODES
        uf, code = request.GET.get("uf", ""), request.GET.get("ibge", "")
        city = request.GET.get("municipio", "").strip()
        if uf in UF_CODES and len(code) == 7 and code.isascii() and code.isdigit() and code.startswith(UF_CODES[uf]) and 1 <= len(city) <= 120:
            form.initial.update(state=uf, municipality=city, ibge_code=code)
    if request.method == "POST":
        try:
            with transaction.atomic():
                locked_campaign = Campaign.objects.select_for_update().get(pk=campaign_id)
                require_writable(locked_campaign)
                require_campaign_permission(request.user, locked_campaign, config.write)
                if instance:
                    instance = config.model.objects.select_for_update().get(pk=object_id, campaign_id=campaign_id)
                    require_object_access(request.user, instance)
                    check_version(instance, request.POST.get("row_version"))
                    if not can_edit(instance):
                        raise ValidationError("Este registro não pode mais ser editado.")
                form = form_cls(request.POST, instance=instance, campaign=locked_campaign, actor=request.user)
                command = str(uuid.UUID(request.POST.get("command_id", "")))
                route = f"workspace/{key}/save/{object_id or 'new'}"
                hashed = hashlib.sha256(command.encode()).hexdigest()
                existing = IdempotencyRecord.objects.filter(campaign_id=campaign_id, actor_scope=f"user:{request.user.pk}", route=route, key_hash=hashed).first()
                if existing:
                    return redirect("module_detail", campaign_id=campaign_id, key=key, object_id=existing.result_ref["object_id"])
                if form.is_valid():
                    obj = form.save(commit=False)
                    if config.model is ElectorRegistration:
                        from apps.core.crypto import blind_index, encrypt_json
                        from apps.forms.models import ContactPoint
                        obj.source = "assisted"
                        voter_title = form.cleaned_data.get("voter_title")
                        obj.voter_title_ciphertext = encrypt_json({"value": voter_title}) if voter_title else None
                        obj.person = Person.objects.create(tenant=obj.tenant, campaign=obj.campaign, created_by=request.user, retention_policy=obj.purpose.retention_policy, display_name_ciphertext=encrypt_json({"value": form.cleaned_data["registration_name"]}))
                        for field, kind in [("registration_email", "email"), ("registration_phone", "phone")]:
                            value = form.cleaned_data.get(field)
                            if value:
                                ContactPoint.objects.create(person=obj.person, type=kind, value_ciphertext=encrypt_json({"value": value}), match_hmac=blind_index(value, campaign_id=campaign_id))
                    if not instance:
                        prepare_create(obj, request.user)
                    else:
                        validate_booking(obj)
                    if config.model is Document:
                        upload_document(request.user, obj, request.FILES.get("file"))
                    elif config.model is OfficialDataset:
                        import_aggregate_csv(obj, request.FILES.get("file"))
                    else:
                        obj.save()
                    if config.model is LegalCase and not instance:
                        initialize_case_access(obj, request.user)
                    audit(request.user, obj, f"{key}.{'updated' if instance else 'created'}", fields=list(config.fields))
                    IdempotencyRecord.objects.create(tenant=context["campaign"].tenant, campaign=context["campaign"], actor_scope=f"user:{request.user.pk}", route=route, key_hash=hashed, request_hash=canonical_json_hash({f: str(getattr(obj, f)) for f in config.fields}), status_code=201, result_ref={"object_id": str(obj.pk)}, expires_at=timezone.now() + timedelta(hours=24))
                    messages.success(request, "Registro salvo com sucesso.")
                    return redirect("module_detail", campaign_id=campaign_id, key=key, object_id=obj.pk)
        except (ValidationError, IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            if isinstance(exc, ValidationError):
                form.add_error(None, " ".join(exc.messages))
            else:
                form.add_error(None, "Não foi possível salvar. Confira os dados e recarregue a página.")
    context.update(title=("Editar " if instance else "Novo registro · ") + config.title, config=config, active=key, form=form, obj=instance, command_id=str(uuid.uuid4()), upload=config.model in {Document, OfficialDataset}, csv_upload=config.model is OfficialDataset)
    return render(request, "workspace/edit.html", context)


ACTION_LABELS = {"submit": "Enviar para revisão", "approve": "Aprovar", "reject": "Devolver / rejeitar", "start": "Iniciar", "complete": "Concluir", "cancel": "Cancelar", "block": "Bloquear", "review": "Enviar para conferência", "reopen": "Reabrir", "dependency": "Adicionar dependência", "allocate": "Alocar pagamento", "reverse": "Estornar registro", "reconcile": "Conciliar pagamento", "add_item": "Adicionar item", "receive": "Registrar recebimento", "release": "Liberar reserva", "consume": "Consumir reserva", "accept": "Aceitar custódia", "return": "Registrar devolução", "triage": "Iniciar triagem", "wait": "Aguardar pessoa", "resolve": "Resolver", "close": "Encerrar", "publication": "Registrar publicação externa"}


ACTION_LABELS.update({"add_line": "Adicionar linha de orçamento", "file": "Registrar protocolo externo"})
ACTION_LABELS.update({"dispatch": "Confirmar saída para transporte", "receive_transfer": "Conferir recebimento no destino", "return_transfer": "Conferir devolução à origem"})
ACTION_LABELS.update({"train": "Registrar capacitação", "pause": "Pausar integrante", "resume": "Reativar integrante", "confirm": "Confirmar escala", "checkin": "Registrar presença", "verify": "Conferir manifestação", "suppress": "Suprimir contato"})


def available_actions(obj):
    if isinstance(obj, StockTransfer):
        return {"draft": ["dispatch", "cancel"], "in_transit": ["receive_transfer", "return_transfer"]}.get(obj.status, [])
    if isinstance(obj, FieldWorker):
        return (["train"] if obj.training_status == "pending" else []) + (["pause"] if obj.status == "active" else ["resume"] if obj.status == "paused" else [])
    if isinstance(obj, FieldAssignment):
        return {"scheduled": ["confirm", "cancel"], "confirmed": ["checkin", "cancel"], "checked_in": ["complete"]}.get(obj.status, [])
    if isinstance(obj, ElectorRegistration):
        return {"pending": ["verify", "suppress"], "registered": ["suppress"]}.get(obj.status, [])
    if isinstance(obj, BudgetVersion):
        return ["add_line", "approve"] if obj.status == "draft" else []
    if isinstance(obj, AccountingBatch):
        return {"building": ["approve"], "exported": ["file"]}.get(obj.status, [])
    if isinstance(obj, Reviewable):
        actions = {"draft": ["submit", "cancel"], "in_review": ["approve", "reject", "cancel"], "approved": ["start", "cancel"], "active": ["complete", "cancel"]}.get(obj.status, [])
        if isinstance(obj, EditorialContent) and obj.status in {"approved", "active"}:
            actions = ["publication", "cancel"]
        return actions
    model = obj._meta.model_name
    if isinstance(obj, Task):
        return {"open": ["start", "dependency", "cancel"], "in_progress": ["block", "review", "cancel"], "blocked": ["start", "cancel"], "in_review": ["complete", "reopen"], "completed": ["reopen"]}.get(obj.status, [])
    if isinstance(obj, Obligation):
        return {"draft": ["submit"], "submitted": ["approve", "reject"]}.get(obj.approval_status, [])
    if isinstance(obj, PaymentRecord):
        return ["allocate", "reverse"] if obj.status != "reversed" else []
    if isinstance(obj, BankEntry):
        return ["reconcile"] if obj.amount_cents < 0 and obj.status != "reconciled" else []
    if model == "purchaserequest":
        return {"draft": ["add_item", "submit"], "submitted": ["approve", "reject"]}.get(obj.status, [])
    if model == "purchaseorder":
        return {"draft": ["approve"], "active": ["receive"], "partially_received": ["receive"]}.get(obj.status, [])
    if isinstance(obj, StockReservation):
        return ["release", "consume"] if obj.status == "active" else []
    if isinstance(obj, AssetBooking):
        return {"reserved": ["accept", "cancel"], "accepted": ["return"]}.get(obj.status, [])
    if isinstance(obj, ServiceRequest):
        return {"received": ["triage"], "triage": ["start"], "in_progress": ["wait", "resolve"], "waiting_person": ["start"], "resolved": ["close"]}.get(obj.status, [])
    if isinstance(obj, ClosureItem):
        return ["complete"] if not obj.completed_at else []
    if model == "financialreceipt":
        return ["approve"] if obj.status == "pending" else []
    if model == "inkindcontribution":
        return ["approve"] if not obj.reviewed else []
    return []


@login_required
def module_detail(request, campaign_id, key, object_id):
    context = campaign_context(request, campaign_id)
    config = config_for(context, key)
    obj = get_object_or_404(scoped_queryset(config, context), pk=object_id)
    actions = []
    if context["campaign"].phase != "archived":
        for action in available_actions(obj):
            permission = config.review if action in {"approve", "reject"} and config.review else config.write
            if permission in context["permissions"]:
                actions.append((action, ACTION_LABELS[action]))
    display_fields = list(dict.fromkeys([*config.fields, *config.columns, "created_at", "updated_at", "row_version"]))
    context.update(title=str(obj), config=config, active=key, obj=obj, display_fields=display_fields, actions=actions, can_edit=config.editable and has_write(context, config) and can_edit(obj), command_id=str(uuid.uuid4()))
    context["history"] = AuditEvent.objects.filter(campaign_id=campaign_id, resource_id=str(obj.pk))[:12] if context["audit_access"] else []
    if isinstance(obj, LegalCase):
        context["legal_access_manager"] = can_manage_access(request.user, obj)
        audit(request.user, obj, "legal.case_viewed")
    if isinstance(obj, ElectorRegistration):
        from apps.core.crypto import decrypt_json
        context["private_person"] = {"name": decrypt_json(obj.person.display_name_ciphertext).get("value", ""), "contacts": [{"type": c.get_type_display(), "value": decrypt_json(c.value_ciphertext).get("value", ""), "verification": c.get_verification_state_display()} for c in obj.person.contact_points.all()]}
        context["private_person"]["voter_title"] = decrypt_json(obj.voter_title_ciphertext).get("value", "") if obj.voter_title_ciphertext else ""
        audit(request.user, obj, "elector.registration_viewed")
    if isinstance(obj, FieldActivity):
        context["field_assignments"] = obj.assignments.select_related("worker")
    campaign = context["campaign"]
    if isinstance(obj, StockTransfer):
        context["transfer_receipts"] = obj.receipts.select_related("created_by").order_by("created_at")
        context["transfer_balances"] = StockBalance.objects.filter(item=obj.item, warehouse_id__in=[obj.source_warehouse_id, obj.destination_warehouse_id]).select_related("warehouse")
        context["display_fields"] += ["received_quantity", "returned_quantity", "dispatched_at", "dispatched_by", "completed_at"]
    if isinstance(obj, Task):
        context["dependencies"] = obj.dependencies.select_related("depends_on")
        context["task_options"] = Task.objects.filter(campaign=campaign).exclude(pk=obj.pk).order_by("title")[:200]
    if isinstance(obj, BudgetVersion):
        context["budget_lines"] = obj.lines.all()
    if isinstance(obj, AccountingBatch):
        context["filings"] = obj.filings.all()
        context["financial_documents"] = Document.objects.filter(campaign=campaign, classification="financial", status="available") if "documents.read_financial.campaign" in context["permissions"] else []
    if isinstance(obj, Person):
        from apps.core.crypto import decrypt_json
        context["private_person"] = {"name": decrypt_json(obj.display_name_ciphertext).get("value", ""), "contacts": [{"type": c.get_type_display(), "value": decrypt_json(c.value_ciphertext).get("value", ""), "verification": c.get_verification_state_display()} for c in obj.contact_points.all()]}
        audit(request.user, obj, "person.viewed_assigned")
    if isinstance(obj, ServiceRequest) and obj.submission_id and obj.assignee_id == context["member"].pk and "service.read_payload.assigned" in context["permissions"]:
        from apps.core.crypto import decrypt_json
        payload = decrypt_json(obj.submission.payload_ciphertext)
        context["private_request"] = {field: payload.get(field, "") for field in ("name", "email", "phone", "message")}
        audit(request.user, obj, "service.payload_viewed_assigned")
    if isinstance(obj, PaymentRecord):
        context["obligation_options"] = Obligation.objects.filter(campaign=campaign, approval_status="approved").order_by("description")[:200]
        context["allocations"] = obj.allocations.select_related("obligation")
    if isinstance(obj, BankEntry):
        context["payment_options"] = PaymentRecord.objects.filter(campaign=campaign).exclude(status="reversed").order_by("external_reference")[:200]
        context["reconciliations"] = obj.reconciliations.select_related("payment")
    if obj._meta.model_name in {"purchaserequest", "purchaseorder"}:
        context["purchase_items"] = obj.items.all() if obj._meta.model_name == "purchaserequest" else obj.purchase_request.items.all()
        context["stock_options"] = StockItem.objects.filter(campaign=campaign).order_by("name")[:200]
        context["warehouse_options"] = Warehouse.objects.filter(campaign=campaign).order_by("name")[:200]
    if isinstance(obj, Document):
        context["document_versions"] = obj.versions.order_by("-version_number")
        context["document_download"] = "documents.download.resource" in context["permissions"]
    if isinstance(obj, OfficialDataset):
        context["aggregate_rows"] = obj.results.order_by("geography_code", "metric")[:100]
    if isinstance(obj, Form):
        context["form_versions"] = obj.versions.select_related("notice_version").order_by("-version_number")
        context["source_links"] = obj.source_links.filter(revoked_at__isnull=True)
    return render(request, "workspace/detail.html", context)


@login_required
@require_POST
def module_action(request, campaign_id, key, object_id):
    context = campaign_context(request, campaign_id)
    config = config_for(context, key)
    get_object_or_404(scoped_queryset(config, context), pk=object_id)
    try:
        changed = execute_action(actor=request.user, campaign=context["campaign"], config=config, object_id=object_id, action=request.POST.get("action", ""), version=request.POST.get("row_version"), command_id=request.POST.get("command_id"), data=request.POST.dict())
        messages.success(request, "Ação concluída." if changed else "Este comando já foi concluído anteriormente.")
    except (ValidationError, ObjectDoesNotExist, IntegrityError, ValueError) as exc:
        user_error(request, exc)
    return redirect("module_detail", campaign_id=campaign_id, key=key, object_id=object_id)


@login_required
def stock_movement(request, campaign_id):
    context = campaign_context(request, campaign_id)
    require_campaign_permission(request.user, context["campaign"], "stock.manage.campaign")
    require_writable(context["campaign"])
    from .materials import MovementForm, record_movement
    form = MovementForm(request.POST if request.method == "POST" else None, campaign=context["campaign"])
    if request.method == "POST" and form.is_valid():
        try:
            changed = record_movement(actor=request.user, campaign=context["campaign"], data=request.POST)
            messages.success(request, "Movimentação registrada." if changed else "Este envio já foi registrado. O estoque não foi alterado novamente.")
            return redirect("stock_movement", campaign_id=campaign_id)
        except (ValidationError, ObjectDoesNotExist, IntegrityError, ValueError) as exc:
            form.add_error(None, " ".join(exc.messages) if isinstance(exc, ValidationError) else "Não foi possível registrar. Confira os dados e tente novamente.")
    balance_query = StockBalance.objects.filter(item__campaign_id=campaign_id).select_related("item", "warehouse").order_by("item__name", "warehouse__name")
    context.update(title="Materiais e estoque", active="materials", form=form, has_items=StockItem.objects.filter(campaign_id=campaign_id).exists(), balances=Paginator(balance_query, 20).get_page(request.GET.get("page")), stock_history=StockMovement.objects.filter(campaign_id=campaign_id).select_related("item", "warehouse").order_by("-created_at")[:10])
    return render(request, "workspace/stock.html", context)


@login_required
@require_POST
def stock_expire(request, campaign_id):
    context = campaign_context(request, campaign_id)
    from .inventory import expire_item_reservations_locked
    with transaction.atomic():
        campaign = Campaign.objects.select_for_update().get(pk=campaign_id)
        require_campaign_permission(request.user, campaign, "stock.manage.campaign")
        count = 0
        item_ids = StockReservation.objects.filter(campaign=campaign, status="active", expires_at__lte=timezone.now()).values_list("item_id", flat=True).distinct()
        for item in StockItem.objects.select_for_update().filter(pk__in=item_ids).order_by("pk"):
            count += expire_item_reservations_locked(item)
    messages.success(request, f"{count} reserva(s) vencida(s) liberada(s).")
    return redirect("module_list", campaign_id=campaign_id, key="reservas")


@login_required
def document_download(request, campaign_id, object_id, version_id):
    context = campaign_context(request, campaign_id)
    document = get_object_or_404(scoped_queryset(config_for(context, "documentos"), context), pk=object_id)
    require_document_access(request.user, document)
    version = get_object_or_404(document.versions, pk=version_id, scan_status="clean")
    if document.status != "available":
        raise Http404
    try:
        file = private_storage().open(version.storage_key, "rb")
    except FileNotFoundError:
        raise Http404
    digest = hashlib.sha256()
    for chunk in iter(lambda: file.read(65536), b""):
        digest.update(chunk)
    if digest.hexdigest() != version.sha256:
        file.close()
        raise PermissionDenied("A integridade do arquivo não pôde ser confirmada.")
    file.seek(0)
    audit(request.user, document, "document.downloaded", version=version.version_number)
    extension = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}.get(version.media_type, ".bin")
    return FileResponse(file, as_attachment=True, filename=f"documento-{str(document.pk)[:8]}-v{version.version_number}{extension}", content_type=version.media_type)


@login_required
@require_POST
def document_rescan(request, campaign_id, object_id):
    context = campaign_context(request, campaign_id)
    document = get_object_or_404(scoped_queryset(config_for(context, "documentos"), context), pk=object_id)
    require_writable(context["campaign"])
    try:
        result = rescan_document(request.user, document)
        messages.info(request, "Análise concluída." if result == "clean" else "Arquivo indisponível. Verifique a conexão com o antivírus; a quarentena permanece ativa.")
    except ValidationError as exc:
        user_error(request, exc)
    return redirect("module_detail", campaign_id=campaign_id, key="documentos", object_id=object_id)


@login_required
def audit_log(request, campaign_id):
    context = campaign_context(request, campaign_id)
    require_campaign_permission(request.user, context["campaign"], "audit.read.campaign")
    qs = visible_audit_events(request.user, context["campaign"]).select_related("actor")
    query = request.GET.get("q", "")[:100]
    if query:
        qs = qs.filter(action__icontains=query)
    context.update(title="Trilha de auditoria", active="audit", page=Paginator(qs, 50).get_page(request.GET.get("page")), query=query)
    return render(request, "workspace/audit.html", context)


@login_required
@require_POST
def accounting_export(request, campaign_id, object_id):
    context = campaign_context(request, campaign_id)
    require_campaign_permission(request.user, context["campaign"], "finance.export.campaign")
    with transaction.atomic():
        batch = get_object_or_404(AccountingBatch.objects.select_for_update(), pk=object_id, campaign_id=campaign_id)
        if batch.status not in {"reviewed", "exported", "delivered"} or canonical_json_hash(batch.manifest_json) != batch.manifest_hash:
            messages.error(request, "O dossiê precisa ser conferido e ter integridade válida antes da exportação.")
            return redirect("module_detail", campaign_id=campaign_id, key="contabilidade", object_id=object_id)
        if batch.status == "reviewed":
            require_writable(context["campaign"])
            batch.status = "exported"
            batch.save()
        audit(request.user, batch, "accounting.exported", manifest_hash=batch.manifest_hash)
    response = HttpResponse(json.dumps({"manifest": batch.manifest_json, "sha256": batch.manifest_hash}, ensure_ascii=False, sort_keys=True, indent=2), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="dossie-{batch.pk}.json"'
    return response


@login_required
@sensitive_post_parameters("password")
def team(request, campaign_id):
    context = campaign_context(request, campaign_id)
    campaign = context["campaign"]
    require_campaign_permission(request.user, campaign, "memberships.manage.campaign")
    roles = [role for role in Role.objects.filter(tenant=campaign.tenant).prefetch_related("permissions") if set(role.permissions.values_list("code", flat=True)).issubset(context["permissions"])]
    from .access_choices import AccessForm
    from .platform_services import create_selected_access
    access_form = AccessForm(request.POST if request.method == "POST" and request.POST.get("action") == "create_access" else None, allowed=context["permissions"])
    invitation_token = ""
    if request.method == "POST":
        try:
            with transaction.atomic():
                Campaign.objects.select_for_update().get(pk=campaign_id)
                require_writable(campaign)
                if request.POST.get("action") == "create_access":
                    if access_form.is_valid():
                        create_selected_access(actor=request.user, campaign=campaign, **access_form.cleaned_data)
                        messages.success(request, "Acesso criado com as permissões escolhidas. Entregue a senha inicial por um canal seguro.")
                        return redirect("team", campaign_id=campaign_id)
                elif request.POST.get("action") == "revoke":
                    member = Membership.objects.get(pk=request.POST.get("membership"), campaign=campaign)
                    if member.user_id == request.user.pk:
                        raise ValidationError("Peça a outro gestor para revogar o seu vínculo.")
                    member.revoke()
                    append_audit_event(actor=request.user, tenant=campaign.tenant, campaign=campaign, action="membership.revoked", resource_type="membership", resource_id=member.pk)
                    messages.success(request, "Vínculo revogado. O acesso à campanha foi encerrado.")
                elif request.POST.get("action") == "invite":
                    role = next((r for r in roles if str(r.pk) == request.POST.get("role")), None)
                    if role is None:
                        raise ValidationError("Você não pode delegar permissões que não possui.")
                    from django.contrib.auth.validators import UnicodeUsernameValidator
                    username = request.POST.get("username", "").strip()
                    UnicodeUsernameValidator()(username)
                    if not username or len(username) > 150:
                        raise ValidationError("Nome de usuário inválido.")
                    import secrets
                    invitation_token = secrets.token_urlsafe(32)
                    invitation = Invitation.objects.create(tenant=campaign.tenant, campaign=campaign, created_by=request.user, username=username, role=role, token_hash=hash_token(invitation_token), expires_at=timezone.now() + timedelta(hours=48))
                    audit(request.user, invitation, "membership.invited")
                else:
                    raise ValidationError("Ação inválida.")
        except (ValidationError, ObjectDoesNotExist, IntegrityError, ValueError) as exc:
            if request.POST.get("action") == "create_access":
                access_form.add_error(None, " ".join(exc.messages) if isinstance(exc, ValidationError) else "Não foi possível criar o acesso. Nenhuma criação parcial foi mantida.")
            else:
                user_error(request, exc)
    context.update(title="Equipe e acessos", active="team", members=Membership.objects.filter(campaign=campaign).select_related("user", "role").prefetch_related("role__permissions").order_by("user__username"), roles=roles, invitation_token=invitation_token, access_form=access_form)
    return render(request, "workspace/team.html", context)


REPORT_MODULES = {"tarefas", "obrigacoes", "pagamentos", "extrato", "arrecadacao", "estimaveis", "itens", "movimentos", "agenda", "encerramento"}


def csv_safe(value):
    text = str(value if value is not None else "")
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + text
    return text


@login_required
def reports(request, campaign_id):
    context = campaign_context(request, campaign_id)
    require_campaign_permission(request.user, context["campaign"], "reports.read.campaign")
    available = [c for c in MODULES if c.key in REPORT_MODULES and c.read in context["permissions"]]
    if request.method == "POST":
        require_campaign_permission(request.user, context["campaign"], "reports.export.campaign")
        config = next((c for c in available if c.key == request.POST.get("module")), None)
        if not config:
            raise PermissionDenied
        if config.group == "Financeiro":
            require_campaign_permission(request.user, context["campaign"], "finance.export.campaign")
        qs = scoped_queryset(config, context).order_by("created_at", "id")
        if qs.count() > 10000:
            messages.error(request, "O relatório excede 10.000 registros. É necessário um lote de exportação assíncrona.")
        else:
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="nabio-{config.key}-{timezone.now():%Y%m%d}.csv"'
            response.write("\ufeff")
            writer = csv.writer(response, delimiter=";")
            writer.writerow(["Campanha", "Extraído em", *[LABELS.get(field, field) for field in config.columns]])
            count = 0
            for obj in qs.iterator(chunk_size=500):
                writer.writerow([csv_safe(context["campaign"].code), timezone.now().isoformat(), *[csv_safe(getattr(obj, field)) for field in config.columns]])
                count += 1
            append_audit_event(actor=request.user, tenant=context["campaign"].tenant, campaign=context["campaign"], action="report.exported", resource_type=config.model._meta.label_lower, resource_id="", minimized_diff={"rows": count, "columns": list(config.columns)})
            return response
    context.update(title="Relatórios", active="reports", report_modules=available)
    return render(request, "workspace/reports.html", context)


@login_required
@require_POST
def campaign_phase(request, campaign_id):
    context = campaign_context(request, campaign_id)
    require_campaign_permission(request.user, context["campaign"], "closure.manage.campaign")
    try:
        with transaction.atomic():
            campaign = Campaign.objects.select_for_update().get(pk=campaign_id)
            require_writable(campaign)
            check_version(campaign, request.POST.get("row_version"))
            reason = request.POST.get("reason", "").strip()
            if len(reason) < 5:
                raise ValidationError("Informe o motivo da mudança de fase.")
            target = {"preparation": "operation", "operation": "closing", "closing": "archived"}[campaign.phase]
            if target == "archived":
                if StockTransfer.objects.filter(campaign=campaign, status__in=["draft", "in_transit"]).exists():
                    raise ValidationError("Conclua as transferências de materiais antes de arquivar a campanha.")
                blockers = [not ClosureItem.objects.filter(campaign=campaign).exists(), ClosureItem.objects.filter(campaign=campaign, completed_at__isnull=True).exists(), Task.objects.filter(campaign=campaign).exclude(status__in=["completed", "cancelled"]).exists(), Obligation.objects.filter(campaign=campaign).exclude(approval_status__in=["cancelled", "rejected"]).annotate(paid=models.Sum("payment_allocations__amount_cents", filter=~models.Q(payment_allocations__payment__status="reversed"))).filter(models.Q(paid__isnull=True) | models.Q(paid__lt=models.F("amount_cents"))).exists(), StockReservation.objects.filter(campaign=campaign, status="active").exists(), AssetBooking.objects.filter(campaign=campaign, status__in=["reserved", "accepted"]).exists(), ServiceRequest.objects.filter(campaign=campaign).exclude(status="closed").exists(), Form.objects.filter(campaign=campaign, status="published").exists()]
                if any(blockers):
                    raise ValidationError("Há pendências: confira checklist, tarefas, obrigações, reservas, custódias, atendimentos e formulários publicados.")
            CampaignPhaseEvent.objects.create(campaign=campaign, from_phase=campaign.phase, to_phase=target, reason=reason, changed_by=request.user)
            campaign.phase = target
            campaign.save()
            append_audit_event(actor=request.user, tenant=campaign.tenant, campaign=campaign, action="campaign.phase_changed", resource_type="campaign", resource_id=campaign.pk, reason=reason, minimized_diff={"phase": target})
        messages.success(request, "Fase da campanha atualizada.")
    except (ValidationError, KeyError) as exc:
        user_error(request, exc)
    return redirect("module_list", campaign_id=campaign_id, key="encerramento")
