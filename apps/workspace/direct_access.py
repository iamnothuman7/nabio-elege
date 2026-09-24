"""Owner-authorized password-only access and isolated demo-to-customer transition."""

from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Role, Tenant
from apps.core.rls import database_scope
from .models import CampaignProfile, SecurityProfile
from .platform_services import platform_audit, require_platform_admin
from .security import PASSWORD_ONLY_GROUP


@transaction.atomic
def prepare_direct_access(
    *,
    admin_username,
    customer_username,
    new_customer_username,
    admin_password,
    customer_password,
    tenant_slug,
    customer_name,
):
    users = {
        user.username: user
        for user in User.objects.select_for_update()
        .filter(username__in=[admin_username, customer_username])
        .order_by("pk")
    }
    if len(users) != 2 or admin_password == customer_password:
        raise ValidationError("Selecione duas contas existentes e senhas distintas.")
    admin, customer = users[admin_username], users[customer_username]
    require_platform_admin(admin)
    if not customer.is_active or customer.is_staff or customer.is_superuser:
        raise ValidationError(
            "A conta de origem deve ser um cliente ativo sem privilégios globais."
        )
    if not customer_name.strip() or len(customer_name) > 150:
        raise ValidationError("Informe o nome do cliente, com até 150 caracteres.")
    if (
        User.objects.exclude(pk=customer.pk)
        .filter(username__iexact=new_customer_username)
        .exists()
    ):
        raise ValidationError("O novo nome de usuário já está ocupado.")
    memberships = list(Membership.objects.select_for_update().filter(user=customer))
    if len(memberships) != 1 or not memberships[0].is_effective:
        raise ValidationError(
            "A conversão exige um único vínculo ativo de demonstração."
        )
    old_member = memberships[0]
    old_campaign = Campaign.objects.select_for_update().get(pk=old_member.campaign_id)
    if not old_campaign.is_demo or old_member.role.code == "platform-operator":
        raise ValidationError(
            "A origem deve ser uma demonstração, sem papel de administrador."
        )
    customer.username = new_customer_username
    customer.first_name = customer_name
    for user, password in ((admin, admin_password), (customer, customer_password)):
        if not isinstance(password, str) or not 20 <= len(password) <= 1024:
            raise ValidationError("Use senhas distintas de 20 a 1024 caracteres.")
        validate_password(password, user)
        user.full_clean()

    # The synthetic tenant and all its records remain unchanged and recoverable.
    # The real customer starts empty, without inventing election/location details.
    tenant = Tenant(name=customer_name, slug=tenant_slug)
    tenant.full_clean()
    tenant.save()
    campaign = Campaign(
        tenant=tenant,
        code="principal",
        name=f"Campanha de {customer_name}",
        election_id="A_CONFIGURAR",
        office_code="a-configurar",
        jurisdiction_code="A_CONFIGURAR",
        is_demo=False,
    )
    campaign.full_clean()
    campaign.save()
    role = Role.objects.create(
        tenant=tenant, code="customer-manager", name="Gestor do cliente"
    )
    role.permissions.set(old_member.role.permissions.all())
    Membership.objects.create(
        user=customer,
        tenant=tenant,
        campaign=campaign,
        role=role,
        status="active",
        invited_by=admin,
    )
    with database_scope(campaign=campaign, actor=customer):
        CampaignProfile.objects.create(
            tenant=tenant,
            campaign=campaign,
            created_by=customer,
            candidate_name=customer_name,
            campaign_region="A definir pela equipe",
        )
    old_member.revoke()
    group, _ = Group.objects.get_or_create(name=PASSWORD_ONLY_GROUP)
    if group.permissions.exists():
        raise ValidationError(
            "O grupo de política de acesso não pode conceder permissões."
        )
    for user, password in ((admin, admin_password), (customer, customer_password)):
        user.set_password(password)
        user.save(update_fields=["username", "first_name", "password"])
        profile, _ = SecurityProfile.objects.select_for_update().get_or_create(
            user=user
        )
        profile.password_change_required = False
        profile.password_changed_at = timezone.now()
        profile.session_version += 1
        profile.enabled_at = None
        profile.totp_secret_ciphertext = b""
        profile.recovery_hashes = []
        profile.last_counter = -1
        profile.failures = 0
        profile.locked_until = None
        profile.save()
        user.groups.add(group)
        platform_audit(
            actor=admin,
            action="security.password_only_access_configured",
            resource_type="user",
            resource_id=user.pk,
            reason="Acesso direto e nova senha definitiva solicitados pelo proprietário.",
            minimized_diff={"sessions_revoked": True, "mfa_optional": True},
        )
    platform_audit(
        actor=admin,
        action="platform.demo_customer_converted",
        resource_type="user",
        resource_id=customer.pk,
        minimized_diff={
            "previous_campaign_id": str(old_campaign.pk),
            "new_campaign_id": str(campaign.pk),
            "synthetic_records_preserved": True,
        },
    )
    return campaign
