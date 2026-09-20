from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from .models import Campaign, Membership


def active_memberships(user):
    if not user.is_authenticated or not user.is_active:
        return Membership.objects.none()
    return Membership.objects.filter(
        user=user,
        status=Membership.Status.ACTIVE,
        revoked_at__isnull=True,
        tenant__status="active",
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))


def campaigns_for_user(user):
    if not user.is_authenticated:
        return Campaign.objects.none()
    return Campaign.objects.filter(memberships__in=active_memberships(user)).distinct()


def membership_for(user, campaign):
    if not user.is_authenticated:
        return None
    return (
        active_memberships(user)
        .filter(campaign=campaign, tenant=campaign.tenant)
        .select_related("role", "campaign", "tenant")
        .prefetch_related("role__permissions")
        .first()
    )


def has_campaign_permission(user, campaign, permission_code):
    membership = membership_for(user, campaign)
    if membership is None:
        return False
    return membership.role.permissions.filter(code=permission_code).exists()


def require_campaign_permission(user, campaign, permission_code):
    if campaign.phase == "archived" and not any(part in permission_code for part in (".read", ".export.", ".download.", "privacy.handle")):
        raise PermissionDenied("A campanha arquivada está em modo somente leitura.")
    membership = membership_for(user, campaign)
    if membership is None or not membership.role.permissions.filter(
        code=permission_code
    ).exists():
        raise PermissionDenied("Acesso não autorizado para esta campanha.")
    return membership
