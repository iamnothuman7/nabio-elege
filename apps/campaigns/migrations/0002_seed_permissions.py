from django.db import migrations


PERMISSIONS = [
    ("campaigns.read.campaign", "campaigns", "read", "Consultar campanha"),
    ("campaigns.manage.campaign", "campaigns", "manage", "Configurar campanha"),
    ("memberships.manage.campaign", "memberships", "manage", "Gerenciar vínculos"),
    ("audit.read.campaign", "audit", "read", "Consultar auditoria"),
    ("documents.create.campaign", "documents", "create", "Enviar documentos"),
    ("documents.download.resource", "documents", "download", "Baixar documento"),
    ("forms.create.campaign", "forms", "create", "Criar formulários"),
    ("forms.review.campaign", "forms", "review", "Revisar formulários"),
    ("forms.publish.campaign", "forms", "publish", "Publicar formulários"),
    ("submissions.read.campaign", "submissions", "read", "Triar respostas"),
    ("submissions.assist.assigned", "submissions", "assist", "Realizar cadastro assistido"),
    ("people.read.assigned", "people", "read", "Consultar pessoas atribuídas"),
    ("people.export.campaign", "people", "export", "Exportar pessoas"),
    ("privacy.handle.campaign", "privacy", "handle", "Tratar direitos de titulares"),
    ("finance.create.campaign", "finance", "create", "Criar obrigação financeira"),
    ("finance.approve.campaign", "finance", "approve", "Aprovar obrigação financeira"),
    ("finance.reconcile.campaign", "finance", "reconcile", "Conciliar operações"),
]


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("campaigns", "Permission")
    for code, resource, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "resource": resource,
                "action": action,
                "scope": "campaign",
                "description": description,
            },
        )


def unseed_permissions(apps, schema_editor):
    Permission = apps.get_model("campaigns", "Permission")
    Permission.objects.filter(code__in=[item[0] for item in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("campaigns", "0001_initial")]

    operations = [migrations.RunPython(seed_permissions, unseed_permissions)]
