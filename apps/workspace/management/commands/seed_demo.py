import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.models import RetentionPolicy
from apps.finance.models import BankAccount, FinancialReceipt, Obligation
from apps.forms.models import Form, ProcessingPurpose, ServiceRequest
from apps.operations.models import Project, StockItem, Supplier, Task, Warehouse
from apps.operations.services import apply_stock_movement
from apps.workspace.models import Asset, CampaignEvent, ClosureItem, EditorialContent, ElectionShift, LegalCase, Proposal
from apps.workspace.services import audit


class Command(BaseCommand):
    help = "Cria dados fictícios exclusivamente no ambiente local de demonstração."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Senha apenas para as duas contas fictícias locais.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, "LOCAL_DEMO", False):
            raise CommandError("Este comando só funciona com nabio_elege.local_settings.")
        password = options["password"]
        if len(password) < 12:
            raise CommandError("Use uma senha de demonstração com ao menos 12 caracteres.")
        tenant, _ = Tenant.objects.get_or_create(slug="demonstracao", defaults={"name": "Nabio · Demonstração"})
        role, _ = Role.objects.get_or_create(tenant=tenant, code="gestao-demo", defaults={"name": "Gestão da demonstração"})
        role.permissions.set(Permission.objects.all())
        campaign, created = Campaign.objects.get_or_create(tenant=tenant, code="campanha-demo", defaults={"name": "Horizonte 2026", "election_id": "demo-2026", "office_code": "administrativo", "jurisdiction_code": "DEMO", "phase": "operation", "is_demo": True})
        users = []
        for username, first_name in [("demo.gestor", "Alex"), ("demo.revisor", "Marina")]:
            user, _ = User.objects.get_or_create(username=username, defaults={"first_name": first_name, "last_name": "Demonstração"})
            user.set_password(password)
            user.save()
            membership, _ = Membership.objects.get_or_create(user=user, campaign=campaign, defaults={"tenant": tenant, "role": role, "status": "active"})
            users.append((user, membership))
        actor, member = users[0]
        reviewer, reviewer_member = users[1]
        retention, _ = RetentionPolicy.objects.get_or_create(tenant=tenant, code="demo", defaults={"name": "Política fictícia para testes", "description": "Somente dados fictícios; não representa orientação jurídica.", "retention_days": 30, "legal_basis_ref": "DEMO · requer revisão antes de produção", "status": "active"})
        if not created:
            self.stdout.write("Demonstração já existente. Senhas das contas fictícias atualizadas; registros preservados.")
            return
        scope = {"tenant": tenant, "campaign": campaign, "created_by": actor}
        now = timezone.now()
        project = Project.objects.create(**scope, title="Estruturação da operação", description="Coordenação administrativa, documentação e infraestrutura.")
        project2 = Project.objects.create(**scope, title="Agenda e suporte à equipe", description="Preparação dos eventos e atendimento administrativo.")
        task_data = [("Conferir documentação dos fornecedores", "high", 1, member, project), ("Validar plano de acessibilidade do encontro", "normal", 2, reviewer_member, project2), ("Revisar checklist dos depósitos", "normal", 3, member, project), ("Organizar a escala de suporte", "high", 4, reviewer_member, project2), ("Concluir inventário de equipamentos", "low", 6, member, project)]
        for title, priority, days, assignee, project_obj in task_data:
            Task.objects.create(**scope, title=title, project=project_obj, priority=priority, assignee=assignee, due_at=now + timedelta(days=days), completion_criteria="Checklist conferido e revisão registrada.")
        supplier = Supplier.objects.create(**scope, name="Papelaria Exemplo · fictícia")
        Warehouse.objects.create(**scope, name="Almoxarifado central", code="central")
        warehouse = Warehouse.objects.get(campaign=campaign, code="central")
        for name, sku, quantity in [("Crachás administrativos", "CRA-001", 120), ("Pranchetas", "PRA-001", 40), ("Canetas", "CAN-001", 240)]:
            item = StockItem.objects.create(**scope, name=name, sku=sku, unit="un")
            apply_stock_movement(actor=actor, item_id=item.pk, warehouse_id=warehouse.pk, kind="entry", quantity=quantity, reason="Carga inicial fictícia da demonstração")
        BankAccount.objects.create(**scope, name="Conta demonstrativa", funding_source="Fictícia · sem conexão bancária")
        for description, amount, status in [("Locação de estrutura para encontro", 185000, "submitted"), ("Materiais administrativos", 42500, "submitted"), ("Suporte técnico ao escritório", 78000, "draft")]:
            Obligation.objects.create(**scope, origin_type="demo", origin_id=uuid.uuid4(), creditor_ref=supplier.name, description=description, amount_cents=amount, due_date=(now + timedelta(days=7)).date(), approval_status=status)
        FinancialReceipt.objects.create(**scope, origin_ref="Receita fictícia de demonstração", amount_cents=500000, received_at=now, documentation_ref="DEMO-REC-001")
        for title, days, location in [("Encontro de alinhamento da equipe", 2, "Sala de reuniões · escritório"), ("Oficina de processos administrativos", 5, "Espaço de formação · demonstração")]:
            CampaignEvent.objects.create(**scope, title=title, starts_at=now + timedelta(days=days), ends_at=now + timedelta(days=days, hours=2), location=location, capacity=35, accessibility_plan="Acesso sem degraus, materiais digitais acessíveis e assentos reservados.", responsible=reviewer_member)
        Asset.objects.create(**scope, name="Notebook de apoio", inventory_code="PAT-001", ownership="owned", description="Equipamento fictício para controle de custódia.")
        LegalCase.objects.create(**scope, title="Revisão dos termos de contratação", case_type="Consultivo", responsible=reviewer_member, due_at=now + timedelta(days=3))
        EditorialContent.objects.create(**scope, title="Comunicado de horário do atendimento", channel="Site institucional", body="O atendimento administrativo estará disponível no horário informado pela equipe responsável.", rights_reference="Texto original da demonstração", planned_at=now + timedelta(days=4))
        Proposal.objects.create(**scope, title="Acessibilidade dos serviços administrativos", policy_area="Administração", statement_type="commitment", methodology="Proposta fictícia para demonstrar revisão e rastreabilidade.")
        ElectionShift.objects.create(**scope, title="Suporte administrativo · turno da manhã", location="Base administrativa fictícia", starts_at=now + timedelta(days=15), ends_at=now + timedelta(days=15, hours=4), responsible=member, checklist="Conferir equipe, recursos disponíveis e canal de ocorrências.")
        for category in ["Informações sobre atendimento", "Acessibilidade de evento", "Solicitação administrativa"]:
            ServiceRequest.objects.create(**scope, category=category, assignee=member, due_at=now + timedelta(days=2))
        purpose = ProcessingPurpose.objects.create(**scope, code="atendimento-demo", description="Receber solicitações administrativas fictícias.", legal_basis_ref="DEMO · validar base legal antes de uso real", allowed_fields=["name", "email", "phone", "message", "adult_declaration", "consent"], retention_policy=retention)
        Form.objects.create(**scope, purpose=purpose, title="Fale com a equipe administrativa", slug="atendimento")
        for title, area in [("Conferir obrigações e conciliações", "Financeiro"), ("Devolver bens e liberar reservas", "Operação"), ("Revisar retenção e bloqueios legais", "Privacidade"), ("Conferir dossiê de encerramento", "Governança")]:
            ClosureItem.objects.create(**scope, title=title, area=area, responsible=member)
        audit(actor, project, "demo.initialized")
        self.stdout.write(self.style.SUCCESS("Demonstração criada com sucesso. Contas: demo.gestor e demo.revisor."))
        self.stdout.write(f"Campanha: /c/{campaign.pk}/")
