from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.campaigns.services import require_campaign_permission
from apps.operations.models import Task
from .models import CampaignBase, CampaignProfile, ElectorRegistration, FieldActivity, FieldAssignment, FieldWorker, Territory
from .registry import REGISTRY
from .views import campaign_context, scoped_queryset


def operational_map_data(context, territory_id=None):
    campaign = context["campaign"]
    permissions = context["permissions"]
    if "territories.read.campaign" not in permissions:
        return {"points": [], "has_field_access": False}
    bases = CampaignBase.objects.filter(campaign=campaign, status="active", public_location_confirmed=True).select_related("territory")
    if territory_id:
        bases = bases.filter(territory_id=territory_id)
    points = []
    for base in bases.order_by("name")[:500]:
        points.append({"id": str(base.pk), "name": base.name, "type": base.base_type, "type_label": base.get_base_type_display(), "latitude": float(base.latitude), "longitude": float(base.longitude), "territory": base.territory.name, "municipality": base.territory.municipality, "state": base.territory.state, "address": base.public_address, "accessible": base.accessible, "hours": base.opening_hours, "url": reverse("module_detail", args=[campaign.pk, "comites", base.pk])})
    activities = []
    if "field.manage.campaign" in permissions:
        queryset = FieldActivity.objects.filter(campaign=campaign, base__in=bases, status__in=["approved", "active"], ends_at__gte=timezone.now()).select_related("base").order_by("starts_at")[:100]
        for activity in queryset:
            activities.append({"id": str(activity.pk), "base_id": str(activity.base_id), "title": activity.title, "starts": timezone.localtime(activity.starts_at).strftime("%d/%m %H:%M"), "url": reverse("module_detail", args=[campaign.pk, "acoes-de-rua", activity.pk])})
    # Never add electors, contact details, home addresses or voting preferences here.
    return {"points": points, "activities": activities, "has_field_access": "field.manage.campaign" in permissions}


@login_required
def political_dashboard(request, campaign_id):
    context = campaign_context(request, campaign_id)
    campaign, permissions = context["campaign"], context["permissions"]
    profile = CampaignProfile.objects.filter(campaign=campaign).first()
    context.update(title="Central eleitoral", active="dashboard", profile=profile)
    context["election_days"] = max((profile.election_date - timezone.localdate()).days, 0) if profile and profile.election_date else None
    context["elector_count"] = scoped_queryset(REGISTRY["eleitores"], context).exclude(status="suppressed").count() if "electors.read.assigned" in permissions else None
    context["worker_count"] = FieldWorker.objects.filter(campaign=campaign, status="active").count() if "field.manage.campaign" in permissions else None
    context["territory_count"] = Territory.objects.filter(campaign=campaign, status="active").count() if "territories.read.campaign" in permissions else None
    context["committee_count"] = CampaignBase.objects.filter(campaign=campaign, status="active").count() if "territories.read.campaign" in permissions else None
    context["field_activities"] = FieldActivity.objects.filter(campaign=campaign, ends_at__gte=timezone.now()).exclude(status__in=["cancelled", "completed"]).select_related("territory", "base").order_by("starts_at")[:5] if "field.manage.campaign" in permissions else []
    context["field_workers"] = FieldWorker.objects.filter(campaign=campaign, status="active").select_related("territory").order_by("name")[:5] if "field.manage.campaign" in permissions else []
    context["tasks"] = Task.objects.filter(campaign=campaign).exclude(status__in=["completed", "cancelled"]).order_by("due_at")[:4] if "tasks.manage.campaign" in permissions else []
    context["territories"] = Territory.objects.filter(campaign=campaign, status="active").annotate(base_count=Count("campaignbase", distinct=True)).order_by("name")[:6] if "territories.read.campaign" in permissions else []
    context["map_data"] = operational_map_data(context)
    context["map_enabled"] = context["map_access"]
    request.maps_enabled = context["map_enabled"]
    return render(request, "workspace/political_dashboard.html", context)


@login_required
def campaign_map(request, campaign_id):
    context = campaign_context(request, campaign_id)
    require_campaign_permission(request.user, context["campaign"], "territories.read.campaign")
    territories = Territory.objects.filter(campaign_id=campaign_id, status="active").order_by("municipality", "name")
    territory_id = request.GET.get("territory", "")
    try:
        selected = territories.filter(pk=territory_id).first() if territory_id and len(territory_id) == 36 else None
    except ValidationError:
        selected = None
    data = operational_map_data(context, selected.pk if selected else None)
    context.update(title="Mapa da campanha", active="map", map_enabled=True, map_data=data, territories=territories, selected_territory=selected, points=data["points"])
    request.maps_enabled = True
    return render(request, "workspace/map.html", context)
