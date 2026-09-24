"""Explicit per-case access, always in addition to campaign permissions."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models.functions import Cast
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership
from apps.campaigns.services import (
    active_memberships,
    membership_for,
    require_campaign_permission,
)
from apps.core.models import AuditEvent, Document
from apps.core.services import append_audit_event
from .models import LegalCase, LegalCaseAccess, Occurrence


def active_grants():
    return LegalCaseAccess.objects.filter(
        revoked_at__isnull=True,
        membership__status="active",
        membership__revoked_at__isnull=True,
        membership__user__is_active=True,
        membership__tenant__status="active",
        membership__role__permissions__code="legal.manage.campaign",
    ).filter(
        models.Q(membership__expires_at__isnull=True)
        | models.Q(membership__expires_at__gt=timezone.now())
    )


def visible_cases(actor, campaign):
    memberships = active_memberships(actor).filter(
        campaign=campaign, tenant=campaign.tenant
    )
    return LegalCase.objects.filter(
        campaign=campaign,
        pk__in=active_grants()
        .filter(membership__in=memberships)
        .values("legal_case_id"),
    )


def blocked_document_ids(actor, campaign):
    # A document shared by several cases requires access to EVERY linked case.
    return (
        LegalCase.objects.filter(campaign=campaign, restricted_document__isnull=False)
        .exclude(pk__in=visible_cases(actor, campaign).values("pk"))
        .values("restricted_document_id")
    )


def restrict_queryset(qs, actor, campaign):
    if qs.model is LegalCase:
        qs = qs.filter(pk__in=visible_cases(actor, campaign).values("pk"))
    if qs.model is Document:
        return qs.exclude(pk__in=blocked_document_ids(actor, campaign))
    for field in qs.model._meta.fields:
        if isinstance(field, models.ForeignKey) and field.related_model is LegalCase:
            qs = qs.filter(
                models.Q(**{field.name + "__isnull": True})
                | models.Q(**{field.name + "__in": visible_cases(actor, campaign)})
            )
        if isinstance(field, models.ForeignKey) and field.related_model is Document:
            qs = qs.exclude(
                **{field.name + "__in": blocked_document_ids(actor, campaign)}
            )
    return qs


def require_object_access(actor, obj):
    if not restrict_queryset(
        type(obj).objects.filter(pk=obj.pk), actor, obj.campaign
    ).exists():
        raise PermissionDenied("Registro indisponível para este acesso.")


def visible_audit_events(actor, campaign):
    events = AuditEvent.objects.filter(campaign=campaign)
    for model in [LegalCase, Occurrence, Document]:
        visible = restrict_queryset(
            model.objects.filter(campaign=campaign), actor, campaign
        )
        ids = visible.annotate(text_id=Cast("pk", models.CharField())).values("text_id")
        events = events.exclude(
            models.Q(resource_type=model._meta.label_lower)
            & ~models.Q(resource_id__in=ids)
        )
    return events


def can_manage_access(actor, case):
    member = membership_for(actor, case.campaign)
    return bool(
        member
        and active_grants()
        .filter(legal_case=case, membership=member, can_manage_access=True)
        .exists()
    )


def initialize_case_access(case, actor):
    member = require_campaign_permission(actor, case.campaign, "legal.manage.campaign")
    LegalCaseAccess.objects.create(
        tenant=case.tenant,
        campaign=case.campaign,
        created_by=actor,
        legal_case=case,
        membership=member,
        can_manage_access=True,
    )
    if case.responsible_id and case.responsible_id != member.pk:
        LegalCaseAccess.objects.create(
            tenant=case.tenant,
            campaign=case.campaign,
            created_by=actor,
            legal_case=case,
            membership=case.responsible,
        )


@transaction.atomic
def change_case_access(
    *, actor, campaign, case_id, membership_id, can_manage, revoke, version, reason
):
    from .services import check_version, require_writable

    campaign = Campaign.objects.select_for_update().get(pk=campaign.pk)
    require_writable(campaign)
    require_campaign_permission(actor, campaign, "legal.manage.campaign")
    case = LegalCase.objects.select_for_update().get(pk=case_id, campaign=campaign)
    require_object_access(actor, case)
    if not can_manage_access(actor, case):
        raise PermissionDenied("Você não pode administrar os acessos deste caso.")
    check_version(case, version)
    reason = str(reason).strip()
    if not 3 <= len(reason) <= 500:
        raise ValidationError(
            "Informe um motivo administrativo entre 3 e 500 caracteres, sem dados do caso."
        )
    target = Membership.objects.get(
        pk=membership_id, campaign=campaign, tenant=campaign.tenant
    )
    if not revoke and (
        not active_memberships(target.user).filter(pk=target.pk).exists()
        or not target.role.permissions.filter(code="legal.manage.campaign").exists()
    ):
        raise ValidationError("Selecione um vínculo ativo com permissão jurídica.")
    grant = LegalCaseAccess.objects.filter(legal_case=case, membership=target).first()
    if grant and grant.can_manage_access and (revoke or not can_manage):
        if (
            not active_grants()
            .filter(legal_case=case, can_manage_access=True)
            .exclude(pk=grant.pk)
            .exists()
        ):
            raise ValidationError(
                "Mantenha ao menos um administrador ativo para este caso."
            )
    if grant is None:
        if revoke:
            raise ValidationError("Este vínculo não possui acesso ao caso.")
        grant = LegalCaseAccess(
            tenant=case.tenant,
            campaign=case.campaign,
            created_by=actor,
            legal_case=case,
            membership=target,
        )
    grant.can_manage_access = (
        bool(can_manage) if not revoke else grant.can_manage_access
    )
    grant.revoked_at = timezone.now() if revoke else None
    grant.save()
    case.save()
    append_audit_event(
        actor=actor,
        tenant=case.tenant,
        campaign=case.campaign,
        action="legal.access_revoked" if revoke else "legal.access_granted",
        resource_type=case._meta.label_lower,
        resource_id=case.pk,
        minimized_diff={
            "membership_id": str(target.pk),
            "can_manage_access": grant.can_manage_access,
        },
        reason=reason,
    )
    return grant
