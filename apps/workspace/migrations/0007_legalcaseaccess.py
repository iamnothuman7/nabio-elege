import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def seed_existing_case_access(apps, schema_editor):
    alias = schema_editor.connection.alias
    Case = apps.get_model("workspace", "LegalCase")
    Access = apps.get_model("workspace", "LegalCaseAccess")
    Member = apps.get_model("campaigns", "Membership")
    for case in Case.objects.using(alias).iterator():
        members = Member.objects.using(alias).filter(campaign_id=case.campaign_id, tenant_id=case.tenant_id, status="active", revoked_at__isnull=True).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now()))
        owner = members.filter(user_id=case.created_by_id).first() if case.created_by_id else None
        responsible = members.filter(pk=case.responsible_id).first() if case.responsible_id else None
        manager = owner or responsible
        for member in [owner, responsible]:
            if member:
                Access.objects.using(alias).get_or_create(legal_case_id=case.pk, membership_id=member.pk, defaults={"tenant_id": case.tenant_id, "campaign_id": case.campaign_id, "created_by_id": case.created_by_id, "can_manage_access": member.pk == manager.pk})


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0003_seed_operations_permissions"),
        ("workspace", "0006_password_lifecycle"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="LegalCaseAccess",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1)),
                ("can_manage_access", models.BooleanField(default=False)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="campaigns.campaign")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("legal_case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="access_grants", to="workspace.legalcase")),
                ("membership", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="campaigns.membership")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="campaigns.tenant")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("legal_case", "membership"), name="uniq_legal_case_membership")]},
        ),
        migrations.RunPython(seed_existing_case_access, migrations.RunPython.noop),
    ]
