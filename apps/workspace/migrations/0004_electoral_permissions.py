from django.db import migrations


def seed(apps, schema_editor):
    Permission = apps.get_model("campaigns", "Permission")
    for code in ["territories.read.campaign", "territories.manage.campaign", "field.manage.campaign", "field.approve.campaign", "electors.read.assigned", "electors.read.campaign", "electors.create.assigned", "electors.review.campaign"]:
        resource, action, scope = code.split(".")
        Permission.objects.get_or_create(code=code, defaults={"resource": resource, "action": action, "scope": scope})


class Migration(migrations.Migration):
    dependencies = [("workspace", "0003_campaignbase_electorregistration_territory_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
