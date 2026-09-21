import hashlib
import json
import uuid
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.campaigns.models import Campaign
from apps.campaigns.services import require_campaign_permission
from apps.core.models import IdempotencyRecord
from apps.core.services import append_audit_event, canonical_json_hash
from .geography import GeographyUnavailable, public_geography
from .models import Territory
from .services import require_writable
from .views import campaign_context


@login_required
@require_GET
def geography_layer(request, campaign_id, kind, code):
    context = campaign_context(request, campaign_id)
    require_campaign_permission(
        request.user, context["campaign"], "territories.read.campaign"
    )
    try:
        return JsonResponse(public_geography(kind, code))
    except ValueError:
        return JsonResponse({"detail": "Camada inválida."}, status=400)
    except GeographyUnavailable:
        return JsonResponse(
            {
                "detail": "O IBGE não respondeu. Tente novamente; seus cadastros continuam disponíveis."
            },
            status=503,
        )


@login_required
@require_POST
def create_map_area(request, campaign_id):
    context = campaign_context(request, campaign_id)
    if len(request.body) > 25000:
        return JsonResponse(
            {"detail": "O contorno excede o tamanho permitido."}, status=400
        )
    try:
        payload = json.loads(request.body)
        command = str(uuid.UUID(payload.pop("command_id")))
        if set(payload) != {
            "name",
            "area_kind",
            "municipality",
            "state",
            "ibge_code",
            "boundary",
            "source_reference",
            "public_area_confirmed",
        }:
            raise ValueError
        if payload["public_area_confirmed"] is not True:
            raise ValidationError(
                "Confirme que a área é pública e não identifica residência ou pessoa."
            )
        if (
            payload["area_kind"] not in {"district", "neighborhood", "community"}
            or not payload["boundary"]
        ):
            raise ValidationError("Escolha um tipo e desenhe o contorno da área.")
        digest = canonical_json_hash(payload)
        key_hash = hashlib.sha256(command.encode()).hexdigest()
        with transaction.atomic():
            campaign = Campaign.objects.select_for_update().get(
                pk=context["campaign"].pk
            )
            require_writable(campaign)
            require_campaign_permission(
                request.user, campaign, "territories.manage.campaign"
            )
            scope = {
                "campaign": campaign,
                "actor_scope": f"user:{request.user.pk}",
                "route": "map/area/create",
                "key_hash": key_hash,
            }
            previous = IdempotencyRecord.objects.filter(**scope).first()
            if previous:
                if previous.request_hash != digest:
                    return JsonResponse(
                        {"detail": "Comando já usado com outros dados."}, status=409
                    )
                return JsonResponse(previous.result_ref)
            area = Territory.objects.create(
                tenant=campaign.tenant,
                campaign=campaign,
                created_by=request.user,
                **payload,
            )
            result = {"id": str(area.pk), "name": area.name}
            IdempotencyRecord.objects.create(
                **scope,
                tenant=campaign.tenant,
                request_hash=digest,
                status_code=201,
                result_ref=result,
                expires_at=timezone.now() + timedelta(hours=24),
            )
            append_audit_event(
                actor=request.user,
                tenant=campaign.tenant,
                campaign=campaign,
                action="territory.boundary_created",
                resource_type=area._meta.label_lower,
                resource_id=area.pk,
                minimized_diff={"area_kind": area.area_kind, "source_recorded": True},
            )
        return JsonResponse(result, status=201)
    except ValidationError as exc:
        return JsonResponse({"detail": " ".join(exc.messages)}, status=400)
    except (ValueError, TypeError, KeyError, AttributeError):
        return JsonResponse(
            {"detail": "Confira os campos e o contorno informado."}, status=400
        )
