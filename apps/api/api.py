from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from ninja import NinjaAPI
from ninja.security import django_auth

from apps.campaigns.models import Campaign
from apps.campaigns.services import campaigns_for_user, require_campaign_permission
from apps.core.models import AuditEvent
from apps.forms.models import FormVersion
from apps.forms.services import publish_form_version

from .schemas import (
    AuditEventOut,
    CampaignOut,
    MessageOut,
    ProblemOut,
    PublishFormIn,
    UserOut,
)


api = NinjaAPI(
    title="Nabio Elege API",
    version="1.0.0",
    urls_namespace="nabio-elege-api",
    auth=django_auth,
)


def request_id(request):
    return getattr(request, "request_id", None)


@api.exception_handler(PermissionDenied)
def permission_denied_handler(request, exc):
    return api.create_response(
        request,
        ProblemOut(
            type="about:blank",
            title="Acesso negado",
            status=403,
            code="permission_denied",
            detail=str(exc) or "Você não pode executar esta ação.",
            request_id=str(request_id(request)) if request_id(request) else None,
        ).dict(),
        status=403,
    )


@api.exception_handler(ValidationError)
def validation_error_handler(request, exc):
    field_errors = None
    if hasattr(exc, "message_dict"):
        field_errors = {
            field: [str(message) for message in messages]
            for field, messages in exc.message_dict.items()
        }
    return api.create_response(
        request,
        ProblemOut(
            type="about:blank",
            title="Regra de negócio inválida",
            status=422,
            code="validation_error",
            detail="; ".join(str(message) for message in exc.messages),
            request_id=str(request_id(request)) if request_id(request) else None,
            field_errors=field_errors,
        ).dict(),
        status=422,
    )


@api.get("/healthz", auth=None, response=MessageOut, tags=["system"])
def healthz(request):
    return {"message": "ok"}


@api.get("/v1/me", response=UserOut, tags=["context"])
def me(request):
    return request.user


@api.get("/v1/campaigns", response=list[CampaignOut], tags=["context"])
def list_campaigns(request):
    return campaigns_for_user(request.user).select_related("tenant").order_by("name")


def get_authorized_campaign(request, campaign_id):
    campaign = campaigns_for_user(request.user).filter(pk=campaign_id).first()
    if campaign is None:
        raise Http404
    return campaign


@api.get("/v1/campaigns/{campaign_id}", response=CampaignOut, tags=["context"])
def campaign_detail(request, campaign_id: UUID):
    return get_authorized_campaign(request, campaign_id)


@api.get(
    "/v1/campaigns/{campaign_id}/audit-events",
    response=list[AuditEventOut],
    tags=["audit"],
)
def list_audit_events(request, campaign_id: UUID):
    campaign = get_authorized_campaign(request, campaign_id)
    require_campaign_permission(request.user, campaign, "audit.read.campaign")
    return AuditEvent.objects.filter(campaign=campaign)[:100]


@api.post(
    "/v1/campaigns/{campaign_id}/forms/{form_version_id}/publish",
    response={200: CampaignOut, 404: ProblemOut},
    tags=["forms"],
)
def publish_form(request, campaign_id: UUID, form_version_id: UUID, payload: PublishFormIn):
    campaign = get_authorized_campaign(request, campaign_id)
    version = FormVersion.objects.filter(pk=form_version_id).select_related("form").first()
    if version is None or version.form.campaign_id != campaign.id:
        return 404, ProblemOut(
            type="about:blank",
            title="Não encontrado",
            status=404,
            code="not_found",
            detail="O recurso não existe ou não está disponível neste contexto.",
            request_id=str(request_id(request)) if request_id(request) else None,
        )
    form = publish_form_version(
        actor=request.user,
        form_version_id=form_version_id,
        expected_form_row_version=payload.expected_row_version,
        request_id=request_id(request),
    )
    return form.campaign
