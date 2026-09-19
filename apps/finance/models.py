from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import CampaignScopedModel, UUIDTimeStampedModel


class BudgetVersion(CampaignScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        APPROVED = "approved", "Aprovado"
        SUPERSEDED = "superseded", "Substituído"

    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_budget_versions",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "version_number"],
                name="uniq_budget_campaign_version",
            )
        ]


class BudgetLine(UUIDTimeStampedModel):
    budget_version = models.ForeignKey(
        BudgetVersion, on_delete=models.PROTECT, related_name="lines"
    )
    cost_center = models.CharField(max_length=120)
    funding_source = models.CharField(max_length=120)
    amount_cents = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["budget_version", "cost_center", "funding_source"],
                name="uniq_budget_line_dimension",
            )
        ]


class Obligation(CampaignScopedModel):
    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SUBMITTED = "submitted", "Submetida"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"
        CANCELLED = "cancelled", "Cancelada"

    class DocumentationStatus(models.TextChoices):
        INCOMPLETE = "incomplete", "Incompleta"
        IN_REVIEW = "in_review", "Em revisão"
        VERIFIED = "verified", "Conferida"
        WITH_RESERVATION = "with_reservation", "Com ressalva"

    origin_type = models.CharField(max_length=80)
    origin_id = models.UUIDField()
    creditor_ref = models.CharField(max_length=180)
    description = models.CharField(max_length=255)
    amount_cents = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    due_date = models.DateField(null=True, blank=True)
    approval_status = models.CharField(
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
    )
    documentation_status = models.CharField(
        max_length=24,
        choices=DocumentationStatus.choices,
        default=DocumentationStatus.INCOMPLETE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "origin_type", "origin_id"],
                name="uniq_obligation_canonical_origin",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_cents__gt=0), name="obligation_amount_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["campaign", "approval_status", "due_date"])
        ]


class ObligationApproval(UUIDTimeStampedModel):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"

    obligation = models.ForeignKey(
        Obligation, on_delete=models.PROTECT, related_name="approvals"
    )
    obligation_version = models.PositiveBigIntegerField()
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="obligation_decisions",
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason = models.CharField(max_length=500)

    def clean(self):
        super().clean()
        if self.obligation_id and self.decided_by_id:
            if self.obligation.created_by_id == self.decided_by_id:
                raise ValidationError(
                    {"decided_by": "O criador não pode realizar a aprovação final."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaymentRecord(CampaignScopedModel):
    class Status(models.TextChoices):
        RECORDED = "recorded", "Registrado"
        VERIFIED = "verified", "Conferido"
        REVERSED = "reversed", "Estornado"

    external_reference = models.CharField(max_length=180)
    amount_cents = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    paid_at = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RECORDED
    )
    reversal_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversals"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "external_reference"],
                name="uniq_payment_campaign_external_ref",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_cents__gt=0), name="payment_amount_positive"
            ),
        ]


class PaymentAllocation(UUIDTimeStampedModel):
    payment = models.ForeignKey(
        PaymentRecord, on_delete=models.PROTECT, related_name="allocations"
    )
    obligation = models.ForeignKey(
        Obligation, on_delete=models.PROTECT, related_name="payment_allocations"
    )
    amount_cents = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "obligation"],
                name="uniq_payment_obligation_allocation",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_cents__gt=0), name="allocation_amount_positive"
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.payment_id and self.obligation_id:
            if self.payment.campaign_id != self.obligation.campaign_id:
                errors["obligation"] = "Pagamento e obrigação devem pertencer à mesma campanha."
            other_payment_allocations = self.payment.allocations.exclude(pk=self.pk).aggregate(
                total=models.Sum("amount_cents")
            )["total"] or 0
            if other_payment_allocations + self.amount_cents > self.payment.amount_cents:
                errors["amount_cents"] = "A alocação supera o valor disponível do pagamento."
            other_obligation_allocations = self.obligation.payment_allocations.exclude(
                pk=self.pk
            ).aggregate(total=models.Sum("amount_cents"))["total"] or 0
            if other_obligation_allocations + self.amount_cents > self.obligation.amount_cents:
                errors["amount_cents"] = "A alocação supera o saldo da obrigação."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
