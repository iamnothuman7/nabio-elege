from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import get_template


class Command(BaseCommand):
    help = "Compila todos os templates do projeto e recusa erros de sintaxe ou dependências ausentes."

    def handle(self, *args, **options):
        count = 0
        for app in apps.get_app_configs():
            if not app.name.startswith("apps."):
                continue
            root = Path(app.path) / "templates"
            for path in root.rglob("*.html"):
                name = path.relative_to(root).as_posix()
                try:
                    get_template(name)
                except (TemplateDoesNotExist, TemplateSyntaxError):
                    raise CommandError(f"Template inválido: {name}") from None
                count += 1
        self.stdout.write(
            self.style.SUCCESS(f"{count} templates compilados sem erro de sintaxe.")
        )
