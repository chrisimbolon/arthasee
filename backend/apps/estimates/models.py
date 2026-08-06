# =============================================================================
# === backend/apps/estimates/models.py ===
# =============================================================================
"""
Arthasee — Estimates

Closes the loop Sansan's original flow always needed: Estimasi ->
Persetujuan Pelanggan -> Work Order. Confirmed with Chris/Made:

  - Estimate is purely speculative — EstimateLineItem NEVER touches
    real stock. This is the whole point: a proposed quote for a
    scarce part must not falsely lock inventory away from another
    customer before the customer has even said yes. Only
    Estimate.approve() creates real, stock-deducting
    WorkOrderMaterialLine rows — at the exact moment work is
    actually authorized, not before.
  - Same "mutable speculative record -> real committed record"
    promotion pattern already proven twice in this codebase
    (PartUsage -> Invoice, WorkOrder -> ServiceRecord). Nothing about
    WorkOrder itself changes to support this — Estimate holds a
    nullable pointer to the WorkOrder it produced (mirrors
    WorkOrder.service_record's own direction exactly), and Django's
    reverse accessor means a WorkOrder can always look back at its
    originating Estimate for free.
  - Rejection here is deliberately NOT the same object as
    apps.leads.RejectedQuote. Made's own description of "track
    rejected quotes for pricing decisions" was specifically about the
    pre-arrival, often-brand-new-customer stage. An Estimate always
    has a real Vehicle (the car has physically arrived by the time
    diagnosis/estimation happens) — analytically similar event, but a
    meaningfully different moment in the process. Kept separate for
    v1; revisit unification only if real usage demands it.
  - Invoice pricing is deliberately NOT locked to the approved
    Estimate — Made's own example (a mechanic finding an extra fault
    mid-repair, getting fresh WhatsApp approval) confirms final work
    legitimately diverges from the original quote. The frontend
    should show the original quoted total as a reference at
    invoice-creation time, not enforce it.
"""
import uuid

from apps.core.models import TenantScopedModel
from apps.inventory.models import Part
from django.db import models, transaction


class EstimateSequence(TenantScopedModel):
    """
    One row per organization — plain sequential numbering, same
    choice as WorkOrderSequence (no prefix, no year scoping). Not
    exposed via any API; purely internal plumbing.
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Estimate Sequence"
        verbose_name_plural  = "Estimate Sequences"
        unique_together      = [("organization",)]

    def __str__(self):
        return f"{self.organization}: {self.last_sequence}"

    @classmethod
    def next_number(cls, organization):
        """
        Atomically claims the next sequence number. Must be called
        from inside an atomic block — select_for_update() requires an
        active transaction to attach its row lock to. This exact gap
        (a view creating an Estimate/WorkOrder without wrapping the
        call in transaction.atomic()) already caused a real production
        failure once for WorkOrder; the view layer here wraps
        Estimate creation the same way from the start.
        """
        seq, _ = cls.objects.select_for_update().get_or_create(
            organization=organization, defaults={"last_sequence": 0},
        )
        seq.last_sequence += 1
        seq.save(update_fields=["last_sequence"])
        return seq.last_sequence


class Estimate(TenantScopedModel):
    """
    A proposed, not-yet-authorized quote for a vehicle that has
    already arrived. Genuinely mutable while PENDING; promotes into a
    real WorkOrder on approval, or simply records why on rejection.
    """
    STATUS_CHOICES = [
        ("PENDING",  "Menunggu Persetujuan"),
        ("APPROVED", "Disetujui"),
        ("REJECTED", "Ditolak"),
    ]
    REASON_CHOICES = [
        ("TOO_EXPENSIVE",  "Harga Terlalu Mahal"),
        ("WENT_ELSEWHERE", "Pilih Bengkel Lain"),
        ("POSTPONED",      "Ditunda Dulu"),
        ("NOT_NEEDED",     "Diputuskan Tidak Perlu"),
        ("OTHER",          "Lainnya"),
    ]

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        "service.Vehicle", on_delete=models.PROTECT, related_name="estimates", verbose_name="Kendaraan",
    )
    number          = models.CharField(max_length=20, editable=False, verbose_name="Nomor Estimasi")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING", verbose_name="Status")

    diagnosis_notes = models.TextField(blank=True, verbose_name="Catatan Diagnosa")

    odometer_km_intake = models.PositiveIntegerField(null=True, blank=True, verbose_name="KM Saat Masuk")

    rejection_reason = models.CharField(max_length=20, choices=REASON_CHOICES, blank=True, verbose_name="Alasan Penolakan")
    rejection_notes   = models.TextField(blank=True, verbose_name="Catatan Penolakan")

    work_order = models.OneToOneField(
        "workorders.WorkOrder", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="estimate", verbose_name="Work Order",
    )

    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Estimate"
        verbose_name_plural  = "Estimates"
        ordering             = ["-created_at"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return f"EST {self.number} — {self.vehicle.plate_number}"

    def _resolve_organization(self):
        return self.vehicle.organization

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            org = self._resolve_organization()
            self.sequence_number = EstimateSequence.next_number(org)
            self.number = str(self.sequence_number)
        super().save(*args, **kwargs)

    def approve(self, approved_by=None):
        """
        Promotes this Estimate into a real WorkOrder. Every part-kind
        line becomes a genuine WorkOrderMaterialLine — the exact
        moment stock actually moves, never before this call. Labor
        lines have nowhere priced to go on WorkOrder (it only tracks
        free-text job descriptions), so the quoted price is folded
        into the description text itself, visible to whoever works
        the job, rather than inventing a new priced-line concept on a
        model that's already proven and shouldn't be touched.
        """
        # Local import, same cross-app reasoning as every other
        # local import in this project (e.g. WorkOrder.close()'s own
        # ServiceRecord import) — apps.estimates depends on
        # apps.letters, not the other way around.
        from apps.letters.models import OutgoingLetter
        from apps.workorders.models import (WorkOrder, WorkOrderJobLine,
                                            WorkOrderMaterialLine)

        if self.status != "PENDING":
            raise ValueError("Hanya estimasi yang masih menunggu persetujuan yang bisa disetujui.")

        with transaction.atomic():
            work_order = WorkOrder.objects.create(
                organization=self.organization, vehicle=self.vehicle, created_by=approved_by,
                # Carries the diagnosis forward so whoever picks up
                # the Work Order doesn't have to retype context
                # already recorded at estimate time — still fully
                # editable afterward via WorkOrder's own PUT endpoint,
                # this is just a helpful starting point, not a link
                # that stays synced.
                notes=self.diagnosis_notes,
                # Chris's explicit call, 31 Jul: carry forward
                # automatically, no re-entry — this was already
                # captured and validated once at estimate time.
                odometer_km_intake=self.odometer_km_intake,
            )
            for line in self.line_items.all():
                if line.kind == "labor":
                    price_text = f"{line.unit_price:,.0f}".replace(",", ".")
                    label = f"{line.description} (estimasi Rp {price_text})"
                    WorkOrderJobLine.objects.create(
                        organization=self.organization, work_order=work_order, description=label,
                    )
                elif line.kind == "part" and line.part_id:
                    WorkOrderMaterialLine.objects.create(
                        organization=self.organization, work_order=work_order,
                        part=line.part, quantity=line.quantity,
                    )
            self.status = "APPROVED"
            self.work_order = work_order
            self.save(update_fields=["status", "work_order", "updated_at"])

            # D1 (Surat Keluar), Chris's own confirmed trigger, 6 Aug
            # — an approved Estimate is the real, official moment a
            # document goes out authorizing the work. Same
            # transaction as everything above: a failure here rolls
            # back the WorkOrder too, rather than leaving an approved
            # Estimate with no corresponding letter. Silently skipped
            # if the org has no invoice_code configured yet, rather
            # than blocking Estimate approval entirely over a
            # Settings gap unrelated to the estimate itself — real
            # invoice creation already has its own hard block for
            # this (see Invoice.save()), so nothing about billing
            # integrity depends on this letter existing.
            if self.organization.invoice_code:
                OutgoingLetter.objects.create(
                    organization=self.organization, source="ESTIMATE_APPROVAL", estimate=self,
                    recipient=self.vehicle.customer.name,
                    subject=f"Persetujuan Estimasi {self.number} — {self.vehicle.plate_number}",
                    created_by=approved_by,
                )

        return work_order

    def reject(self, reason="OTHER", notes=""):
        if self.status != "PENDING":
            raise ValueError("Hanya estimasi yang masih menunggu persetujuan yang bisa ditolak.")
        self.status = "REJECTED"
        self.rejection_reason = reason
        self.rejection_notes = notes
        self.save(update_fields=["status", "rejection_reason", "rejection_notes", "updated_at"])


class EstimateLineItem(TenantScopedModel):
    """
    One proposed charge — part or labor, mirroring InvoiceLineItem's
    own kind/description/quantity/unit_price shape for a consistent
    rendering story across the two models. Deliberately no stock
    interaction of any kind here — see the module docstring.
    """
    KIND_CHOICES = [
        ("part",  "Part"),
        ("labor", "Jasa"),
    ]

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    estimate   = models.ForeignKey(Estimate, on_delete=models.CASCADE, related_name="line_items", verbose_name="Estimasi")
    kind       = models.CharField(max_length=10, choices=KIND_CHOICES, verbose_name="Jenis")
    description = models.CharField(max_length=255, verbose_name="Deskripsi")
    quantity    = models.DecimalField(max_digits=10, decimal_places=2, default=1, verbose_name="Jumlah")
    unit_price  = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga Satuan")
    part = models.ForeignKey(
        Part, on_delete=models.PROTECT, null=True, blank=True,
        related_name="estimate_line_items", verbose_name="Part",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Estimate Line Item"
        verbose_name_plural  = "Estimate Line Items"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.description} × {self.quantity}"

    def _resolve_organization(self):
        return self.estimate.organization

    @property
    def subtotal(self):
        return self.quantity * self.unit_price
