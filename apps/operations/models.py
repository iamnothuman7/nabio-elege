from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import CampaignScopedModel, UUIDTimeStampedModel


class Project(CampaignScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        COMPLETED = "completed", "Concluído"
        CANCELLED = "cancelled", "Cancelado"

    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        indexes = [models.Index(fields=["campaign", "status", "created_at"])]


class Task(CampaignScopedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        IN_PROGRESS = "in_progress", "Em execução"
        BLOCKED = "blocked", "Bloqueada"
        IN_REVIEW = "in_review", "Em revisão"
        COMPLETED = "completed", "Concluída"
        CANCELLED = "cancelled", "Cancelada"

    class Priority(models.TextChoices):
        LOW = "low", "Baixa"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Crítica"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    assignee = models.ForeignKey(
        "campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True
    )
    priority = models.CharField(
        max_length=16, choices=Priority.choices, default=Priority.NORMAL
    )
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    completion_criteria = models.TextField(blank=True)
    requires_evidence = models.BooleanField(default=False)
    evidence_document = models.ForeignKey(
        "core.Document", on_delete=models.PROTECT, null=True, blank=True
    )

    def clean(self):
        super().clean()
        errors = {}
        if self.project_id and self.campaign_id and self.project.campaign_id != self.campaign_id:
            errors["project"] = "O projeto deve pertencer à mesma campanha."
        if self.assignee_id and self.campaign_id:
            if self.assignee.campaign_id != self.campaign_id or not self.assignee.is_effective:
                errors["assignee"] = "O responsável precisa ter vínculo ativo na campanha."
        if self.status == self.Status.COMPLETED:
            if not self.completion_criteria:
                errors["completion_criteria"] = "Defina os critérios de conclusão."
            if self.requires_evidence and not self.evidence_document_id:
                errors["evidence_document"] = "Esta tarefa exige uma evidência."
        if errors:
            raise ValidationError(errors)


class TaskDependency(UUIDTimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="dependencies")
    depends_on = models.ForeignKey(
        Task, on_delete=models.PROTECT, related_name="dependent_tasks"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "depends_on"], name="uniq_task_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(task=models.F("depends_on")),
                name="task_cannot_depend_on_itself",
            ),
        ]

    def clean(self):
        super().clean()
        if self.task_id and self.depends_on_id:
            if self.task.campaign_id != self.depends_on.campaign_id:
                raise ValidationError("Dependências devem pertencer à mesma campanha.")


class Supplier(CampaignScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        BLOCKED = "blocked", "Bloqueado"
        ARCHIVED = "archived", "Arquivado"

    name = models.CharField(max_length=180)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)


class PurchaseRequest(CampaignScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SUBMITTED = "submitted", "Enviada"
        QUOTING = "quoting", "Em cotação"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"
        CANCELLED = "cancelled", "Cancelada"

    justification = models.TextField()
    destination = models.CharField(max_length=180)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)


class PurchaseItem(UUIDTimeStampedModel):
    request = models.ForeignKey(
        PurchaseRequest, on_delete=models.PROTECT, related_name="items"
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit = models.CharField(max_length=32)
    stock_item = models.ForeignKey(
        "StockItem", on_delete=models.PROTECT, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="purchase_item_quantity_positive"
            )
        ]


class PurchaseOrder(CampaignScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Em elaboração"
        APPROVED = "approved", "Aprovado"
        ACTIVE = "active", "Vigente"
        PARTIALLY_RECEIVED = "partially_received", "Parcialmente recebido"
        RECEIVED = "received", "Recebido"
        CLOSED = "closed", "Encerrado"

    purchase_request = models.OneToOneField(
        PurchaseRequest, on_delete=models.PROTECT, related_name="order"
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    amount_cents = models.PositiveBigIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_cents__gt=0), name="purchase_order_amount_positive"
            )
        ]


class Warehouse(CampaignScopedModel):
    name = models.CharField(max_length=180)
    code = models.SlugField(max_length=80)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "code"], name="uniq_warehouse_campaign_code"
            )
        ]


class StockItem(CampaignScopedModel):
    name = models.CharField(max_length=180)
    sku = models.CharField(max_length=80)
    unit = models.CharField(max_length=32)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "sku"], name="uniq_stock_item_campaign_sku"
            )
        ]


class StockBalance(UUIDTimeStampedModel):
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="balances")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="balances"
    )
    physical_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0")
    )
    reserved_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0")
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "warehouse"], name="uniq_stock_balance_item_warehouse"
            ),
            models.CheckConstraint(
                condition=models.Q(physical_quantity__gte=0),
                name="stock_physical_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_quantity__gte=0),
                name="stock_reserved_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_quantity__lte=models.F("physical_quantity")),
                name="stock_reserved_not_above_physical",
            ),
        ]

    @property
    def available_quantity(self):
        return self.physical_quantity - self.reserved_quantity


class StockMovement(CampaignScopedModel):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada"
        EXIT = "exit", "Saída"
        ADJUSTMENT = "adjustment", "Ajuste"
        RETURN = "return", "Devolução"

    item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="movements")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    signed_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    reason = models.CharField(max_length=500)
    origin_type = models.CharField(max_length=80, blank=True)
    origin_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(signed_quantity=0), name="stock_movement_non_zero"
            )
        ]
        indexes = [models.Index(fields=["campaign", "item", "warehouse", "created_at"])]
