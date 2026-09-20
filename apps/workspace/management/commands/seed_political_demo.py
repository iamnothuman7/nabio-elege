from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission
from apps.core.crypto import blind_index, encrypt_json
from apps.core.models import RetentionPolicy
from apps.forms.models import ContactPoint, Person, ProcessingPurpose
from apps.workspace.models import CampaignBase, CampaignProfile, ElectorRegistration, FieldActivity, FieldAssignment, FieldWorker, Territory


class Command(BaseCommand):
    help = "Acrescenta uma operação eleitoral fictícia ao ambiente de demonstração."

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, "LOCAL_DEMO", False):
            raise CommandError("Somente para nabio_elege.local_settings.")
        campaign = Campaign.objects.get(code="campanha-demo", is_demo=True)
        member = Membership.objects.get(campaign=campaign, user__username="demo.gestor")
        reviewer = Membership.objects.get(campaign=campaign, user__username="demo.revisor")
        member.role.permissions.set(Permission.objects.all())
        scope = {"tenant": campaign.tenant, "campaign": campaign, "created_by": member.user}
        CampaignProfile.objects.get_or_create(campaign=campaign, defaults={**scope, "candidate_name": "Candidatura de demonstração", "office": "a_definir", "campaign_region": "Fortaleza/CE · exemplo fictício", "motto": "Organização de campanha, do comitê ao território."})
        territories = []
        for name in ["Centro", "Leste", "Sul"]:
            territory, _ = Territory.objects.get_or_create(campaign=campaign, name=f"Regional {name}", defaults={**scope, "municipality": "Fortaleza", "state": "CE", "ibge_code": "2304400", "coordinator": member, "description": "Área fictícia de organização de equipes; não é uma divisão oficial nem representa distribuição de eleitores."})
            territories.append(territory)
        point_specs = [("Comitê central · demonstração", "committee", territories[0], "-3.731900", "-38.526700"), ("Ponto de apoio leste · demonstração", "support", territories[1], "-3.737300", "-38.488300"), ("Praça de encontro · demonstração", "event", territories[1], "-3.725100", "-38.497800"), ("Base logística sul · demonstração", "logistics", territories[2], "-3.775000", "-38.526000")]
        bases = []
        for name, kind, territory, lat, lng in point_specs:
            base, _ = CampaignBase.objects.get_or_create(campaign=campaign, name=name, defaults={**scope, "territory": territory, "base_type": kind, "public_address": "Posição ilustrativa em Fortaleza. Não existe sede real neste ponto.", "latitude": lat, "longitude": lng, "coordinator": member, "opening_hours": "Exemplo: 8h às 18h", "accessible": True, "public_location_confirmed": True})
            bases.append(base)
        workers = []
        for name, function, territory in [("Ana Campos · fictícia", "coordinator", territories[0]), ("Bruno Oliveira · fictício", "field_organizer", territories[0]), ("Carla Santos · fictícia", "volunteer", territories[1]), ("Diego Lima · fictício", "logistics", territories[2]), ("Eva Costa · fictícia", "event_staff", territories[1]), ("Felipe Alves · fictício", "field_organizer", territories[2])]:
            worker, _ = FieldWorker.objects.get_or_create(campaign=campaign, name=name, defaults={**scope, "function": function, "territory": territory, "supervisor": member, "availability": "Disponibilidade fictícia: manhã e tarde", "onboarding_reference": "TERMO-DEMO-SEM-VALIDADE", "training_status": "completed"})
            workers.append(worker)
        today = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        specs = [("Plantão de acolhimento no comitê", "committee_shift", bases[0], 1), ("Formação dos cabos eleitorais", "training", bases[1], 2), ("Preparação de encontro público", "public_event", bases[2], 3), ("Distribuição de materiais às equipes", "logistics", bases[3], 4)]
        activities = []
        for title, kind, base, day in specs:
            activity, _ = FieldActivity.objects.get_or_create(campaign=campaign, title=title, defaults={**scope, "activity_type": kind, "territory": base.territory, "base": base, "responsible": reviewer, "starts_at": today + timedelta(days=day), "ends_at": today + timedelta(days=day, hours=3), "required_staff": 3, "operational_checklist": "Conferir acessibilidade, material, equipe escalada e contato da coordenação. Dados fictícios.", "status": "approved"})
            activities.append(activity)
        for i, worker in enumerate(workers[:4]):
            FieldAssignment.objects.get_or_create(campaign=campaign, activity=activities[i], worker=worker, defaults={**scope, "role_description": "Apoio operacional fictício", "status": "confirmed"})
        retention = RetentionPolicy.objects.get(tenant=campaign.tenant, code="demo")
        purpose, _ = ProcessingPurpose.objects.get_or_create(campaign=campaign, code="cadastro-voluntario", defaults={**scope, "description": "Cadastro voluntário fictício para atendimento da campanha, sem perfil ou intenção de voto.", "legal_basis_ref": "DEMO · exige revisão jurídica e de privacidade para uso real", "allowed_fields": ["name", "email", "phone", "message", "adult_declaration", "consent"], "retention_policy": retention, "status": "active"})
        for i, name in enumerate(["Pessoa demonstrativa 01", "Pessoa demonstrativa 02", "Pessoa demonstrativa 03", "Pessoa demonstrativa 04", "Pessoa demonstrativa 05", "Pessoa demonstrativa 06"], 1):
            evidence = f"MANIFESTACAO-FICTICIA-{i:03}"
            if ElectorRegistration.objects.filter(campaign=campaign, evidence_reference=evidence).exists():
                continue
            person = Person.objects.create(**scope, display_name_ciphertext=encrypt_json({"value": name}), retention_policy=retention)
            email = f"pessoa-demo-{i}@example.test"
            ContactPoint.objects.create(person=person, type="email", value_ciphertext=encrypt_json({"value": email}), match_hmac=blind_index(email, campaign_id=campaign.pk))
            ElectorRegistration.objects.create(**scope, person=person, purpose=purpose, owner=member, municipality="Fortaleza", source="assisted", evidence_reference=evidence)
        self.stdout.write(self.style.SUCCESS("Cenário eleitoral fictício pronto: candidatura, 3 territórios, 4 pontos, 6 integrantes, 4 ações e 6 cadastros voluntários."))
