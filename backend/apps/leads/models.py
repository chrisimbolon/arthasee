# =============================================================================
# === backend/apps/leads/models.py ===
# =============================================================================
"""
Arthasee — Leads

RejectedQuote captures what Made described directly: a rough,
verbal-stage estimate that a prospective customer said no to, before
any Customer/Vehicle/WorkOrder record exists. His own words: "no
money today doesn't mean no money forever" — this is purely a
follow-up and pricing-insight tool, not part of the operational
service pipeline.

Deliberately NOT linked to Customer, Vehicle, or WorkOrder — Made
confirmed he's fine creating those manually himself if/when someone
from this list actually comes back. No auto-conversion, no foreign
keys into the rest of the domain. This also means RejectedQuote is
genuinely mutable at any time — unlike ServiceRecord/Invoice, this
is a live working record (a to-do list, functionally), not a
historical one, so there's no append-only discipline to protect here.
"""
import uuid

from django.db import models

from apps.core.models import TenantScopedModel


class RejectedQuote(TenantScopedModel):
    REASON_CHOICES = [
        ("TOO_EXPENSIVE",   "Harga Terlalu Mahal"),
        ("WENT_ELSEWHERE",  "Pilih Bengkel Lain"),
        ("POSTPONED",       "Ditunda Dulu"),
        ("NOT_NEEDED",      "Diputuskan Tidak Perlu"),
        ("OTHER",           "Lainnya"),
    ]
    FOLLOW_UP_STATUS_CHOICES = [
        ("PENDING",   "Belum Dihubungi"),
        ("CONTACTED", "Sudah Dihubungi"),
        ("CONVERTED", "Jadi Pelanggan"),
        ("CLOSED",    "Ditutup"),
    ]

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name  = models.CharField(max_length=200, verbose_name="Nama")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Nomor Telepon")

    # Free text, deliberately not a Vehicle FK — this stage is
    # genuinely rough (Made's own words: "often someone brand new"),
    # and forcing a formal Vehicle record onto a verbal estimate
    # would misrepresent how uncommitted this stage actually is.
    vehicle_description = models.CharField(max_length=255, blank=True, verbose_name="Deskripsi Kendaraan")
    quoted_description   = models.TextField(blank=True, verbose_name="Deskripsi Pekerjaan yang Ditawarkan")
    quoted_amount         = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Estimasi Biaya",
    )

    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="OTHER", verbose_name="Alasan Penolakan")
    notes   = models.TextField(blank=True, verbose_name="Catatan")

    follow_up_status = models.CharField(
        max_length=20, choices=FOLLOW_UP_STATUS_CHOICES, default="PENDING", verbose_name="Status Follow-up",
        help_text="Filter ke PENDING untuk daftar telepon-balik pribadi Made.",
    )

    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Rejected Quote"
        verbose_name_plural  = "Rejected Quotes"
        ordering             = ["-created_at"]

    def __str__(self):
        return f"{self.name} — {self.get_reason_display()}"
