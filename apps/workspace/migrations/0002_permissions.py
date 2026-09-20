from django.db import migrations


PERMISSIONS = [
    "finance.read.campaign", "finance.export.campaign", "events.manage.campaign", "events.approve.campaign",
    "assets.manage.campaign", "logistics.manage.campaign", "logistics.approve.campaign",
    "legal.manage.campaign", "legal.approve.campaign", "rules.manage.campaign", "rules.approve.campaign",
    "documents.read.campaign", "documents.read_personal.campaign", "documents.read_financial.campaign", "documents.read_legal.campaign",
    "closure.manage.campaign", "service.manage.campaign", "service.read_payload.assigned",
    "content.manage.campaign", "content.approve.campaign", "proposals.manage.campaign", "proposals.approve.campaign",
    "results.manage.campaign", "election.manage.campaign", "election.approve.campaign", "reports.read.campaign", "reports.export.campaign",
]


def seed(apps, schema_editor):
    Permission = apps.get_model("campaigns", "Permission")
    for code in PERMISSIONS:
        resource, action, scope = code.split(".")
        Permission.objects.get_or_create(code=code, defaults={"resource": resource, "action": action, "scope": scope})
    for permission in Permission.objects.all():
        permission.scope = permission.code.rsplit(".", 1)[-1]
        permission.save(update_fields=["scope"])


class Migration(migrations.Migration):
    dependencies = [("workspace", "0001_initial"), ("campaigns", "0003_seed_operations_permissions")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
