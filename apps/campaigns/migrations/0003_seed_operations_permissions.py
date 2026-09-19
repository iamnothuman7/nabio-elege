from django.db import migrations


PERMISSIONS = [
    ("tasks.manage.campaign", "tasks", "manage", "Gerenciar projetos e tarefas"),
    ("purchases.create.campaign", "purchases", "create", "Criar solicitações de compra"),
    ("purchases.approve.campaign", "purchases", "approve", "Aprovar compras"),
    ("purchases.receive.campaign", "purchases", "receive", "Confirmar recebimentos"),
    ("stock.manage.campaign", "stock", "manage", "Gerenciar estoque"),
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
    dependencies = [("campaigns", "0002_seed_permissions")]

    operations = [migrations.RunPython(seed_permissions, unseed_permissions)]
