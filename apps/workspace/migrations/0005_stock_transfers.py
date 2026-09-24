import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0003_seed_operations_permissions"),
        ("operations", "0001_initial"),
        ("workspace", "0004_electoral_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(model_name="stockreservation", name="status", field=models.CharField(choices=[("active", "Ativa"), ("released", "Liberada"), ("consumed", "Consumida"), ("expired", "Expirada")], default="active", max_length=16)),
        migrations.CreateModel(
            name="StockTransfer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1)),
                ("quantity", models.DecimalField(decimal_places=4, max_digits=18, verbose_name="Quantidade a enviar")),
                ("received_quantity", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("returned_quantity", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("purpose", models.CharField(max_length=180, verbose_name="Finalidade operacional")),
                ("status", models.CharField(choices=[("draft", "Preparando envio"), ("in_transit", "Em trânsito"), ("received", "Recebida integralmente"), ("returned", "Saldo devolvido à origem"), ("cancelled", "Cancelada antes do envio")], default="draft", max_length=16)),
                ("dispatched_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="campaigns.campaign")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("destination_warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incoming_transfers", to="operations.warehouse")),
                ("dispatched_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.stockitem")),
                ("source_warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="outgoing_transfers", to="operations.warehouse")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="campaigns.tenant")),
            ],
        ),
        migrations.CreateModel(
            name="StockTransferReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1)),
                ("kind", models.CharField(choices=[("receive", "Recebimento no destino"), ("return", "Devolução à origem")], max_length=16)),
                ("quantity", models.DecimalField(decimal_places=4, max_digits=18)),
                ("evidence_reference", models.CharField(max_length=180, verbose_name="Comprovante operacional")),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="campaigns.campaign")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("movement", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="operations.stockmovement")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="campaigns.tenant")),
                ("transfer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipts", to="workspace.stocktransfer")),
            ],
        ),
        migrations.AddIndex(model_name="stocktransfer", index=models.Index(fields=["campaign", "status"], name="stock_transfer_campaign_status")),
        migrations.AddConstraint(model_name="stocktransfer", constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transfer_quantity_positive")),
        migrations.AddConstraint(model_name="stocktransfer", constraint=models.CheckConstraint(condition=~models.Q(source_warehouse=models.F("destination_warehouse")), name="transfer_different_warehouses")),
        migrations.AddConstraint(model_name="stocktransfer", constraint=models.CheckConstraint(condition=models.Q(received_quantity__gte=0, returned_quantity__gte=0), name="transfer_settled_nonnegative")),
        migrations.AddConstraint(model_name="stocktransfer", constraint=models.CheckConstraint(condition=models.Q(quantity__gte=models.F("received_quantity") + models.F("returned_quantity")), name="transfer_settled_within_total")),
        migrations.AddConstraint(model_name="stocktransferreceipt", constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transfer_receipt_positive")),
    ]
