# =============================================================================
# === backend/apps/organizations/models.py ===
# =============================================================================
import re
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
            "(menghasilkan INV/REG/AM/0001/2026). Diisi otomatis dari nama "
            "bengkel saat pendaftaran (lihat Organization.save() /"
            "_generate_invoice_code() di bawah) — pemilik bisa mengubahnya "
            "kapan saja di Pengaturan Bengkel."
        ),
    )
    daily_appointment_capacity = models.PositiveIntegerField(
        default=4, verbose_name="Kapasitas Janji Temu Harian",
        help_text=(
            "Made's own confirmed number, 19 Aug — jumlah maksimum janji "
            "temu online per hari, mencerminkan ketersediaan mekanik nyata "
            "yang berubah-ubah, bukan kapasitas fisik bengkel (Arthasee "
            "tidak melacak jadwal mekanik per hari). Bisa diubah kapan saja "
            "di Pengaturan Bengkel."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Organization"
        verbose_name_plural  = "Organizations"

    def __str__(self):
        return self.name

    # Real legal-entity prefixes recognized in Indonesian business
    # registration (CV, PT, UD) — deliberately NOT stripping generic
    # descriptive words like "Bengkel," which a real owner might
    # reasonably want reflected in their own generated code.
    _LEGAL_PREFIX_RE = re.compile(r"^\s*(CV|PT|UD)\.?\s+", re.IGNORECASE)

    def save(self, *args, **kwargs):
        # Chris's own explicit call, 5 Aug: registration stays
        # completely frictionless (name, email, password, shop name
        # only) — invoice_code never appears on the signup form at
        # all. A real fallback is auto-generated from the shop's own
        # name at creation time instead, so the system always has a
        # valid, usable code from the very first save — Made can
        # customize it any time afterward in a real Organization
        # Settings page. Only fires on CREATE, and only when nothing
        # was explicitly provided — never silently overwrites a real,
        # already-set or owner-customized code on a later save.
        if self._state.adding and not self.invoice_code:
            self.invoice_code = self._generate_invoice_code()
        super().save(*args, **kwargs)

    def _generate_invoice_code(self):
        """
        Real precedent for the algorithm itself, not an arbitrary
        choice: Arya Motor's own actual code, "AM", is exactly what
        this produces from "CV. Arya Motor" — strip the real
        Indonesian legal-entity prefix (CV/PT/UD), then initial the
        first few remaining significant words.

        Real, acknowledged tradeoff, not a silent landmine: two
        different shops with similar names COULD land on the same
        generated code (e.g. two "Motor Jaya"s both -> "MJ").
        invoice_code has no DB-level uniqueness constraint (see the
        field's own help_text) — this is a sensible fallback, not a
        hard guarantee, and it's editable in Settings at any time. A
        real global-uniqueness guarantee would need a cross-org
        registry, disproportionate for what this actually protects
        against (Invoice.save()'s own real concern is a MISSING code,
        not a rare shared one).
        """
        cleaned = self._LEGAL_PREFIX_RE.sub("", self.name or "").strip()
        words = re.findall(r"[A-Za-z]+", cleaned)
        if not words:
            return "ORG"
        if len(words) == 1:
            # A single-word name (or nothing left after stripping the
            # legal prefix) can't produce meaningful initials — the
            # first few letters of the word itself reads better than
            # a lone single character ("Arthasee" -> "ART", not "A").
            code = words[0][:3].upper()
        else:
            code = "".join(w[0] for w in words[:4]).upper()
        return code[:10] or "ORG"


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
