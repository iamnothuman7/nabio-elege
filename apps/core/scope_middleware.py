import re

from django.db import connection, transaction
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.http import Http404
from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.campaigns.services import campaigns_for_user
from .crypto import hash_token
from .rls import database_scope


class CampaignScopeMiddleware(MiddlewareMixin):
    """Resolve routing metadata, authorize the user, scope all view queries."""

    def __call__(self, request):
        # Liveness must stay independent of sessions and database availability.
        if request.path in {"/healthz/", "/api/healthz"} or request.path.startswith(
            "/static/"
        ):
            return self.get_response(request)
        actor = request.user if request.user.is_authenticated else None
        public = re.fullmatch(
            r"/(?:f/|api/v1/public/forms/)([^/]+)(?:/submissions)?/?", request.path
        )
        public_code = public.group(1) if public else ""
        invitation_hash = (
            hash_token(request.POST.get("token", "").strip())
            if request.path == "/convite/" and request.method == "POST"
            else ""
        )
        with database_scope(
            actor=actor, public_code=public_code, invitation_hash=invitation_hash
        ):
            campaign = self.resolve_campaign(request, public_code, invitation_hash)
            with database_scope(
                campaign=campaign,
                actor=actor,
                public_code=public_code,
                invitation_hash=invitation_hash,
            ):
                response = self.get_response(request)
                if response.status_code >= 500 and connection.in_atomic_block:
                    transaction.set_rollback(True)
                if getattr(response, "streaming", False):
                    original = iter(response.streaming_content)

                    def chunks():
                        try:
                            while True:
                                with database_scope(campaign=campaign, actor=actor):
                                    if (
                                        campaign
                                        and actor
                                        and not campaigns_for_user(actor)
                                        .filter(pk=campaign.pk)
                                        .exists()
                                    ):
                                        raise PermissionError(
                                            "Acesso encerrado durante a transmissão."
                                        )
                                    try:
                                        chunk = next(original)
                                    except StopIteration:
                                        return
                                yield chunk
                        finally:
                            close = getattr(original, "close", None)
                            if close:
                                close()

                    response.streaming_content = chunks()
                return response

    @staticmethod
    def resolve_campaign(request, public_code, invitation_hash):
        # The routing policies expose only the record for the supplied opaque
        # token before scope selection. Publication/expiry is rechecked by view.
        if public_code:
            from apps.forms.models import SourceLink

            campaign_id = (
                SourceLink.objects.filter(
                    public_code=public_code, revoked_at__isnull=True
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
                .values_list("campaign_id", flat=True)
                .first()
            )
            return (
                Campaign.objects.filter(pk=campaign_id).first() if campaign_id else None
            )
        if invitation_hash:
            from apps.workspace.models import Invitation

            campaign_id = (
                Invitation.objects.filter(token_hash=invitation_hash)
                .values_list("campaign_id", flat=True)
                .first()
            )
            return (
                Campaign.objects.filter(pk=campaign_id).first() if campaign_id else None
            )
        match = re.match(r"/api/v1/campaigns/([0-9a-fA-F-]{36})(?:/|$)", request.path)
        campaign_id = (
            match.group(1) if match else resolve(request.path).kwargs.get("campaign_id")
        )
        if not campaign_id or not request.user.is_authenticated:
            return None
        try:
            return campaigns_for_user(request.user).filter(pk=campaign_id).first()
        except (ValueError, TypeError, ValidationError):
            raise Http404 from None
