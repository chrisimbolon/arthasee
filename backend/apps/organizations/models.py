# =============================================================================
# === backend/apps/organizations/models.py ===
# =============================================================================
import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    """
    One row per bengkel (shop) using Arthasee. Everything
    tenant-scoped ultimately traces back to one of these — this is
    the actual isolation boundary, not just a label.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=200, verbose_name="Nama Bengkel")
    plan       = models.CharField(max_length=50, default="free", verbose_name="Paket")
    is_active  = models.BooleanField(default=True, verbose_name="Aktif")
    invoice_code = models.CharField(
        max_length=10, blank=True, default="", verbose_name="Kode Invoice",
        help_text=(
            "Kode singkat untuk penomoran invoice, mis. 'AM' untuk Arya Motor "
            "(menghasilkan INV/REG/AM/0001/2026). Harus diisi sebelum bengkel "
            "ini bisa membuat invoice — lihat apps.invoicing.models.Invoice.save() "
            "untuk pesan error jika kosong."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Organization"
        verbose_name_plural  = "Organizations"

    def __str__(self):
        return self.name


class OrganizationMembership(models.Model):
    """
    Who belongs to which shop, and with what role. TenantScopedAPIView
    reads this directly (user.memberships.filter(is_active=True)) to
    resolve which organizations a request is allowed to touch — this
    table IS the access-control mechanism, not a convenience layer
    on top of one.
    """
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships",
    )
    role       = models.CharField(max_length=50, default="member", verbose_name="Peran")
    is_active  = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Organization Membership"
        verbose_name_plural  = "Organization Memberships"
        unique_together      = [("organization", "user")]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"
