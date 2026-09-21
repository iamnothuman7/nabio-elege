from django.core.management.base import BaseCommand, CommandError

from apps.core.rls import verify_database_isolation


class Command(BaseCommand):
    help = "Verifica RLS e privilégios do usuário de execução, sem modificar o banco."

    def handle(self, *args, **options):
        try:
            valid = verify_database_isolation()
        except Exception:
            valid = False
        if not valid:
            raise CommandError(
                "RLS não homologado: confira políticas, migrations e o papel restrito de execução. Nenhuma credencial foi exibida."
            )
        self.stdout.write(
            self.style.SUCCESS("RLS obrigatório e papel de execução restrito: OK.")
        )
