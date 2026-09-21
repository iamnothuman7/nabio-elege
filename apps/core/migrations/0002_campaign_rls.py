from django.db import migrations

from apps.core.rls_schema_v1 import install


class Migration(migrations.Migration):
    # Deliberately irreversible: rolling code back must not silently remove RLS.
    dependencies = [
        ("core", "0001_initial"),
        ("workspace", "0007_legalcaseaccess"),
        ("forms", "0003_formversion_created_by"),
        ("finance", "0003_accountingbatch_manifest_json"),
        ("operations", "0001_initial"),
    ]
    operations = [migrations.RunPython(install)]
