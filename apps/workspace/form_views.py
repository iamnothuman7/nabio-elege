import hashlib
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.campaigns.services import require_campaign_permission
from apps.core.services import canonical_json_hash
from apps.forms.models import Form, FormVersion, PrivacyNoticeVersion, ProcessingPurpose, SourceLink
from apps.forms.public_services import IdempotencyConflict, PublicFormUnavailable, PublicFormVersionConflict, get_public_form, receive_public_submission
from apps.forms.services import publish_form_version
from .services import audit, check_independent, check_version, require_writable
from .ui_forms import PUBLIC_FIELDS, public_submission_form
from .views import campaign_context


@login_required
def form_builder(request, campaign_id, object_id):
    context = campaign_context(request, campaign_id)
    form = get_object_or_404(Form, campaign_id=campaign_id, pk=object_id)
    require_campaign_permission(request.user, form.campaign, "forms.create.campaign")
    if request.method == "POST":
        try:
            with transaction.atomic():
                Campaign.objects.select_for_update().get(pk=campaign_id)
                form = Form.objects.select_for_update().get(pk=object_id)
                require_writable(form.campaign)
                check_version(form, request.POST.get("row_version"))
                action = request.POST.get("action")
                if action == "draft":
                    purpose = form.purpose
                    selected = request.POST.getlist("fields")
                    if not {"adult_declaration", "consent", "message"}.issubset(selected):
                        raise ValidationError("Inclua declaração de maioridade, manifestação e mensagem.")
                    if any(name not in PUBLIC_FIELDS or name not in purpose.allowed_fields for name in selected):
                        raise ValidationError("Use somente campos aprovados para esta finalidade.")
                    notice = request.POST.get("notice", "").strip()
                    if len(notice) < 40 or len(notice) > 20000:
                        raise ValidationError("O aviso deve descrever a finalidade, o responsável, a retenção e o canal de direitos (40 a 20.000 caracteres).")
                    number = (form.versions.order_by("-version_number").values_list("version_number", flat=True).first() or 0) + 1
                    notice_number = (purpose.notice_versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
                    privacy_notice = PrivacyNoticeVersion.objects.create(purpose=purpose, version=notice_number, content=notice, content_hash=hashlib.sha256(notice.encode()).hexdigest())
                    schema = {"fields": [PUBLIC_FIELDS[name] for name in dict.fromkeys(selected)]}
                    FormVersion.objects.create(form=form, created_by=request.user, version_number=number, schema_json=schema, schema_hash=canonical_json_hash(schema), notice_version=privacy_notice, status="in_review")
                    form.save()
                    audit(request.user, form, "form.version_submitted", version=number)
                elif action == "approve":
                    require_campaign_permission(request.user, form.campaign, "forms.review.campaign")
                    check_independent(request.user, form)
                    check_independent(request.user, form.purpose)
                    version = FormVersion.objects.select_for_update().get(pk=request.POST.get("version"), form=form, status="in_review")
                    check_independent(request.user, version)
                    if not form.purpose.legal_basis_ref or form.purpose.retention_policy.status != "active":
                        raise ValidationError("A finalidade exige referência de base legal e retenção ativa.")
                    notice = version.notice_version
                    notice.status = "approved"
                    notice.approved_by = request.user
                    notice.approved_at = timezone.now()
                    notice.save()
                    version.status = "approved"
                    version.approved_by = request.user
                    version.approved_at = timezone.now()
                    version.save()
                    purpose = form.purpose
                    if purpose.status != "active":
                        purpose.status = "active"
                        purpose.save()
                    form.save()
                    audit(request.user, form, "form.version_approved", version=version.version_number)
                elif action == "publish":
                    version = get_object_or_404(FormVersion, pk=request.POST.get("version"), form=form)
                    publish_form_version(actor=request.user, form_version_id=version.pk, expected_form_row_version=form.row_version)
                elif action == "link":
                    if form.status != "published":
                        raise ValidationError("Publique o formulário antes de criar um link.")
                    link = SourceLink.objects.create(tenant=form.tenant, campaign=form.campaign, created_by=request.user, form=form, source_type="public", source_ref=request.POST.get("source_ref", "Site institucional")[:160])
                    form.save()
                    audit(request.user, form, "form.link_created", link_id=str(link.pk))
                elif action in {"pause", "close"}:
                    require_campaign_permission(request.user, form.campaign, "forms.publish.campaign")
                    if form.status not in {"published", "paused"}:
                        raise ValidationError("O formulário não está publicado ou pausado.")
                    form.status = "paused" if action == "pause" else "closed"
                    form.save()
                    audit(request.user, form, f"form.{form.status}")
                else:
                    raise ValidationError("Ação inválida.")
            messages.success(request, "Formulário atualizado.")
            return redirect("module_detail", campaign_id=campaign_id, key="formularios", object_id=object_id)
        except (ValidationError, FormVersion.DoesNotExist) as exc:
            messages.error(request, " ".join(exc.messages) if isinstance(exc, ValidationError) else "A versão não está mais disponível para essa ação.")
    context.update(title="Construtor de formulário", active="formularios", obj=form, field_options=[v for k, v in PUBLIC_FIELDS.items() if k in form.purpose.allowed_fields])
    return render(request, "workspace/builder.html", context)


def public_form_view(request, public_code):
    try:
        link, version = get_public_form(public_code)
    except PublicFormUnavailable:
        return render(request, "workspace/public_form.html", {"unavailable": True}, status=404)
    form = public_submission_form(version, request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST":
        try:
            presentation = signing.loads(request.POST.get("presentation", ""), salt="public-form", max_age=3600)
            if presentation["version"] != str(version.pk) or presentation["link"] != str(link.pk):
                raise PublicFormVersionConflict
            if request.POST.get("website"):
                raise ValidationError("Não foi possível receber este envio.")
            if form.is_valid():
                result, replayed = receive_public_submission(public_code=public_code, version_id=version.pk, fields=form.cleaned_data, idempotency_key=presentation["command"], request_id=getattr(request, "request_id", None))
                if getattr(settings, "LOCAL_DEMO", False):
                    from apps.forms.models import SubmissionReceipt
                    from apps.forms.processing import process_submission
                    receipt = SubmissionReceipt.objects.get(receipt_id=result["receipt_id"])
                    process_submission(submission_id=receipt.submission_id)
                return render(request, "workspace/public_form.html", {"result": result, "title": link.form.title})
        except (signing.BadSignature, PublicFormVersionConflict, IdempotencyConflict):
            form.add_error(None, "A página expirou ou foi atualizada. Confira os campos e envie novamente.")
            status = 409
        except (ValidationError, PublicFormUnavailable) as exc:
            form.add_error(None, " ".join(exc.messages) if isinstance(exc, ValidationError) else "Este formulário não está mais disponível.")
            status = 422
    presentation = signing.dumps({"version": str(version.pk), "link": str(link.pk), "command": str(uuid.uuid4())}, salt="public-form")
    return render(request, "workspace/public_form.html", {"form": form, "title": link.form.title, "notice": version.notice_version.content, "presentation": presentation}, status=status)
