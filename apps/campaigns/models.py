import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import UUIDTimeStampedModel


class Tenant(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        SUSPENDED = "suspended", "Suspensa"
        ARCHIVED = "archived", "Arquivada"

    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=100, unique=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    billing_profile_ref = models.CharField(max_length=180, blank=True)

    def __str__(self):
        return self.name


class Campaign(UUIDTimeStampedModel):
    class Phase(models.TextChoices):
        PREPARATION = "preparation", "Preparação"
        OPERATION = "operation", "Operação"
        CLOSING = "closing", "Encerramento"
        ARCHIVED = "archived", "Arquivada"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="campaigns")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=180)
    election_id = models.CharField(max_length=100)
    office_code = models.CharField(max_length=80)
    jurisdiction_code = models.CharField(max_length=100)
    phase = models.CharField(
        max_length=16, choices=Phase.choices, default=Phase.PREPARATION
    )
    timezone = models.CharField(max_length=64, default="America/Fortaleza")
    is_demo = models.BooleanField(default=False)
    row_version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_campaign_tenant_code"
            )
        ]
        indexes = [models.Index(fields=["tenant", "phase", "created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            self.row_version += 1
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                    "row_version",
                    "updated_at",
                }
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Permission(UUIDTimeStampedModel):
    code = models.CharField(max_length=160, unique=True)
    resource = models.CharField(max_length=80)
    action = models.CharField(max_length=80)
    scope = models.CharField(max_length=80, default="campaign")
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.code


class Role(UUIDTimeStampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="roles")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    permissions = models.ManyToManyField(Permission, blank=True, related_name="roles")
    is_system = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_role_tenant_code"
            )
        ]

    def __str__(self):
        return f"{self.tenant}: {self.name}"


class Membership(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        INVITED = "invited", "Convidado"
        ACTIVE = "active", "Ativo"
        SUSPENDED = "suspended", "Suspenso"
        REVOKED = "revoked", "Revogado"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="memberships")
    campaign = models.ForeignKey(
        Campaign, on_delete=models.PROTECT, related_name="memberships"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.INVITED, db_index=True
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="membership_invitations",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "campaign"], name="uniq_membership_user_campaign"
            )
        ]
        indexes = [models.Index(fields=["campaign", "status", "expires_at"])]

    def clean(self):
        super().clean()
        errors = {}
        if self.campaign_id and self.tenant_id and self.campaign.tenant_id != self.tenant_id:
            errors["campaign"] = "A campanha não pertence à organização informada."
        if self.role_id and self.tenant_id and self.role.tenant_id != self.tenant_id:
            errors["role"] = "O papel não pertence à organização informada."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def is_effective(self):
        if self.status != self.Status.ACTIVE:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    def revoke(self):
        self.status = self.Status.REVOKED
        self.revoked_at = timezone.now()
        self.save(update_fields=["status", "revoked_at", "updated_at"])

    def __str__(self):
        return f"{self.user} @ {self.campaign}"


class CampaignPhaseEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        Campaign, on_delete=models.PROTECT, related_name="phase_events"
    )
    from_phase = models.CharField(max_length=16, choices=Campaign.Phase.choices)
    to_phase = models.CharField(max_length=16, choices=Campaign.Phase.choices)
    reason = models.CharField(max_length=500)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["occurred_at"]
