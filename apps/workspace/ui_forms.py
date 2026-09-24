from django import forms
from django.db import models

from apps.campaigns.models import Membership
from apps.campaigns.services import has_campaign_permission, membership_for
from apps.core.models import CampaignScopedModel, Document, RetentionPolicy
from .registry import LABELS
from .models import CampaignBase, ElectorRegistration, Territory
from .guidance import attach_guidance


class ScopedModelForm(forms.ModelForm):
    def __init__(self, *args, campaign, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.campaign = campaign
        self.instance.tenant = campaign.tenant
        if self.instance._state.adding:
            self.instance.created_by = actor
        for name, field in self.fields.items():
            field.label = LABELS.get(name, field.label)
            if isinstance(field, forms.ModelChoiceField):
                model = field.queryset.model
                if issubclass(model, CampaignScopedModel) or model is Membership:
                    field.queryset = field.queryset.filter(campaign=campaign)
                elif model is RetentionPolicy:
                    field.queryset = field.queryset.filter(tenant=campaign.tenant, status="active")
                else:
                    field.queryset = field.queryset.none()
                if model is Membership:
                    from django.db.models import Q
                    from django.utils import timezone
                    field.queryset = field.queryset.filter(status="active", revoked_at__isnull=True).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
                if model is Document:
                    classifications = ["internal"] + [value for value in ["personal", "financial", "legal"] if has_campaign_permission(actor, campaign, f"documents.read_{value}.campaign")]
                    field.queryset = field.queryset.filter(status="available", classification__in=classifications)
                if issubclass(model, CampaignScopedModel):
                    from .legal_access import restrict_queryset
                    field.queryset = restrict_queryset(field.queryset, actor, campaign)
            if isinstance(field, forms.DateTimeField):
                field.widget = forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})
                field.input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
            elif isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 4
            if "cents" in name:
                field.help_text = "Informe centavos inteiros. Ex.: 15000 = R$ 150,00."
            if name == "allowed_fields":
                field.help_text = 'Exemplo: ["name", "email", "message", "adult_declaration", "consent"]'
        if self._meta.model is Territory:
            from .address_lookup import UF_CODES
            self.fields["state"] = forms.ChoiceField(label="Estado / UF", choices=[("", "Selecione o estado")] + [(uf, uf) for uf in sorted(UF_CODES)])
            self.fields["name"].label = "Nome do território"
            self.fields["name"].help_text = "Ex.: Bairro Centro, Comunidade Lagoa ou Região Norte. Não é necessário desenhar no mapa."
            self.fields["area_kind"].label = "Tipo de território"
            self.fields["municipality"].label = "Município"
            self.fields["ibge_code"].help_text = "Preenchido pela consulta de CEP, quando disponível. Opcional."
            self.fields["source_reference"].help_text = "Necessária apenas se houver um contorno desenhado no mapa."
            self.fields["public_area_confirmed"].help_text = "Confirmação para contornos públicos. Não marque para identificar residências."
        if self._meta.model is ElectorRegistration and self.instance._state.adding:
            self.fields["registration_name"] = forms.CharField(label="Nome informado pela pessoa", min_length=2, max_length=150)
            self.fields["registration_email"] = forms.EmailField(label="E-mail", max_length=254, required=False)
            self.fields["registration_phone"] = forms.RegexField(label="Telefone", regex=r"^\+[1-9][0-9]{7,14}$", max_length=16, required=False, help_text="Formato internacional. Ex.: +5585999999999.")
            self.fields["adult_declaration"] = forms.BooleanField(label="A pessoa declarou ter 18 anos ou mais")
            self.fields["requested_registration"] = forms.BooleanField(label="A pessoa solicitou este cadastro e recebeu as informações de privacidade", help_text="Não marque por outra pessoa sem uma solicitação real. O cadastro fica pendente de conferência; isso não representa confirmação de voto.")
            self.fields["purpose"].queryset = self.fields["purpose"].queryset.filter(status="active")
            self.fields["purpose"].label = "Uso autorizado dos dados"
            purposes = list(self.fields["purpose"].queryset[:2])
            self.privacy_setup_needed = not purposes
            if len(purposes) == 1 and ElectorRegistration.objects.filter(campaign=campaign, purpose=purposes[0]).exists():
                self.fields["purpose"].initial = purposes[0].pk
                self.fields["purpose"].required = False
                self.fields["purpose"].widget = forms.HiddenInput()
                self.single_purpose = purposes[0]
            self.fields["owner"].required = False
            self.fields["owner"].initial = membership_for(actor, campaign).pk
            self.default_owner = membership_for(actor, campaign)
            self.fields["municipality"].required = True
            self.fields["registration_name"].label = "Nome"
            self.fields["first_vote"].label = "Primeira vez votando?"
            self.fields["first_vote"].widget = forms.NullBooleanSelect()
            self.fields["first_vote"].widget.choices = [("unknown", "Não informado"), ("true", "Sim"), ("false", "Não")]
            self.fields["voter_title"] = forms.CharField(label="Número do título de eleitor", required=False, max_length=18, widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}))
            self.fields["evidence_reference"].required = False
            self.fields["evidence_reference"].help_text = "Se houver, informe o número do termo ou recibo. Sem referência, registramos apenas sua declaração de solicitação, ainda pendente de conferência."
            if not has_campaign_permission(actor, campaign, "electors.read.campaign"):
                self.fields["owner"].queryset = self.fields["owner"].queryset.filter(user=actor)
            self.order_fields(["registration_name", "municipality", "first_vote", "voter_title", "adult_declaration", "requested_registration", "purpose", "registration_email", "registration_phone", "owner", "evidence_reference"])
        from apps.operations.models import StockItem, Warehouse
        if self._meta.model is StockItem:
            self.fields["sku"].required = False
            self.fields["sku"].label = "Código do material"
            self.fields["unit"].required = False
            self.fields["unit"].label = "Unidade de medida"
            self.fields["unit"].initial = self.instance.unit or "un"
        if self._meta.model is Warehouse:
            self.fields["code"].required = False
            self.fields["code"].help_text = "Código interno. Pode deixar vazio; geramos um identificador para o novo depósito."
        if self._meta.model is CampaignBase:
            self.fields["public_location_confirmed"].help_text = "Mantenha os endereços residenciais de eleitores fora do mapa. Esta confirmação protege a privacidade das pessoas."
        self.advanced_names = {
            ElectorRegistration: {"registration_email", "registration_phone", "owner", "evidence_reference"},
            CampaignBase: {"latitude", "longitude", "coordinator", "opening_hours", "accessible"},
            StockItem: {"sku", "unit"},
            Warehouse: {"code"},
        }.get(self._meta.model, set())
        self.advanced_fields = [self[name] for name in self.fields if name in self.advanced_names]
        attach_guidance(self)

    @property
    def advanced_errors(self):
        return self.is_bound and any(self[name].errors for name in self.advanced_names)

    def clean(self):
        data = super().clean()
        from uuid import uuid4
        from apps.operations.models import StockItem, Warehouse
        if self._meta.model is StockItem:
            data["sku"] = data.get("sku") or self.instance.sku or f"MAT-{uuid4().hex[:12].upper()}"
            data["unit"] = data.get("unit") or self.instance.unit or "un"
        if self._meta.model is Warehouse:
            data["code"] = data.get("code") or self.instance.code or f"deposito-{uuid4().hex[:12]}"
        if self._meta.model is ElectorRegistration and self.instance._state.adding:
            data["purpose"] = data.get("purpose") or getattr(self, "single_purpose", None)
            data["owner"] = data.get("owner") or self.default_owner
            if not data.get("evidence_reference") and data.get("requested_registration"):
                data["evidence_reference"] = "Solicitação declarada pelo operador no cadastro assistido; aguardando conferência."
            title = data.get("voter_title", "").replace(" ", "").replace("-", "").replace(".", "")
            if title and (len(title) != 12 or not title.isascii() or not title.isdigit()):
                self.add_error("voter_title", "Informe os 12 números do título ou deixe vazio.")
            data["voter_title"] = title
            purpose = data.get("purpose")
            if purpose:
                for name in ["first_vote", "voter_title"]:
                    if data.get(name) not in (None, "") and name not in purpose.allowed_fields:
                        self.add_error(name, "Este dado ainda não está autorizado na configuração de privacidade da campanha. Deixe vazio ou solicite a revisão da finalidade.")
        return data


def model_form_class(config):
    return forms.modelform_factory(config.model, form=ScopedModelForm, fields=config.fields)


PUBLIC_FIELDS = {
    "name": {"name": "name", "label": "Nome", "type": "short_text", "max_length": 150},
    "email": {"name": "email", "label": "E-mail para retorno", "type": "email", "max_length": 254},
    "phone": {"name": "phone", "label": "Telefone (com código do país)", "type": "phone", "max_length": 16},
    "message": {"name": "message", "label": "Sua solicitação administrativa", "type": "long_text", "max_length": 2000, "required": True},
    "adult_declaration": {"name": "adult_declaration", "label": "Declaro ter 18 anos ou mais", "type": "boolean", "required": True},
    "consent": {"name": "consent", "label": "Autorizo o tratamento para a finalidade descrita neste aviso", "type": "boolean", "required": False},
}


def public_submission_form(version, data=None):
    form = forms.Form(data)
    for definition in version.schema_json.get("fields", []):
        field_type = definition["type"]
        kwargs = {"label": definition.get("label", definition["name"]), "required": definition.get("required", False)}
        if field_type == "boolean":
            field = forms.BooleanField(**kwargs)
        elif field_type == "email":
            field = forms.EmailField(max_length=254, **kwargs)
        elif field_type in {"single_choice", "multiple_choice"}:
            cls = forms.ChoiceField if field_type == "single_choice" else forms.MultipleChoiceField
            field = cls(choices=[(v, v) for v in definition.get("options", [])], **kwargs)
        else:
            field = forms.CharField(max_length=min(definition.get("max_length", 2000), 2000), widget=forms.Textarea(attrs={"rows": 5}) if field_type == "long_text" else forms.TextInput(), **kwargs)
        form.fields[definition["name"]] = field
    return form
