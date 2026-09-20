import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class UUIDTimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CampaignScopedModel(UUIDTimeStampedModel):
    tenant = models.ForeignKey(
        "campaigns.Tenant", on_delete=models.PROTECT, related_name="+"
    )
    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    row_version = models.PositiveBigIntegerField(default=1)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.campaign_id and self.tenant_id:
            campaign_tenant_id = getattr(self.campaign, "tenant_id", None)
            if campaign_tenant_id and campaign_tenant_id != self.tenant_id:
                raise ValidationError(
                    {"campaign": "A campanha deve pertencer à organização informada."}
                )
        for field in self._meta.fields:
            if not isinstance(field, models.ForeignKey) or field.name in {"campaign", "tenant", "created_by"}:
                continue
            if not getattr(self, field.attname):
                continue
            related = getattr(self, field.name)
            if hasattr(related, "campaign_id") and related.campaign_id != self.campaign_id:
                raise ValidationError({field.name: "O registro deve pertencer à mesma campanha."})
            if hasattr(related, "tenant_id") and related.tenant_id != self.tenant_id:
                raise ValidationError({field.name: "O registro deve pertencer à mesma organização."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if not self._state.adding:
            current = type(self).objects.select_for_update().only("row_version").get(pk=self.pk)
            if current.row_version != self.row_version:
                raise ValidationError("Este registro foi alterado por outra pessoa. Recarregue a página.")
            self.row_version += 1
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                    "row_version",
                    "updated_at",
                }
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        for name in ("title", "name", "display_name", "description", "external_reference", "protocol", "code"):
            value = getattr(self, name, None)
            if value:
                return str(value)[:100]
        return str(self.pk)[:8]


class RetentionPolicy(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        ACTIVE = "active", "Ativa"
        RETIRED = "retired", "Desativada"

    tenant = models.ForeignKey(
        "campaigns.Tenant", on_delete=models.PROTECT, related_name="retention_policies"
    )
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    legal_basis_ref = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_retention_policy_tenant_code"
            )
        ]

    def __str__(self):
        return f"{self.tenant}: {self.name}"


class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Eventos de auditoria são imutáveis.")

    def delete(self):
        raise ValidationError("Eventos de auditoria não podem ser excluídos.")


class AuditEvent(models.Model):
    objects = ImmutableAuditQuerySet.as_manager()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "campaigns.Tenant", on_delete=models.PROTECT, null=True, blank=True
    )
    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.PROTECT, null=True, blank=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=120)
    resource_type = models.CharField(max_length=120)
    resource_id = models.CharField(max_length=120, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    minimized_diff = models.JSONField(default=dict, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["campaign", "occurred_at"]),
            models.Index(fields=["resource_type", "resource_id"]),
        ]
        ordering = ["-occurred_at", "-id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Eventos de auditoria são imutáveis.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Eventos de auditoria não podem ser excluídos.")


class OutboxEvent(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PROCESSING = "processing", "Processando"
        PUBLISHED = "published", "Publicado"
        FAILED = "failed", "Falhou"

    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant = models.ForeignKey("campaigns.Tenant", on_delete=models.PROTECT)
    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.PROTECT, null=True, blank=True
    )
    kind = models.CharField(max_length=120)
    aggregate_type = models.CharField(max_length=120)
    aggregate_id = models.CharField(max_length=120)
    aggregate_version = models.PositiveBigIntegerField(default=1)
    payload_minimized = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    available_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=120, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "available_at"])]


class InboxEvent(UUIDTimeStampedModel):
    consumer = models.CharField(max_length=120)
    event_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "event_id"], name="uniq_inbox_consumer_event"
            )
        ]


class IdempotencyRecord(UUIDTimeStampedModel):
    tenant = models.ForeignKey("campaigns.Tenant", on_delete=models.PROTECT)
    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.PROTECT)
    actor_scope = models.CharField(max_length=160)
    route = models.CharField(max_length=255)
    key_hash = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    result_ref = models.JSONField(default=dict)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "actor_scope", "route", "key_hash"],
                name="uniq_idempotency_scope_route_key",
            )
        ]


class Document(CampaignScopedModel):
    class Classification(models.TextChoices):
        INTERNAL = "internal", "Interno administrativo"
        PERSONAL = "personal", "Pessoal restrito"
        FINANCIAL = "financial", "Financeiro restrito"
        LEGAL = "legal", "Jurídico sigiloso"

    class Status(models.TextChoices):
        QUARANTINED = "quarantined", "Em quarentena"
        AVAILABLE = "available", "Disponível"
        REJECTED = "rejected", "Rejeitado"
        ARCHIVED = "archived", "Arquivado"

    display_name = models.CharField(max_length=255)
    classification = models.CharField(max_length=16, choices=Classification.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUARANTINED
    )
    retention_policy = models.ForeignKey(
        RetentionPolicy, on_delete=models.PROTECT, null=True, blank=True
    )
    legal_hold = models.BooleanField(default=False)


class DocumentVersion(UUIDTimeStampedModel):
    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        CLEAN = "clean", "Aprovado"
        REJECTED = "rejected", "Rejeitado"
        ERROR = "error", "Erro"

    document = models.ForeignKey(
        Document, on_delete=models.PROTECT, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=500, unique=True)
    sha256 = models.CharField(max_length=64)
    media_type = models.CharField(max_length=150)
    size_bytes = models.PositiveBigIntegerField()
    scan_status = models.CharField(
        max_length=16, choices=ScanStatus.choices, default=ScanStatus.PENDING
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="document_uploads"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="uniq_document_version_number",
            )
        ]
