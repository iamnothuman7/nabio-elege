from django.core.management.base import BaseCommand

from apps.workspace.inventory import expire_due_reservations


class Command(BaseCommand):
    help = "Libera reservas de estoque vencidas, com auditoria, sem alterar campanhas arquivadas."

    def handle(self, *args, **options):
        count = expire_due_reservations()
        self.stdout.write(self.style.SUCCESS(f"{count} reserva(s) expirada(s) e saldo liberado."))
