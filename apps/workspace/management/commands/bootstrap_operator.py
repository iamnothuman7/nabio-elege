"""Create an explicitly scoped first operator; never overwrites existing data."""

import getpass
import sys

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.services import append_audit_event
from apps.workspace.models import SecurityProfile


class Command(BaseCommand):
    help = "Cria organização/campanha e operador sem superusuário, com permissões explícitas e troca obrigatória de senha."

    def add_arguments(self, parser):
        for name in [
            "tenant-name",
            "tenant-slug",
            "campaign-name",
            "campaign-code",
            "election-id",
            "office-code",
            "jurisdiction-code",
            "username",
        ]:
            parser.add_argument("--" + name, required=True)
        parser.add_argument(
            "--permission",
            action="append",
            required=True,
            help="Código de permissão explícita; repetir para cada permissão aprovada.",
        )
        parser.add_argument(
            "--password-stdin",
            action="store_true",
            help="Lê a senha exclusivamente de stdin protegido, nunca de argumentos ou logs.",
        )

    def handle(self, *args, **options):
        codes = set(options["permission"])
        permissions = list(Permission.objects.filter(code__in=codes))
        if {permission.code for permission in permissions} != codes:
            raise CommandError(
                "Há permissões inexistentes. Aplique as migrations e confira os códigos aprovados."
            )
        if (
            Tenant.objects.filter(slug=options["tenant_slug"]).exists()
            or User.objects.filter(username__iexact=options["username"]).exists()
        ):
            raise CommandError(
                "Organização ou usuário já existe; nenhum registro será sobrescrito."
            )
        if options["password_stdin"]:
            password = sys.stdin.readline(1026).rstrip("\r\n")
        else:
            password = getpass.getpass("Senha inicial (não será exibida): ")
            if password != getpass.getpass("Confirme a senha inicial: "):
                raise CommandError("As senhas não coincidem.")
        user = User(username=options["username"], is_staff=False, is_superuser=False)
        try:
            if not 12 <= len(password) <= 1024:
                raise ValidationError(
                    "A senha inicial deve ter entre 12 e 1024 caracteres."
                )
            validate_password(password, user)
            user.set_password(password)
            user.full_clean()
            with transaction.atomic():
                tenant = Tenant(
                    name=options["tenant_name"], slug=options["tenant_slug"]
                )
                tenant.full_clean()
                tenant.save()
                campaign = Campaign(
                    tenant=tenant,
                    name=options["campaign_name"],
                    code=options["campaign_code"],
                    election_id=options["election_id"],
                    office_code=options["office_code"],
                    jurisdiction_code=options["jurisdiction_code"],
                )
                campaign.full_clean()
                campaign.save()
                role = Role.objects.create(
                    tenant=tenant, code="initial-operator", name="Operador inicial"
                )
                role.permissions.set(permissions)
                user.save()
                SecurityProfile.objects.create(user=user, password_change_required=True)
                Membership.objects.create(
                    user=user,
                    tenant=tenant,
                    campaign=campaign,
                    role=role,
                    status="active",
                )
                append_audit_event(
                    actor=user,
                    tenant=tenant,
                    campaign=campaign,
                    action="security.operator_bootstrapped",
                    resource_type="user",
                    resource_id=user.pk,
                    minimized_diff={
                        "permissions": sorted(codes),
                        "password_change_required": True,
                    },
                )
        except (ValidationError, IntegrityError) as exc:
            # Do not serialize arbitrary validation/provider messages or inputs.
            raise CommandError(
                "Não foi possível criar o operador. Confira os campos e os requisitos da senha; nenhuma criação parcial foi mantida."
            ) from None
        finally:
            password = None
        self.stdout.write(
            self.style.SUCCESS(
                "Operador criado sem privilégios de superusuário. Troca de senha obrigatória; MFA exigido pelo perfil de produção."
            )
        )
