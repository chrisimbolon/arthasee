# =============================================================================
# === backend/apps/organizations/migrations/0007_organization_logo.py ===
# =============================================================================
"""
6 Oct 2026 — Organization.logo. Purely additive: AddField only, no
existing column altered, no existing row touched (every current
organization simply has NULL here until an owner uploads one via
OrganizationLogoView). Reverse is Django's own default DROP COLUMN —
safe, since nothing has ever been written to a column that doesn't
exist yet.

Real dependency confirmed: `ls backend/apps/organizations/migrations/ |
sort | tail -3` showed 0006_organization_requires_sequential_period_
closing as the latest migration in this app. Named
0007_organization_logo.py accordingly.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0006_organization_requires_sequential_period_closing"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="logo",
            field=models.ImageField(
                blank=True, null=True, upload_to="organization_logos/%Y/%m/",
                help_text="Ditampilkan di Pengaturan Bengkel dan pada invoice PDF.",
                verbose_name="Logo Bengkel",
            ),
        ),
    ]
