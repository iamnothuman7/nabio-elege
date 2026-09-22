"""Explicit, atomic conversion. Secrets arrive only on stdin and are never echoed."""

import json
import sys

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.workspace.direct_access import prepare_direct_access


class Command(BaseCommand):
    help = "Configura acesso direto para duas contas e separa um cliente real da demonstração."

    def add_arguments(self, parser):
        for name in (
            "admin-username",
            "customer-username",
            "new-customer-username",
            "tenant-slug",
            "customer-name",
        ):
            parser.add_argument("--" + name, required=True)
        parser.add_argument("--passwords-stdin", action="store_true", required=True)
        parser.add_argument(
            "--confirm-password-only", action="store_true", required=True
        )

    def handle(self, *args, **options):
        credentials = {}
        try:
            credentials = json.loads(sys.stdin.read(8193))
            campaign = prepare_direct_access(
                **{
                    name: options[name]
                    for name in (
                        "admin_username",
                        "customer_username",
                        "new_customer_username",
                        "tenant_slug",
                        "customer_name",
                    )
                },
                admin_password=credentials["admin_password"],
                customer_password=credentials["customer_password"],
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            ValidationError,
            PermissionDenied,
            IntegrityError,
        ):
            raise CommandError(
                "Operação recusada. Confira as contas, nomes, vínculo demo e senhas; nenhuma alteração parcial foi mantida."
            ) from None
        finally:
            credentials = None
        self.stdout.write(
            json.dumps(
                {"direct_access_configured": True, "campaign_id": str(campaign.pk)}
            )
        )
