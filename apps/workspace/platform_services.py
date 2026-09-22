"""Explicit platform administration without bypassing campaign RLS."""

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.rls import database_scope
from apps.core.services import append_audit_event
from .models import SecurityProfile


def platform_audit(*, actor, **fields):
    with database_scope(actor=actor):
        return append_audit_event(actor=actor, **fields)


def require_platform_admin(actor):
    if not (
        actor.is_authenticated
        and actor.is_active
        and actor.is_staff
        and actor.is_superuser
    ):
        raise PermissionDenied("Área exclusiva da administração da plataforma.")


def account(username, password, *, administrator=False):
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError("Este usuário já existe. Nenhuma conta foi alterada.")
    user = User(username=username, is_staff=administrator, is_superuser=administrator)
    if not 12 <= len(password) <= 1024:
        raise ValidationError("Use uma senha inicial com pelo menos 12 caracteres.")
    validate_password(password, user)
    user.set_password(password)
    user.full_clean()
    user.save()
    SecurityProfile.objects.create(user=user, password_change_required=True)
    return user


@transaction.atomic
def create_customer(
    *,
    actor,
    organization,
    slug,
    campaign_name,
    username,
    password,
    election_id,
    office_code,
    jurisdiction_code,
    is_demo=False,
):
    require_platform_admin(actor)
    tenant = Tenant(name=organization, slug=slug)
    tenant.full_clean()
    tenant.save()
    campaign = Campaign(
        tenant=tenant,
        name=campaign_name,
        code="principal",
        election_id=election_id,
        office_code=office_code,
        jurisdiction_code=jurisdiction_code,
        is_demo=is_demo,
    )
    campaign.full_clean()
    campaign.save()
    role = Role.objects.create(
        tenant=tenant, code="customer-manager", name="Gestor do cliente"
    )
    role.permissions.set(Permission.objects.all())
    user = account(username, password)
    member = Membership.objects.create(
        user=user,
        tenant=tenant,
        campaign=campaign,
        role=role,
        status="active",
        invited_by=actor,
    )
    platform_audit(
        actor=actor,
        action="platform.customer_created",
        resource_type="tenant",
        resource_id=tenant.pk,
        minimized_diff={
            "campaign_id": str(campaign.pk),
            "user_id": user.pk,
            "demo": is_demo,
        },
    )
    return tenant, campaign, user, member


@transaction.atomic
def create_customer_access(*, actor, campaign, role, username, password):
    require_platform_admin(actor)
    campaign = Campaign.objects.select_related("tenant").get(pk=campaign.pk)
    role = Role.objects.get(pk=role.pk)
    if campaign.tenant.status != "active" or campaign.phase == "archived":
        raise ValidationError(
            "Selecione uma organização ativa e campanha não arquivada."
        )
    if role.tenant_id != campaign.tenant_id or role.code == "platform-operator":
        raise ValidationError("Escolha um papel de cliente da mesma organização.")
    user = account(username, password)
    Membership.objects.create(
        user=user,
        tenant=campaign.tenant,
        campaign=campaign,
        role=role,
        status="active",
        invited_by=actor,
    )
    platform_audit(
        actor=actor,
        action="platform.user_created",
        resource_type="user",
        resource_id=user.pk,
        minimized_diff={"campaign_id": str(campaign.pk), "role_id": str(role.pk)},
    )
    return user


@transaction.atomic
def open_campaign(*, actor, campaign):
    require_platform_admin(actor)
    if campaign.tenant.status != "active":
        raise ValidationError("Reative a organização antes de abrir a campanha.")
    role, _ = Role.objects.get_or_create(
        tenant=campaign.tenant,
        code="platform-operator",
        defaults={"name": "Administrador da plataforma"},
    )
    role.permissions.set(Permission.objects.all())
    Membership.objects.update_or_create(
        user=actor,
        campaign=campaign,
        defaults={
            "tenant": campaign.tenant,
            "role": role,
            "status": "active",
            "revoked_at": None,
            "expires_at": None,
        },
    )
    with database_scope(campaign=campaign, actor=actor):
        append_audit_event(
            actor=actor,
            tenant=campaign.tenant,
            campaign=campaign,
            action="platform.campaign_opened",
            resource_type="campaign",
            resource_id=campaign.pk,
            reason="Acesso administrativo explícito pelo painel da plataforma.",
        )
    platform_audit(
        actor=actor,
        action="platform.campaign_opened",
        resource_type="campaign",
        resource_id=campaign.pk,
    )


@transaction.atomic
def set_tenant_status(*, actor, tenant, status):
    require_platform_admin(actor)
    if status not in ("active", "suspended"):
        raise ValidationError("Status inválido.")
    tenant.status = status
    tenant.save(update_fields=["status", "updated_at"])
    platform_audit(
        actor=actor,
        action="platform.tenant_status_changed",
        resource_type="tenant",
        resource_id=tenant.pk,
        minimized_diff={"status": status},
    )


@transaction.atomic
def set_user_status(*, actor, user, active):
    require_platform_admin(actor)
    if user.pk == actor.pk or user.is_superuser or user.is_staff:
        raise ValidationError(
            "Contas administrativas não podem ser suspensas por esta ação."
        )
    user.is_active = active
    user.save(update_fields=["is_active"])
    profile, _ = SecurityProfile.objects.select_for_update().get_or_create(user=user)
    profile.session_version += 1
    profile.save(update_fields=["session_version"])
    platform_audit(
        actor=actor,
        action="platform.user_status_changed",
        resource_type="user",
        resource_id=user.pk,
        minimized_diff={"active": active},
    )
