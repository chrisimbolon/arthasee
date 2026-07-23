# =============================================================================
# === backend/apps/inventory/models.py ===
# =============================================================================
"""
Arthasee — Inventory

Split out of apps.service (where it originated in Sprint 1) into its
own app ahead of Sprint 2 — invoicing needs to reference Part
directly for line items, and keeping it inside apps.service would
mean invoicing importing from an unrelated domain's models, exactly
the cross-app coupling the organizations/service split otherwise
avoids.

Real production data already exists in these tables (Part rows,
stock counts, PartUsage history) — see this app's migrations/0001_
initial.py and apps/service/migrations/0004_... for how the move
happens without losing or recreating any of it: a migration-state
relabel plus a table rename, not a drop-and-recreate.
"""
import uuid

from apps.core.models import TenantScopedModel
from django.db import models


class Part(TenantScopedModel):
    """
    One catalog entry in a shop's parts inventory. Organization is
    set explicitly by the view at creation time — same pattern as
    Customer, since a Part doesn't derive its org from any other
    relation the way ServiceRecord derives its org from Vehicle.

    `current_stock` is denormalized, same philosophy as Vehicle's
    last_service_* fields: the true source of truth is the sum of
    every PartUsage (negative) and StockAdjustment (positive/
    negative) ever recorded against this Part, but reading that sum
    on every request would be needlessly expensive. Both PartUsage
    and StockAdjustment update this field atomically via
    `F("current_stock") ± quantity` on save — see below — so it's
    always correct without a recompute step.
    """
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="Nama Part")
    sku  = models.CharField(
        max_length=50, blank=True, verbose_name="Kode/SKU",
        help_text="Opsional — kode internal bengkel untuk part ini, jika ada.",
    )
    # Decimal, not integer — oli (oil) is sold/consumed by the liter,
    # a genuinely fractional unit.
    unit = models.CharField(
        max_length=20, default="pcs", verbose_name="Satuan",
        help_text="pcs, liter, set, botol, dll.",
    )
    current_stock = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Stok Saat Ini",
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Harga Satuan",
        help_text="Harga jual per satuan saat ini — perubahan di sini tidak mengubah riwayat pemakaian yang sudah tercatat.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Part"
        verbose_name_plural  = "Parts"
        ordering             = ["name"]

    def __str__(self):
        return f"{self.name} ({self.current_stock} {self.unit})"


class PartUsage(TenantScopedModel):
    """
    One line of "this Part was used on this ServiceRecord." Creating
    one atomically decrements Part.current_stock — the mechanism
    behind Made's own "G inventory 20−4=16" note.

    `service_record` is a cross-app FK (to apps.service.ServiceRecord)
    — referenced by string ("service.ServiceRecord") rather than a
    direct class import, standard Django practice for cross-app FKs
    that avoids any import-ordering questions between the two apps.

    `unit_price_at_time` is a deliberate snapshot, not a live
    reference to Part.unit_price — a price change next month must
    never silently rewrite the effective cost of a past service
    record. Same instinct as ServiceRecord being append-only: history
    should not move once written.
    """
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_record = models.ForeignKey(
        "service.ServiceRecord", on_delete=models.CASCADE, related_name="part_usages",
        verbose_name="Catatan Servis",
        # CASCADE (not PROTECT) is safe specifically because
        # ServiceRecord has no delete endpoint at all — there is
        # currently no code path that could ever cascade-delete a
        # PartUsage as a side effect. If a delete endpoint is ever
        # added to ServiceRecord, this decision needs revisiting.
    )
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name="usages",
        verbose_name="Part",
        # PROTECT — same Principle 2 reasoning as everywhere else. A
        # Part that's never been used can be deleted freely; one with
        # real usage history cannot.
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jumlah")
    unit_price_at_time = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Harga Saat Digunakan",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Part Usage"
        verbose_name_plural  = "Part Usages"
        ordering             = ["-created_at"]

    def __str__(self):
        return f"{self.part.name} × {self.quantity} — {self.service_record}"

    def _resolve_organization(self):
        return self.service_record.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.unit_price_at_time:
            self.unit_price_at_time = self.part.unit_price
        super().save(*args, **kwargs)
        if creating:
            # F() expression, not read-modify-write — avoids a race
            # condition if two mechanics log usage of the same part
            # at the same moment. Deliberately allowed to go negative
            # (see PartUsageSerializer.validate for why) rather than
            # hard-blocking here at the model layer.
            Part.objects.filter(pk=self.part_id).update(
                current_stock=models.F("current_stock") - self.quantity
            )


class StockAdjustment(TenantScopedModel):
    """
    Every non-usage change to a Part's stock — restocking after a
    purchase, correcting a miscount, writing off damaged/lost stock.
    Without this, current_stock could only ever go down after a
    Part's initial creation value.
    """
    REASON_CHOICES = [
        ("restock",    "Restock / Pembelian"),
        ("correction", "Koreksi Stok"),
        ("damage",     "Rusak / Hilang"),
        ("work_order_cancelled", "Pembatalan Work Order"),
    ]

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, related_name="adjustments",
        verbose_name="Part",
    )
    quantity_change = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Perubahan Jumlah")
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="restock", verbose_name="Alasan")
    notes  = models.TextField(blank=True, verbose_name="Catatan")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Stock Adjustment"
        verbose_name_plural  = "Stock Adjustments"
        ordering             = ["-created_at"]

    def __str__(self):
        sign = "+" if self.quantity_change >= 0 else ""
        return f"{self.part.name} {sign}{self.quantity_change} ({self.get_reason_display()})"

    def _resolve_organization(self):
        return self.part.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            Part.objects.filter(pk=self.part_id).update(
                current_stock=models.F("current_stock") + self.quantity_change
            )
