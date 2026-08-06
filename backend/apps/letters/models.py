# =============================================================================
# === backend/apps/letters/models.py ===
# =============================================================================
"""
Arthasee — Surat Masuk / Surat Keluar (D1)

Made's own confirmed answer, 4 Aug meeting, resolved further via a
direct phone call 6 Aug: outgoing letters get a real, sequential,
auto-generated document number; incoming letters get scanned/
uploaded with just enough metadata to stay genuinely searchable, not
a blind file drop.

Own app, not folded into apps.invoicing (which already owns a
sequence-numbering pattern this mirrors) — a letter is a genuinely
different kind of document than a financial one, and this app's own
two real trigger points (Estimate.approve(), ContractImport.apply())
live in two OTHER apps entirely. Keeping this separate avoids forcing
either of those apps to import a numbering concept that isn't really
theirs.

Two real, confirmed trigger points for auto-generated Surat Keluar,
Chris's own explicit call, 6 Aug:
  - Estimate.approve() — the moment a quote is authorized, an
    official document (implicitly) goes out to the customer.
  - ContractImport.apply() — specifically: the moment a contract's
    scope/budget is confirmed, a real letter requesting or
    withdrawing funds goes out to the institutional client. NOT
    Contract creation itself, and NOT tied to any individual
    TerminPeriod becoming due — confirmed directly by phone, 6 Aug.

A third path — a standalone "Buat Surat" action for anything with no
WorkOrder/Estimate/Contract origin at all — exists purely as a manual
entry point sharing the exact same numbering sequence. One shared
LetterSequence, not one per origin: this mirrors how a real physical
"buku agenda surat keluar" registry actually works — one continuous
log, regardless of what a given letter was actually about.
"""
import uuid
from datetime import date

from apps.core.models import TenantScopedModel
from django.db import models

# Only 12 values ever needed — a lookup table is the honest choice
# here, not a general Roman-numeral algorithm nothing else in this
# app would ever reuse.
ROMAN_MONTHS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


class LetterSequence(TenantScopedModel):
    """
    Tracks the last outgoing-letter sequence number per (organization,
    year) — mirrors apps.invoicing.models.InvoiceSequence's exact
    pattern (same select_for_update()-inside-atomic discipline, same
    per-year reset), reused deliberately rather than reinvented, for
    the same reason it was reused a second and third time elsewhere
    in this project: it already solves the real concurrency problem
    (two letters created in the same instant can't both claim the
    same number). Not exposed via any API — purely internal plumbing
    behind OutgoingLetter.save().
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    year          = models.PositiveIntegerField(verbose_name="Tahun")
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Letter Sequence"
        verbose_name_plural  = "Letter Sequences"
        unique_together      = [("organization", "year")]

    def __str__(self):
        return f"{self.organization} — {self.year}: {self.last_sequence}"

    @classmethod
    def next_number(cls, organization, year):
        """Must be called from inside an atomic block — same
        select_for_update()-needs-a-transaction requirement as
        InvoiceSequence.next_number(), same reasoning."""
        seq, _ = cls.objects.select_for_update().get_or_create(
            organization=organization, year=year, defaults={"last_sequence": 0},
        )
        seq.last_sequence += 1
        seq.save(update_fields=["last_sequence"])
        return seq.last_sequence


class OutgoingLetter(TenantScopedModel):
    """
    A real, officially-numbered outgoing letter. number format
    confirmed directly against Made's own real example:
    "042/SK/AM/VIII/2026" — sequence/SK/{org.invoice_code}/{roman
    month}/{year}. Deliberately reuses Organization.invoice_code
    rather than adding a second, separately-configured shop code —
    Made's own example used the SAME "AM" already used for invoices,
    and a shop only has one real short identifier, not two.

    source records WHY this letter exists — auto-generated from one
    of the two confirmed trigger points, or a standalone entry with
    no origin at all. estimate/contract_import are both nullable,
    SET_NULL: a letter's own number and content stay valid and
    real regardless of what happens to the record that triggered it
    later — same "the letter itself is the real, permanent thing"
    reasoning already applied to Invoice's own frozen snapshots,
    just via a nullable link instead of a copied value (a letter
    doesn't need to freeze a whole snapshot of its origin, only
    remember which one it was).
    """
    SOURCE_CHOICES = [
        ("ESTIMATE_APPROVAL",       "Persetujuan Estimasi"),
        ("CONTRACT_FUNDS_REQUEST",  "Permohonan Dana Kontrak"),
        ("STANDALONE",              "Surat Mandiri"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=50, editable=False, verbose_name="Nomor Surat")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    year            = models.PositiveIntegerField(editable=False, verbose_name="Tahun")

    recipient = models.CharField(max_length=255, verbose_name="Kepada")
    subject   = models.CharField(max_length=255, verbose_name="Perihal")
    source    = models.CharField(max_length=30, choices=SOURCE_CHOICES, default="STANDALONE", verbose_name="Sumber")

    # Nullable — only populated for the two auto-generated paths.
    # SET_NULL, not PROTECT: unlike Invoice<->ServiceRecord (where
    # the financial document's own integrity depends on its origin
    # never vanishing), a letter's real content (recipient, subject,
    # number) is already fully self-contained — this link exists for
    # traceability, not as something the letter's own validity
    # depends on.
    estimate = models.ForeignKey(
        "estimates.Estimate", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="outgoing_letters", verbose_name="Estimasi Terkait",
    )
    contract_import = models.ForeignKey(
        "contracts.ContractImport", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="outgoing_letters", verbose_name="Import Kontrak Terkait",
    )

    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Outgoing Letter"
        verbose_name_plural  = "Outgoing Letters"
        ordering             = ["-created_at"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        # Same "generate once, on creation, never again" discipline
        # as Invoice.save() and Estimate.save() — a letter's own
        # official number must never change after the fact, whatever
        # else about the record might later be corrected.
        if self._state.adding and not self.number:
            self.year = self.year or date.today().year
            self.sequence_number = LetterSequence.next_number(self.organization, self.year)
            roman_month = ROMAN_MONTHS[date.today().month - 1]
            self.number = (
                f"{self.sequence_number:03d}/SK/{self.organization.invoice_code}/"
                f"{roman_month}/{self.year}"
            )
        super().save(*args, **kwargs)


class IncomingLetter(TenantScopedModel):
    """
    A scanned/uploaded incoming document. Deliberately no sequence
    number at all — Made's own confirmed distinction: an incoming
    letter wasn't authored by Arya Motor, so there's no "official
    outgoing number" concept to generate here, only real metadata to
    keep it genuinely searchable (his own explicit words: "jangan
    jadi blind file drop").

    customer/vehicle are both nullable — an incoming letter isn't
    always about a specific customer or vehicle at all (a government
    circular, a vendor's general notice) — but when it is, linking it
    surfaces the letter directly in that customer/vehicle's own
    history timeline, per Made's own explicit ask.
    """
    id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.CharField(max_length=255, verbose_name="Pengirim")
    subject = models.CharField(max_length=255, verbose_name="Perihal / Ringkasan")

    letter_date   = models.DateField(verbose_name="Tanggal Surat")
    received_date = models.DateField(default=date.today, verbose_name="Tanggal Diterima")

    file = models.FileField(upload_to="incoming_letters/%Y/%m/", verbose_name="File (PDF/Gambar)")

    customer = models.ForeignKey(
        "service.Customer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="incoming_letters", verbose_name="Pelanggan Terkait",
    )
    vehicle = models.ForeignKey(
        "service.Vehicle", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="incoming_letters", verbose_name="Kendaraan Terkait",
    )

    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Incoming Letter"
        verbose_name_plural  = "Incoming Letters"
        ordering             = ["-received_date", "-created_at"]

    def __str__(self):
        return f"{self.subject} — {self.sender}"
