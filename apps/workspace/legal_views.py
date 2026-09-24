from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.campaigns.models import Membership
from .legal_access import can_manage_access, change_case_access, visible_cases
from .views import campaign_context


@login_required
def case_access(request, campaign_id, object_id):
    context = campaign_context(request, campaign_id)
    campaign = context["campaign"]
    case = get_object_or_404(visible_cases(request.user, campaign), pk=object_id)
    if not can_manage_access(request.user, case):
        raise PermissionDenied
    if request.method == "POST":
        try:
            if request.POST.get("action") not in {"grant", "revoke"}:
                raise ValidationError("Ação inválida.")
            change_case_access(
                actor=request.user,
                campaign=campaign,
                case_id=case.pk,
                membership_id=request.POST.get("membership"),
                can_manage=request.POST.get("can_manage") == "on",
                revoke=request.POST.get("action") == "revoke",
                version=request.POST.get("row_version"),
                reason=request.POST.get("reason", ""),
            )
            messages.success(request, "Acesso ao caso atualizado.")
            if not can_manage_access(request.user, case):
                if visible_cases(request.user, campaign).filter(pk=case.pk).exists():
                    return redirect(
                        "module_detail",
                        campaign_id=campaign_id,
                        key="juridico",
                        object_id=object_id,
                    )
                return redirect("module_list", campaign_id=campaign_id, key="juridico")
            return redirect("case_access", campaign_id=campaign_id, object_id=object_id)
        except (ValidationError, ObjectDoesNotExist, ValueError):
            messages.error(
                request,
                "Não foi possível atualizar. Confira o vínculo, o motivo e mantenha um administrador ativo. Recarregue se o registro mudou.",
            )
        case.refresh_from_db()
    members = (
        Membership.objects.filter(
            campaign=campaign,
            status="active",
            revoked_at__isnull=True,
            user__is_active=True,
            role__permissions__code="legal.manage.campaign",
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .select_related("user")
    )
    context.update(
        title="Acessos do caso",
        active="juridico",
        case=case,
        case_members=members,
        grants=case.access_grants.select_related("membership__user"),
        writable=campaign.phase != "archived",
    )
    return render(request, "workspace/legal_access.html", context)
