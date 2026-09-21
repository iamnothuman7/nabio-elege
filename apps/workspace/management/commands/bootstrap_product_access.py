"""Explicit first platform administrator + isolated, synthetic demonstration."""

import json
import sys
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.rls import database_scope
from apps.operations.models import Project, Task
from apps.workspace.models import CampaignProfile, FieldWorker, Territory
from apps.workspace.platform_services import account, create_customer, open_campaign


class Command(BaseCommand):
    help = "Cria duas contas novas e um cliente demo isolado; não redefine contas existentes."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", required=True)
        parser.add_argument("--demo-username", required=True)
        parser.add_argument("--demo-slug", default="cliente-demo")
        parser.add_argument("--credentials-stdin", action="store_true", required=True)

    def handle(self, *args, **options):
        credentials = {}
        try:
            credentials = json.loads(sys.stdin.read(8193))
            admin_password = credentials["admin_password"]
            demo_password = credentials["demo_password"]
            if not isinstance(admin_password, str) or not isinstance(
                demo_password, str
            ):
                raise ValueError
            if admin_password == demo_password:
                raise ValueError
            with transaction.atomic():
                admin = account(
                    options["admin_username"], admin_password, administrator=True
                )
                tenant, campaign, demo, member = create_customer(
                    actor=admin,
                    organization="Cliente demonstração · dados fictícios",
                    slug=options["demo_slug"],
                    campaign_name="Nabio Elege · Demonstração",
                    username=options["demo_username"],
                    password=demo_password,
                    election_id="DEMONSTRACAO",
                    office_code="administrativo",
                    jurisdiction_code="DEMO",
                    is_demo=True,
                )
                open_campaign(actor=admin, campaign=campaign)
                with database_scope(campaign=campaign, actor=demo):
                    scope = {"tenant": tenant, "campaign": campaign, "created_by": demo}
                    CampaignProfile.objects.create(
                        **scope,
                        candidate_name="Campanha demonstrativa",
                        campaign_region="Brasil · operação fictícia",
                        motto="Explore a plataforma. Utilize somente dados fictícios.",
                    )
                    territory = Territory.objects.create(
                        **scope,
                        name="Território de demonstração",
                        municipality="Fortaleza",
                        state="CE",
                        coordinator=member,
                        description="Exemplo operacional sintético, sem limites oficiais ou pessoas reais.",
                    )
                    for index, function in enumerate(
                        ("coordinator", "field_organizer", "volunteer"), 1
                    ):
                        FieldWorker.objects.create(
                            **scope,
                            name=f"Integrante fictício {index:02}",
                            function=function,
                            territory=territory,
                            supervisor=member,
                            onboarding_reference=f"DEMO-FICTICIO-{index:02}",
                            availability="Exemplo de disponibilidade · a combinar",
                        )
                    project = Project.objects.create(
                        **scope,
                        title="Primeiros passos · demonstração",
                        description="Organização administrativa fictícia. Explore os cadastros, mapas, equipe e tarefas.",
                    )
                    for days, title in enumerate(
                        (
                            "Conhecer os módulos e permissões",
                            "Organizar a equipe e os territórios",
                            "Explorar a agenda e os recursos",
                        ),
                        1,
                    ):
                        Task.objects.create(
                            **scope,
                            title=title,
                            project=project,
                            assignee=member,
                            due_at=timezone.now() + timedelta(days=days),
                            completion_criteria="Exploração concluída e anotada pela equipe demo.",
                        )
        except (ValueError, TypeError, KeyError, ValidationError, IntegrityError):
            raise CommandError(
                "Criação recusada: confira senhas distintas, campos e contas existentes. Nenhuma criação parcial foi mantida."
            ) from None
        finally:
            credentials = None
            admin_password = demo_password = None
        self.stdout.write(
            "PRODUCT_ACCESS_CREATED: duas contas novas, troca inicial de senha e MFA obrigatório no perfil de produção. Nenhuma senha foi registrada em logs."
        )
