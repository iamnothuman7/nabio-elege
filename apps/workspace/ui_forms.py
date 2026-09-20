from django import forms
from django.db import models

from apps.campaigns.models import Membership
from apps.campaigns.services import has_campaign_permission
from apps.core.models import CampaignScopedModel, Document, RetentionPolicy
from .registry import LABELS
from .models import ElectorRegistration


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
        if self._meta.model is ElectorRegistration and self.instance._state.adding:
            self.fields["registration_name"] = forms.CharField(label="Nome informado pela pessoa", min_length=2, max_length=150)
            self.fields["registration_email"] = forms.EmailField(label="E-mail informado (opcional)", max_length=254, required=False)
            self.fields["registration_phone"] = forms.RegexField(label="Telefone informado (opcional)", regex=r"^\+[1-9][0-9]{7,14}$", max_length=16, required=False, help_text="Formato internacional. Ex.: +5585999999999.")
            self.fields["adult_declaration"] = forms.BooleanField(label="A pessoa declarou ter 18 anos ou mais")
            self.fields["requested_registration"] = forms.BooleanField(label="A pessoa solicitou o cadastro; tenho uma referência da manifestação")
            self.fields["purpose"].queryset = self.fields["purpose"].queryset.filter(status="active")
            self.fields["evidence_reference"].help_text = "Identifique o termo ou recibo, sem colar documentos ou dados sensíveis. Cadastro assistido fica pendente de conferência."
            if not has_campaign_permission(actor, campaign, "electors.read.campaign"):
                self.fields["owner"].queryset = self.fields["owner"].queryset.filter(user=actor)


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
