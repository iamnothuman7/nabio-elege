from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workspace", "0005_stock_transfers")]
    operations = [
        migrations.AddField(model_name="securityprofile", name="password_change_required", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="securityprofile", name="password_changed_at", field=models.DateTimeField(blank=True, null=True)),
    ]
