import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import CampaignScopedModel, RetentionPolicy, UUIDTimeStampedModel


def opaque_code():
    return secrets.token_urlsafe(24)


class ProcessingPurpose(CampaignScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        ACTIVE = "active", "Ativa"
        RETIRED = "retired", "Desativada"

    code = models.SlugField(max_length=80)
    description = models.TextField()
    legal_basis_ref = models.CharField(max_length=255)
    allowed_fields = models.JSONField(default=list)
    retention_policy = models.ForeignKey(RetentionPolicy, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "code"], name="uniq_purpose_campaign_code"
            )
        ]


class PrivacyNoticeVersion(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        APPROVED = "approved", "Aprovado"
        RETIRED = "retired", "Desativado"

    purpose = models.ForeignKey(
        ProcessingPurpose, on_delete=models.PROTECT, related_name="notice_versions"
    )
    version = models.PositiveIntegerField()
    content = models.TextField()
    content_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_privacy_notices",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["purpose", "version"], name="uniq_notice_purpose_version"
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).only("status").first()
            if previous and previous.status == self.Status.APPROVED:
                raise ValidationError("Avisos aprovados são imutáveis.")
        return super().save(*args, **kwargs)


class Form(CampaignScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        IN_REVIEW = "in_review", "Em revisão"
        APPROVED = "approved", "Aprovado"
        PUBLISHED = "published", "Publicado"
        PAUSED = "paused", "Pausado"
        CLOSED = "closed", "Encerrado"
        ARCHIVED = "archived", "Arquivado"

    purpose = models.ForeignKey(
        ProcessingPurpose, on_delete=models.PROTECT, related_name="forms"
    )
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=100)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    opens_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    current_version = models.ForeignKey(
        "FormVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "slug"], name="uniq_form_campaign_slug"
            )
        ]

    def clean(self):
        super().clean()
        if self.purpose_id and self.campaign_id:
            if self.purpose.campaign_id != self.campaign_id:
                raise ValidationError(
                    {"purpose": "A finalidade deve pertencer à mesma campanha."}
                )
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            raise ValidationError({"closes_at": "O encerramento deve ocorrer após a abertura."})


class FormVersion(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        IN_REVIEW = "in_review", "Em revisão"
        APPROVED = "approved", "Aprovada"
        PUBLISHED = "published", "Publicada"
        RETIRED = "retired", "Desativada"

    form = models.ForeignKey(Form, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    schema_json = models.JSONField()
    schema_hash = models.CharField(max_length=64)
    notice_version = models.ForeignKey(PrivacyNoticeVersion, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_form_versions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["form", "version_number"], name="uniq_form_version_number"
            )
        ]

    def clean(self):
        super().clean()
        if self.notice_version_id and self.form_id:
            if self.notice_version.purpose_id != self.form.purpose_id:
                raise ValidationError(
                    {"notice_version": "O aviso deve corresponder à finalidade do formulário."}
                )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).only("status").first()
            if previous and previous.status == self.Status.PUBLISHED:
                raise ValidationError("Versões publicadas são imutáveis.")
        self.full_clean()
        return super().save(*args, **kwargs)


class SourceLink(CampaignScopedModel):
    form = models.ForeignKey(Form, on_delete=models.PROTECT, related_name="source_links")
    public_code = models.CharField(max_length=80, unique=True, default=opaque_code)
    source_type = models.CharField(max_length=80, default="direct")
    source_ref = models.CharField(max_length=160, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        super().clean()
        if self.form_id and self.campaign_id and self.form.campaign_id != self.campaign_id:
            raise ValidationError(
                {"form": "O formulário deve pertencer à mesma campanha do link."}
            )

    @property
    def is_active(self):
        if self.revoked_at:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()


class Submission(CampaignScopedModel):
    class CaptureMode(models.TextChoices):
        DIRECT = "direct", "Direto"
        ASSISTED = "assisted", "Assistido"

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Recebida"
        PROCESSING = "processing", "Em processamento"
        PROCESSED = "processed", "Processada"
        REJECTED = "rejected", "Rejeitada"
        REVIEW_REQUIRED = "review_required", "Revisão necessária"

    form_version = models.ForeignKey(
        FormVersion, on_delete=models.PROTECT, related_name="submissions"
    )
    source_link = models.ForeignKey(
        SourceLink, on_delete=models.PROTECT, null=True, blank=True
    )
    capture_mode = models.CharField(max_length=16, choices=CaptureMode.choices)
    assisted_by_membership = models.ForeignKey(
        "campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True
    )
    payload_ciphertext = models.BinaryField()
    processing_status = models.CharField(
        max_length=24,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
        db_index=True,
    )

    def clean(self):
        super().clean()
        if self.form_version_id and self.campaign_id:
            if self.form_version.form.campaign_id != self.campaign_id:
                raise ValidationError(
                    {"form_version": "A versão deve pertencer à mesma campanha."}
                )
        if self.capture_mode == self.CaptureMode.ASSISTED and not self.assisted_by_membership_id:
            raise ValidationError(
                {"assisted_by_membership": "O modo assistido exige um agente autenticado."}
            )
        if self.capture_mode == self.CaptureMode.DIRECT and self.assisted_by_membership_id:
            raise ValidationError(
                {"assisted_by_membership": "O modo direto não pode atribuir um agente."}
            )


class SubmissionReceipt(UUIDTimeStampedModel):
    submission = models.OneToOneField(
        Submission, on_delete=models.PROTECT, related_name="receipt"
    )
    receipt_id = models.CharField(max_length=80, unique=True, default=opaque_code)
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()


class Person(CampaignScopedModel):
    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        IN_REVIEW = "in_review", "Em revisão"
        RELEASED = "released", "Liberado"
        RESTRICTED = "restricted", "Restrito"

    display_name_ciphertext = models.BinaryField()
    review_status = models.CharField(
        max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    retention_policy = models.ForeignKey(RetentionPolicy, on_delete=models.PROTECT)


class ContactPoint(UUIDTimeStampedModel):
    class Type(models.TextChoices):
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"

    class VerificationState(models.TextChoices):
        UNVERIFIED = "unverified", "Não verificado"
        CHALLENGE_SENT = "challenge_sent", "Desafio enviado"
        VERIFIED = "verified", "Verificado"
        EXPIRED = "expired", "Expirado"

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="contact_points")
    type = models.CharField(max_length=16, choices=Type.choices)
    value_ciphertext = models.BinaryField()
    match_hmac = models.CharField(max_length=64, db_index=True)
    verification_state = models.CharField(
        max_length=24,
        choices=VerificationState.choices,
        default=VerificationState.UNVERIFIED,
    )

    class Meta:
        indexes = [models.Index(fields=["person", "type", "match_hmac"])]


class Manifestation(CampaignScopedModel):
    class Choice(models.TextChoices):
        GRANTED = "granted", "Concedida"
        DENIED = "denied", "Negada"
        REVOKED = "revoked", "Revogada"

    submission = models.ForeignKey(
        Submission, on_delete=models.PROTECT, related_name="manifestations"
    )
    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, null=True, blank=True
    )
    purpose = models.ForeignKey(ProcessingPurpose, on_delete=models.PROTECT)
    notice_version = models.ForeignKey(PrivacyNoticeVersion, on_delete=models.PROTECT)
    choice = models.CharField(max_length=16, choices=Choice.choices)
    method = models.CharField(max_length=80)
    occurred_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class VerificationChallenge(CampaignScopedModel):
    contact_point = models.ForeignKey(ContactPoint, on_delete=models.PROTECT)
    purpose_scope = models.CharField(max_length=120)
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)


class Suppression(CampaignScopedModel):
    contact_hmac = models.CharField(max_length=64, db_index=True)
    purpose = models.ForeignKey(ProcessingPurpose, on_delete=models.PROTECT)
    reason = models.CharField(max_length=255)
    effective_at = models.DateTimeField(default=timezone.now)
    source_request_id = models.CharField(max_length=120, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "contact_hmac", "purpose"],
                name="uniq_suppression_campaign_contact_purpose",
            )
        ]


class ServiceRequest(CampaignScopedModel):
    class Status(models.TextChoices):
        RECEIVED = "received", "Recebida"
        TRIAGE = "triage", "Em triagem"
        IN_PROGRESS = "in_progress", "Em atendimento"
        WAITING_PERSON = "waiting_person", "Aguardando pessoa"
        RESOLVED = "resolved", "Resolvida"
        CLOSED = "closed", "Encerrada"

    protocol = models.CharField(max_length=80, unique=True, default=opaque_code)
    person = models.ForeignKey(Person, on_delete=models.PROTECT, null=True, blank=True)
    submission = models.OneToOneField(
        Submission,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="service_request",
    )
    category = models.CharField(max_length=120)
    assignee = models.ForeignKey(
        "campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.RECEIVED
    )
    due_at = models.DateTimeField(null=True, blank=True)
    resolution_summary = models.TextField(blank=True)


class PrivacyRequest(CampaignScopedModel):
    class RequestType(models.TextChoices):
        ACCESS = "access", "Acesso"
        CORRECTION = "correction", "Correção"
        SUPPRESSION = "suppression", "Supressão"
        DELETION = "deletion", "Eliminação"

    protocol = models.CharField(max_length=80, unique=True, default=opaque_code)
    request_type = models.CharField(max_length=16, choices=RequestType.choices)
    received_at = models.DateTimeField(default=timezone.now)
    verification_status = models.CharField(max_length=24, default="pending")
    due_at = models.DateTimeField(null=True, blank=True)
    decision_ref = models.CharField(max_length=180, blank=True)
