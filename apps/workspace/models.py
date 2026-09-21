import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import CampaignScopedModel, UUIDTimeStampedModel


class SecurityProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    totp_secret_ciphertext = models.BinaryField(blank=True, default=bytes)
    enabled_at = models.DateTimeField(null=True, blank=True)
    last_counter = models.BigIntegerField(default=-1)
    recovery_hashes = models.JSONField(default=list, blank=True)
    session_version = models.PositiveIntegerField(default=1)
    failures = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    password_change_required = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)


class LoginGuard(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class Invitation(CampaignScopedModel):
    username = models.CharField(max_length=150)
    role = models.ForeignKey("campaigns.Role", on_delete=models.PROTECT)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class Reviewable(CampaignScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        IN_REVIEW = "in_review", "Em revisão"
        APPROVED = "approved", "Aprovado"
        ACTIVE = "active", "Em execução"
        COMPLETED = "completed", "Concluído"
        CANCELLED = "cancelled", "Cancelado"

    title = models.CharField("Título", max_length=180)
    description = models.TextField("Descrição", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    responsible = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True)
    due_at = models.DateTimeField("Prazo", null=True, blank=True)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.responsible_id and not self.responsible.is_effective:
            raise ValidationError({"responsible": "Selecione um vínculo ativo."})


class LegalCase(Reviewable):
    reference = models.CharField("Referência externa", max_length=180, blank=True)
    case_type = models.CharField("Natureza", max_length=80)
    source_ref = models.URLField("Fonte", blank=True)
    restricted_document = models.ForeignKey("core.Document", on_delete=models.PROTECT, null=True, blank=True)


class LegalCaseAccess(CampaignScopedModel):
    legal_case = models.ForeignKey(LegalCase, on_delete=models.PROTECT, related_name="access_grants")
    membership = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT)
    can_manage_access = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["legal_case", "membership"], name="uniq_legal_case_membership")]


class RegulatoryDeadline(Reviewable):
    source_url = models.URLField("Fonte normativa")
    source_excerpt = models.TextField("Dispositivo de referência")
    effective_from = models.DateField("Vigente desde")
    effective_until = models.DateField("Vigente até", null=True, blank=True)
    severity = models.CharField("Efeito", max_length=16, choices=[("warn", "Alerta"), ("review", "Revisão obrigatória")], default="warn")

    def clean(self):
        super().clean()
        if self.effective_until and self.effective_from and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "A vigência final deve ser posterior à inicial."})


class CampaignEvent(Reviewable):
    starts_at = models.DateTimeField("Início")
    ends_at = models.DateTimeField("Fim")
    location = models.CharField("Local", max_length=250)
    accessibility_plan = models.TextField("Plano de acessibilidade")
    public_summary = models.TextField("Resumo público", blank=True)
    capacity = models.PositiveIntegerField("Capacidade", default=1)

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "O fim deve ocorrer após o início."})
        if self.capacity < 1:
            raise ValidationError({"capacity": "Informe uma capacidade positiva."})


class Asset(CampaignScopedModel):
    name = models.CharField("Nome", max_length=180)
    inventory_code = models.CharField("Código patrimonial", max_length=80)
    ownership = models.CharField("Propriedade", max_length=16, choices=[("owned", "Próprio"), ("rented", "Locado"), ("loaned", "Cedido")])
    condition = models.CharField("Condição", max_length=16, choices=[("available", "Disponível"), ("maintenance", "Em manutenção"), ("retired", "Baixado")], default="available")
    description = models.TextField("Descrição", blank=True)
    document_due = models.DateField("Validade documental", null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "inventory_code"], name="uniq_asset_inventory_code")]


class AssetBooking(CampaignScopedModel):
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="bookings")
    event = models.ForeignKey(CampaignEvent, on_delete=models.PROTECT, null=True, blank=True)
    custodian = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT)
    starts_at = models.DateTimeField("Início")
    ends_at = models.DateTimeField("Fim")
    status = models.CharField(max_length=16, choices=[("reserved", "Reservado"), ("accepted", "Custódia aceita"), ("returned", "Devolvido"), ("cancelled", "Cancelado")], default="reserved")
    return_condition = models.CharField(max_length=500, blank=True)

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("O fim deve ocorrer após o início.")
        if self.custodian_id and not self.custodian.is_effective:
            raise ValidationError("O custodiante precisa ter vínculo ativo.")


class LogisticsTrip(Reviewable):
    vehicle = models.ForeignKey(Asset, on_delete=models.PROTECT)
    driver = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT, related_name="driving_trips")
    departure_at = models.DateTimeField("Partida")
    return_at = models.DateTimeField("Retorno previsto")
    origin = models.CharField("Origem", max_length=180)
    destination = models.CharField("Destino", max_length=180)

    def clean(self):
        super().clean()
        if self.departure_at and self.return_at and self.return_at <= self.departure_at:
            raise ValidationError("O retorno deve ocorrer após a partida.")
        if self.driver_id and not self.driver.is_effective:
            raise ValidationError("O motorista precisa ter vínculo ativo.")


class EditorialContent(Reviewable):
    channel = models.CharField("Canal público", max_length=80)
    body = models.TextField("Texto da peça")
    rights_reference = models.CharField("Licenças e direitos de uso", max_length=250)
    planned_at = models.DateTimeField("Publicação prevista", null=True, blank=True)
    publication_url = models.URLField("URL publicada", blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    approved_hash = models.CharField(max_length=64, blank=True)


class BrandAsset(Reviewable):
    asset_type = models.CharField("Tipo de peça", max_length=80)
    rights_reference = models.CharField("Licença e direitos", max_length=250)
    version_label = models.CharField("Versão", max_length=40)
    document = models.ForeignKey("core.Document", on_delete=models.PROTECT, null=True, blank=True)


class Proposal(Reviewable):
    policy_area = models.CharField("Área de política pública", max_length=100)
    statement_type = models.CharField("Natureza", max_length=16, choices=[("fact", "Fato documentado"), ("estimate", "Estimativa"), ("commitment", "Proposta declarada")])
    source_url = models.URLField("Fonte", blank=True)
    methodology = models.TextField("Fundamentação e limites")

    def clean(self):
        super().clean()
        if self.statement_type in {"fact", "estimate"} and not self.source_url:
            raise ValidationError({"source_url": "Fatos e estimativas precisam de uma fonte."})


class ElectionShift(Reviewable):
    location = models.CharField("Local administrativo", max_length=180)
    starts_at = models.DateTimeField("Início")
    ends_at = models.DateTimeField("Fim")
    checklist = models.TextField("Checklist operacional")

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("O fim deve ocorrer após o início.")


class Occurrence(Reviewable):
    occurred_at = models.DateTimeField("Ocorrido em", default=timezone.now)
    location = models.CharField("Local", max_length=180)
    verification = models.CharField("Verificação", max_length=16, choices=[("alleged", "Relato não confirmado"), ("verified", "Verificado")], default="alleged")
    legal_case = models.ForeignKey(LegalCase, on_delete=models.PROTECT, null=True, blank=True)


class ClosureItem(CampaignScopedModel):
    title = models.CharField("Item de conferência", max_length=180)
    area = models.CharField("Área", max_length=80)
    responsible = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True)
    evidence_reference = models.CharField("Referência da evidência", max_length=250, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)


class ReviewDecision(CampaignScopedModel):
    resource_type = models.CharField(max_length=100)
    resource_id = models.UUIDField()
    resource_version = models.PositiveBigIntegerField()
    content_hash = models.CharField(max_length=64)
    decision = models.CharField(max_length=32)
    reason = models.CharField(max_length=500)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Decisões são imutáveis.")
        return super().save(*args, **kwargs)


class StockReservation(CampaignScopedModel):
    item = models.ForeignKey("operations.StockItem", on_delete=models.PROTECT)
    warehouse = models.ForeignKey("operations.Warehouse", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    purpose = models.CharField("Finalidade administrativa", max_length=180)
    expires_at = models.DateTimeField("Expira em")
    status = models.CharField(max_length=16, choices=[("active", "Ativa"), ("released", "Liberada"), ("consumed", "Consumida"), ("expired", "Expirada")], default="active")

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="stock_reservation_positive")]


class StockTransfer(CampaignScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Preparando envio"
        IN_TRANSIT = "in_transit", "Em trânsito"
        RECEIVED = "received", "Recebida integralmente"
        RETURNED = "returned", "Saldo devolvido à origem"
        CANCELLED = "cancelled", "Cancelada antes do envio"

    item = models.ForeignKey("operations.StockItem", on_delete=models.PROTECT)
    source_warehouse = models.ForeignKey("operations.Warehouse", on_delete=models.PROTECT, related_name="outgoing_transfers")
    destination_warehouse = models.ForeignKey("operations.Warehouse", on_delete=models.PROTECT, related_name="incoming_transfers")
    quantity = models.DecimalField("Quantidade a enviar", max_digits=18, decimal_places=4)
    received_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    returned_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    purpose = models.CharField("Finalidade operacional", max_length=180)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    dispatched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["campaign", "status"], name="stock_transfer_campaign_status")]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transfer_quantity_positive"),
            models.CheckConstraint(condition=~models.Q(source_warehouse=models.F("destination_warehouse")), name="transfer_different_warehouses"),
            models.CheckConstraint(condition=models.Q(received_quantity__gte=0, returned_quantity__gte=0), name="transfer_settled_nonnegative"),
            models.CheckConstraint(condition=models.Q(quantity__gte=models.F("received_quantity") + models.F("returned_quantity")), name="transfer_settled_within_total"),
        ]

    @property
    def in_transit_quantity(self):
        return self.quantity - self.received_quantity - self.returned_quantity if self.status == self.Status.IN_TRANSIT else 0

    def clean(self):
        super().clean()
        if self.source_warehouse_id and self.source_warehouse_id == self.destination_warehouse_id:
            raise ValidationError({"destination_warehouse": "Escolha um depósito diferente da origem."})

    def __str__(self):
        return f"Transferência {str(self.pk)[:8]}"


class StockTransferReceipt(CampaignScopedModel):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.PROTECT, related_name="receipts")
    kind = models.CharField(max_length=16, choices=[("receive", "Recebimento no destino"), ("return", "Devolução à origem")])
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    evidence_reference = models.CharField("Comprovante operacional", max_length=180)
    movement = models.OneToOneField("operations.StockMovement", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transfer_receipt_positive")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Comprovantes de transferência não podem ser alterados.")
        return super().save(*args, **kwargs)


class PurchaseReceipt(CampaignScopedModel):
    order = models.ForeignKey("operations.PurchaseOrder", on_delete=models.PROTECT, related_name="receipts")
    item = models.ForeignKey("operations.PurchaseItem", on_delete=models.PROTECT)
    warehouse = models.ForeignKey("operations.Warehouse", on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    evidence_reference = models.CharField(max_length=180)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchase_receipt_positive")]


class OfficialDataset(CampaignScopedModel):
    title = models.CharField("Título da base", max_length=180)
    source_url = models.URLField("Fonte oficial")
    reference_year = models.PositiveIntegerField("Ano de referência")
    coverage = models.CharField("Cobertura geográfica", max_length=180)
    methodology = models.TextField("Metodologia e limitações")
    file_hash = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField(default=0)


class AggregateResult(UUIDTimeStampedModel):
    dataset = models.ForeignKey(OfficialDataset, on_delete=models.PROTECT, related_name="results")
    geography_code = models.CharField(max_length=32)
    geography_name = models.CharField(max_length=120)
    metric = models.CharField(max_length=80)
    value = models.PositiveBigIntegerField()
    denominator = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["dataset", "geography_code", "metric"], name="uniq_aggregate_result")]


class CampaignProfile(CampaignScopedModel):
    candidate_name = models.CharField("Nome público da candidatura", max_length=150)
    ballot_number = models.CharField("Número da candidatura", max_length=5, blank=True)
    party = models.CharField("Partido / federação", max_length=120, blank=True)
    office = models.CharField("Cargo", max_length=40, choices=[("vereador", "Vereador(a)"), ("prefeito", "Prefeito(a)"), ("deputado_estadual", "Deputado(a) estadual"), ("deputado_federal", "Deputado(a) federal"), ("senador", "Senador(a)"), ("governador", "Governador(a)"), ("presidente", "Presidente"), ("a_definir", "A definir")], default="a_definir")
    election_date = models.DateField("Data da eleição (confirmada pela equipe)", null=True, blank=True)
    campaign_region = models.CharField("Abrangência da campanha", max_length=180)
    motto = models.CharField("Identificação / lema público", max_length=180, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign"], name="uniq_campaign_public_profile")]

    def clean(self):
        super().clean()
        if self.ballot_number and not self.ballot_number.isdigit():
            raise ValidationError({"ballot_number": "Informe somente os dígitos do número público."})

    def __str__(self):
        return self.candidate_name


class Territory(CampaignScopedModel):
    area_kind = models.CharField(max_length=20, choices=[("operation", "Território operacional"), ("district", "Distrito"), ("neighborhood", "Bairro"), ("community", "Comunidade")], default="operation")
    boundary = models.JSONField(default=dict, blank=True)
    source_reference = models.CharField(max_length=500, blank=True)
    public_area_confirmed = models.BooleanField(default=False)
    name = models.CharField("Nome do território", max_length=120)
    municipality = models.CharField("Município", max_length=120)
    state = models.CharField("UF", max_length=2)
    ibge_code = models.CharField("Código IBGE (opcional)", max_length=7, blank=True)
    coordinator = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True)
    description = models.TextField("Descrição da área de operação", blank=True)
    status = models.CharField(max_length=16, choices=[("active", "Ativo"), ("inactive", "Inativo")], default="active")

    def clean(self):
        super().clean()
        from .geo_validation import validate_boundary
        validate_boundary(self.boundary)
        if self.boundary and (not self.public_area_confirmed or len(self.source_reference.strip()) < 3):
            raise ValidationError("Identifique a fonte e confirme que o contorno é uma área pública, não uma localização individual.")
        if self.state not in {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}:
            raise ValidationError({"state": "Informe uma UF brasileira válida, em maiúsculas."})
        if self.ibge_code and (len(self.ibge_code) != 7 or not self.ibge_code.isdigit()):
            raise ValidationError({"ibge_code": "Use um código de município com sete dígitos."})
        if self.coordinator_id and not self.coordinator.is_effective:
            raise ValidationError({"coordinator": "A coordenação precisa ter vínculo ativo."})


class CampaignBase(CampaignScopedModel):
    name = models.CharField("Comitê / ponto de apoio", max_length=160)
    territory = models.ForeignKey(Territory, on_delete=models.PROTECT)
    base_type = models.CharField("Tipo", max_length=20, choices=[("committee", "Comitê eleitoral"), ("support", "Ponto de apoio"), ("event", "Local de evento público"), ("logistics", "Base de logística")], default="committee")
    public_address = models.CharField("Endereço público do local", max_length=250)
    latitude = models.DecimalField("Latitude", max_digits=9, decimal_places=6)
    longitude = models.DecimalField("Longitude", max_digits=9, decimal_places=6)
    coordinator = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True)
    opening_hours = models.CharField("Horário de funcionamento", max_length=160, blank=True)
    accessible = models.BooleanField("Acessibilidade conferida", default=False)
    public_location_confirmed = models.BooleanField("Confirmo que é um local de operação, não residência de eleitor", default=False)
    status = models.CharField(max_length=16, choices=[("active", "Ativo"), ("inactive", "Inativo")], default="active")

    def clean(self):
        super().clean()
        if self.latitude is not None and not -85 <= self.latitude <= 85:
            raise ValidationError({"latitude": "A latitude deve ficar entre -85 e 85."})
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValidationError({"longitude": "A longitude deve ficar entre -180 e 180."})
        if not self.public_location_confirmed:
            raise ValidationError({"public_location_confirmed": "O mapa aceita somente locais de operação públicos, sem residências de eleitores."})


class FieldWorker(CampaignScopedModel):
    name = models.CharField("Nome do integrante", max_length=150)
    function = models.CharField("Função na campanha", max_length=24, choices=[("coordinator", "Coordenador(a) territorial"), ("field_organizer", "Cabo eleitoral"), ("volunteer", "Voluntário(a)"), ("event_staff", "Equipe de eventos"), ("poll_observer", "Fiscal / apoio eleitoral"), ("logistics", "Apoio logístico")], default="volunteer")
    territory = models.ForeignKey(Territory, on_delete=models.PROTECT)
    base = models.ForeignKey(CampaignBase, on_delete=models.PROTECT, null=True, blank=True)
    supervisor = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT)
    membership = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT, null=True, blank=True, related_name="field_profiles")
    availability = models.CharField("Disponibilidade declarada", max_length=180, blank=True)
    onboarding_reference = models.CharField("Referência do termo de participação", max_length=180)
    training_status = models.CharField("Capacitação", max_length=16, choices=[("pending", "Pendente"), ("completed", "Concluída")], default="pending")
    status = models.CharField(max_length=16, choices=[("active", "Ativo"), ("paused", "Pausado"), ("ended", "Desligado")], default="active")

    def clean(self):
        super().clean()
        if self.base_id and self.territory_id and self.base.territory_id != self.territory_id:
            raise ValidationError({"base": "Selecione um comitê do mesmo território."})
        if self.supervisor_id and not self.supervisor.is_effective:
            raise ValidationError({"supervisor": "A supervisão precisa ter vínculo ativo."})


class FieldActivity(Reviewable):
    activity_type = models.CharField("Tipo de ação", max_length=24, choices=[("public_event", "Ato / encontro público"), ("street_team", "Equipe de rua"), ("materials", "Distribuição geral de material"), ("committee_shift", "Plantão de comitê"), ("training", "Formação de equipe"), ("logistics", "Operação logística"), ("accessibility", "Apoio de acessibilidade")])
    territory = models.ForeignKey(Territory, on_delete=models.PROTECT)
    base = models.ForeignKey(CampaignBase, on_delete=models.PROTECT)
    starts_at = models.DateTimeField("Início")
    ends_at = models.DateTimeField("Fim")
    required_staff = models.PositiveIntegerField("Pessoas necessárias", default=1)
    operational_checklist = models.TextField("Checklist operacional")

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("A ação precisa terminar depois do início.")
        if self.base_id and self.territory_id and self.base.territory_id != self.territory_id:
            raise ValidationError({"base": "O ponto de encontro deve pertencer ao território da ação."})
        if self.required_staff < 1:
            raise ValidationError({"required_staff": "Informe ao menos uma pessoa."})


class FieldAssignment(CampaignScopedModel):
    activity = models.ForeignKey(FieldActivity, on_delete=models.PROTECT, related_name="assignments")
    worker = models.ForeignKey(FieldWorker, on_delete=models.PROTECT, related_name="assignments")
    role_description = models.CharField("Responsabilidade na ação", max_length=180)
    status = models.CharField(max_length=16, choices=[("scheduled", "Escalado"), ("confirmed", "Confirmado"), ("checked_in", "Presença registrada"), ("completed", "Concluído"), ("cancelled", "Cancelado")], default="scheduled")
    checked_in_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["activity", "worker"], name="uniq_field_assignment")]

    def clean(self):
        super().clean()
        if self.worker_id and self.worker.status != "active":
            raise ValidationError({"worker": "Selecione um integrante ativo."})


class ElectorRegistration(CampaignScopedModel):
    """Voluntary contact record. Not an official voter roll or voting preference."""
    person = models.OneToOneField("forms.Person", on_delete=models.PROTECT, related_name="elector_registration")
    purpose = models.ForeignKey("forms.ProcessingPurpose", on_delete=models.PROTECT)
    owner = models.ForeignKey("campaigns.Membership", on_delete=models.PROTECT)
    municipality = models.CharField("Município informado", max_length=120, blank=True)
    source = models.CharField("Origem", max_length=16, choices=[("voluntary", "Cadastro voluntário"), ("assisted", "Cadastro assistido")])
    status = models.CharField(max_length=20, choices=[("pending", "Aguardando revisão"), ("registered", "Cadastro conferido"), ("suppressed", "Contato suprimido")], default="pending")
    evidence_reference = models.CharField("Referência da manifestação / solicitação", max_length=180)
    consent_verified_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        super().clean()
        if self.owner_id and not self.owner.is_effective:
            raise ValidationError({"owner": "O responsável precisa ter vínculo ativo."})
        if self.purpose_id and self.purpose.status != "active":
            raise ValidationError({"purpose": "A finalidade precisa estar ativa e revisada."})
