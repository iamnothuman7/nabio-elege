"""Explicit capabilities: labels reflect the existing server permission boundaries."""

from django import forms
from django.core.exceptions import ValidationError

from apps.campaigns.models import Permission
from .guidance import attach_guidance

LABELS = {
    "campaigns.read": "Consultar identificação da campanha",
    "campaigns.manage": "Editar identificação da campanha",
    "memberships.manage": "Criar e revogar acessos da equipe",
    "audit.read": "Consultar histórico de ações da campanha",
    "tasks.manage": "Consultar e gerenciar projetos e tarefas",
    "territories.read": "Consultar territórios, comitês e mapa",
    "territories.manage": "Cadastrar e editar territórios e comitês",
    "field.manage": "Consultar e gerenciar equipe de campo, ações e escalas",
    "field.approve": "Aprovar ações da equipe de campo",
    "electors.read.assigned": "Consultar cadastros de eleitores sob sua responsabilidade",
    "electors.read.campaign": "Consultar cadastros de eleitores de toda a campanha",
    "electors.create": "Cadastrar eleitores voluntários",
    "electors.review": "Conferir solicitações de cadastro de eleitores",
    "stock.manage": "Consultar e gerenciar materiais, entradas, saídas, reservas e transferências",
    "purchases.create": "Consultar e cadastrar fornecedores, solicitações e pedidos de compra",
    "purchases.approve": "Aprovar compras",
    "purchases.receive": "Conferir recebimentos de compras",
    "finance.read": "Consultar registros financeiros",
    "finance.create": "Cadastrar despesas, receitas e contas",
    "finance.approve": "Aprovar registros financeiros",
    "finance.reconcile": "Registrar pagamentos e conciliar extratos",
    "finance.export": "Exportar informações financeiras",
    "events.manage": "Consultar e gerenciar agenda e eventos",
    "events.approve": "Aprovar eventos",
    "assets.manage": "Consultar e gerenciar patrimônio e custódias",
    "logistics.manage": "Consultar e gerenciar viagens, veículos e motoristas",
    "logistics.approve": "Aprovar logística",
    "documents.read": "Consultar documentos internos",
    "documents.create": "Enviar documentos",
    "documents.download": "Baixar documentos aos quais já tem acesso",
    "documents.read_personal": "Consultar documentos pessoais",
    "documents.read_financial": "Consultar documentos financeiros",
    "documents.read_legal": "Consultar documentos jurídicos autorizados",
    "legal.manage": "Consultar e gerenciar casos jurídicos autorizados e ocorrências",
    "legal.approve": "Revisar casos jurídicos autorizados",
    "rules.manage": "Consultar e gerenciar calendário regulatório",
    "rules.approve": "Aprovar prazos regulatórios",
    "closure.manage": "Gerenciar encerramento e fases da campanha",
    "service.manage": "Consultar e gerenciar atendimentos",
    "service.read_payload": "Ler conteúdo dos atendimentos atribuídos",
    "privacy.handle": "Gerenciar privacidade, finalidades e solicitações de titulares",
    "forms.create": "Consultar e criar formulários",
    "forms.review": "Revisar formulários",
    "forms.publish": "Publicar formulários revisados",
    "submissions.read": "Triar respostas recebidas",
    "submissions.assist": "Registrar respostas assistidas atribuídas",
    "people.read": "Consultar pessoas atribuídas",
    "people.export": "Permitir exportação de pessoas nos fluxos que a suportam",
    "content.manage": "Consultar e gerenciar comunicação, estúdio e marca",
    "content.approve": "Aprovar comunicação e materiais de marca",
    "proposals.manage": "Consultar e gerenciar propostas públicas",
    "proposals.approve": "Aprovar propostas públicas",
    "results.manage": "Consultar e importar resultados públicos agregados",
    "election.manage": "Consultar e gerenciar escalas do dia da eleição",
    "election.approve": "Aprovar escalas do dia da eleição",
    "reports.read": "Consultar relatórios dos módulos permitidos",
    "reports.export": "Exportar relatórios dos módulos permitidos",
}

# No silent grants: dependencies must also be selected and delegable.
DEPENDENCIES = {
    "campaigns.manage.campaign": {"campaigns.read.campaign"},
    "territories.manage.campaign": {"territories.read.campaign"},
    "electors.read.campaign": {"electors.read.assigned"},
    "electors.create.assigned": {"electors.read.assigned"},
    "electors.review.campaign": {"electors.read.assigned", "electors.read.campaign"},
    "finance.create.campaign": {"finance.read.campaign"},
    "finance.approve.campaign": {"finance.read.campaign"},
    "finance.reconcile.campaign": {"finance.read.campaign"},
    "finance.export.campaign": {"finance.read.campaign"},
    "reports.export.campaign": {"reports.read.campaign"},
    "purchases.approve.campaign": {"purchases.create.campaign"},
    "purchases.receive.campaign": {"purchases.create.campaign"},
    "forms.review.campaign": {"forms.create.campaign"},
    "forms.publish.campaign": {"forms.create.campaign"},
}
for resource in [
    "field",
    "events",
    "logistics",
    "legal",
    "rules",
    "content",
    "proposals",
    "election",
]:
    DEPENDENCIES[f"{resource}.approve.campaign"] = {f"{resource}.manage.campaign"}
for action in ["create", "download", "read_personal", "read_financial", "read_legal"]:
    DEPENDENCIES[
        f"documents.{action}.{'resource' if action == 'download' else 'campaign'}"
    ] = {"documents.read.campaign"}


def permission_label(code):
    return LABELS.get(code) or LABELS.get(
        code.rsplit(".", 1)[0], "Permissão administrativa: " + code
    )


def validate_selection(codes, allowed):
    selected = set(codes)
    if not selected or not selected.issubset(set(allowed)):
        raise ValidationError(
            "Selecione ao menos uma permissão que você possa delegar."
        )
    for code in sorted(selected):
        missing = DEPENDENCIES.get(code, set()) - selected
        if missing:
            raise ValidationError(
                f"Para “{permission_label(code)}”, marque também: "
                + "; ".join(permission_label(dep) for dep in sorted(missing))
                + "."
            )
    return selected


class AccessForm(forms.Form):
    username = forms.CharField(
        label="Nome de usuário",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    password = forms.CharField(
        label="Senha inicial (mínimo 12 caracteres)",
        min_length=12,
        max_length=1024,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    permission_codes = forms.MultipleChoiceField(
        label="O que esta pessoa pode acessar?", widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, allowed=None, **kwargs):
        super().__init__(*args, **kwargs)
        existing = set(Permission.objects.values_list("code", flat=True))
        self.allowed = existing if allowed is None else existing & set(allowed)
        self.fields["permission_codes"].choices = sorted(
            [(code, permission_label(code)) for code in self.allowed],
            key=lambda pair: pair[1],
        )
        attach_guidance(self)

    @property
    def permission_groups(self):
        categories = {
            "Campanha e território": {
                "campaigns",
                "territories",
                "field",
                "election",
                "results",
            },
            "Eleitores, atendimento e privacidade": {
                "electors",
                "people",
                "service",
                "privacy",
                "submissions",
                "forms",
            },
            "Operação e materiais": {
                "tasks",
                "events",
                "assets",
                "logistics",
                "stock",
                "purchases",
            },
            "Financeiro": {"finance"},
            "Conteúdo, documentos e jurídico": {
                "content",
                "proposals",
                "documents",
                "legal",
                "rules",
            },
            "Equipe, relatórios e auditoria": {
                "memberships",
                "reports",
                "audit",
                "closure",
            },
        }
        choices = list(self["permission_codes"])
        for choice in choices:
            required = DEPENDENCIES.get(choice.data["value"], set())
            choice.requirements = "; ".join(
                permission_label(code) for code in sorted(required)
            )
        return [
            {
                "name": name,
                "choices": [
                    choice
                    for choice in choices
                    if choice.data["value"].split(".")[0] in resources
                ],
                "selected": any(
                    choice.data["selected"]
                    for choice in choices
                    if choice.data["value"].split(".")[0] in resources
                ),
            }
            for name, resources in categories.items()
            if any(
                choice.data["value"].split(".")[0] in resources for choice in choices
            )
        ]

    def clean_permission_codes(self):
        codes = self.cleaned_data["permission_codes"]
        if not codes and not self.fields["permission_codes"].required:
            return None
        return sorted(validate_selection(codes, self.allowed))
