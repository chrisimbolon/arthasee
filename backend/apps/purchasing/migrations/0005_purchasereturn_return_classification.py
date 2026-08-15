# apps/purchasing/migrations/0005_purchasereturn_return_classification.py
#
# Simpler than the PurchaseOrder migration on purpose — no nullable
# → backfill → NOT NULL dance needed here. The old create_return()
# guard only ever allowed creation when the GRN had NO linked
# SupplierInvoice — meaning every PurchaseReturn row that exists
# today was NECESSARILY "before invoice" by construction of the code
# that made it. default="BEFORE_INVOICE" isn't a safe approximation
# here, the way PO-LEGACY's synthetic values were — it's the
# objectively, provably correct value for every possible historical
# row, so Django's own default-backfill-on-AddField is sufficient by
# itself.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0004_alter_goodsreceivednote_purchase_order_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchasereturn",
            name="return_classification",
            field=models.CharField(
                choices=[
                    ("BEFORE_INVOICE", "Sebelum Invoice (Retur ke Accrued Inventory)"),
                    ("AFTER_INVOICE_UNPAID", "Setelah Invoice, Belum Dibayar (Retur ke Utang)"),
                ],
                default="BEFORE_INVOICE",
                editable=False,
                max_length=30,
                verbose_name="Klasifikasi Retur",
            ),
        ),
    ]
