# =============================================================================
# === backend/apps/contracts/models.py ===
# =============================================================================
"""
Arthasee — Contracts (institutional / tender clients)

Real background, confirmed with Chris and cross-referenced against a
real HPS (Harga Perkiraan Sementara) document from Polda Kepri, T.A.
2026: many Batam bengkels, Arya Motor included, serve two genuinely
different customer types — regular walk-in customers (everything
built so far) and institutional/tender clients (government bodies,
police, large companies) who award a contract via tender, paid on a
termin (scheduled disbursement) rather than per visit.

Own app, not folded into apps.invoicing or apps.service — same
reasoning as every other domain extraction in this project: this is
a genuinely distinct concept (a multi-vehicle, multi-year contract
with its own document-import lifecycle), not a variant of Invoice.

Design decisions locked in with Chris:
  - A tender client's Excel budget document (HPS/RAB) gets imported,
    not manually re-typed. Made's own words: an "engine" that digests
    the xlsx and turns it into real, usable data on the platform.
  - Imported line items become LIVE data — each vehicle and its
    pre-authorized scope+pricing should be something a real
    WorkOrder can later reference, not just a read-only archive copy
    of the document.
  - Confirmed: Made's Excel template is consistent every time. This
    is what makes a deterministic parser (see parsing.py) a
    reasonable choice at all — a fuzzy/heuristic parser would be the
    wrong tool if the format varied per contract, but it doesn't.
  - Confirmed: contracts get revised/re-uploaded over their life.
    This is why ContractImport exists as its own model at all — the
    same "mutable/speculative -> reviewed -> frozen" promotion
    pattern already used three times elsewhere (PartUsage->Invoice,
    WorkOrder->ServiceRecord, Estimate->WorkOrder), applied here for
    the 4th time. A re-upload NEVER silently overwrites live
    ContractLineItem rows — it produces a diff, a human reviews
    exactly what would change, and only an explicit apply() call
    promotes it.
  - Confirmed: institutional fleet vehicles (e.g. "HYUNDAI TUCSON
    (9-XXXI)" — a fleet code, not a civilian plate) reuse the
    existing service.Vehicle model as-is. Vehicle.plate_number is an
    unconstrained CharField, so a fleet code fits with zero schema
    changes — same "the downstream model needs zero changes" logic
    as every other promotion pattern here.
"""
import calendar
import uuid
from datetime import date
from decimal import Decimal

from apps.core.models import TenantScopedModel
from django.db import models, transaction
from django.utils import timezone


def _add_months(base_date, months):
    """
    Plain stdlib month arithmetic — deliberately not a new dependency
    (python-dateutil isn't already used anywhere in this project, and
    this one calculation doesn't justify introducing it). Clamps the
    day to the target month's real last day, so e.g. 31 Jan + 1 month
    lands on 28/29 Feb, not an invalid date.
    """
    month_index = base_date.month - 1 + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class Contract(TenantScopedModel):
    """
    One awarded tender/contract — e.g. Polda Kepri's annual vehicle
    maintenance procurement. Root-level model: organization and
    customer are both set directly at creation, same as Customer/
    Vehicle — this is not derived through another relation.
    """
    STATUS_CHOICES = [
        ("ACTIVE",    "Aktif"),
        ("EXPIRED",   "Berakhir"),
        ("CANCELLED", "Dibatalkan"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        "service.Customer", on_delete=models.PROTECT, related_name="contracts",
        verbose_name="Klien Institusi",
        # PROTECT — same Principle 2 reasoning as everywhere else. A
        # real, awarded contract must never silently vanish just
        # because someone deletes the customer record.
    )
    title = models.CharField(max_length=255, verbose_name="Judul Pekerjaan")
    fiscal_year = models.PositiveIntegerField(verbose_name="Tahun Anggaran")
    # Deliberately never appears in the HPS/RAB document itself —
    # confirmed with Chris this is entered manually, once known.
    # Made's own notes: 3x/year = disbursed every 4 months, 4x/year =
    # every 3 months.
    termin_count = models.PositiveSmallIntegerField(
        choices=[(3, "3x per tahun (tiap 4 bulan)"), (4, "4x per tahun (tiap 3 bulan)")],
        verbose_name="Jumlah Termin",
    )
    # New field — the anchor point termin due dates get calculated
    # from. Defaults to today's date at creation, but deliberately
    # editable: the real day Arya Motor enters a contract into
    # Arthasee isn't always the contract's real, authorized start —
    # relying on created_at (system entry time) as if it were the
    # same thing would silently produce wrong due dates for any
    # contract entered a few days late.
    start_date = models.DateField(default=date.today, verbose_name="Tanggal Mulai")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE", verbose_name="Status")

    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Contract"
        verbose_name_plural  = "Contracts"
        ordering             = ["-fiscal_year", "-created_at"]

    def __str__(self):
        return f"{self.title} — {self.customer.name} ({self.fiscal_year})"

    def generate_termin_periods(self):
        """
        Confirmed with Chris: all termin slots get created upfront,
        in full, the moment a Contract is created — not added one at
        a time as they happen. Called explicitly from
        ContractListView.post(), not from save() itself, matching
        this project's own established pattern of keeping model
        business logic and its trigger point separately visible
        (WorkOrder doesn't auto-generate its own stages in save()
        either).

        interval_months uses 12 // termin_count — Made's own
        confirmed numbers make this exact, not approximate: 4x/year
        is every 3 months, 3x/year is every 4 months, both clean
        integer divisions of 12.

        amount_expected starts at 0 for every period — deliberately,
        not left null. At the moment a Contract is created it has
        zero ContractVehicles and therefore no real budget to split
        yet (every vehicle/line item comes in exclusively through a
        ContractImport upload, per this model's own docstring) — see
        recalculate_unrealized_termin_amounts() below for where the
        real figure actually gets filled in, once there's a real
        budget to split.
        """
        interval_months = 12 // self.termin_count
        TerminPeriod.objects.bulk_create([
            TerminPeriod(
                organization=self.organization, contract=self,
                sequence=n, jatuh_tempo=_add_months(self.start_date, interval_months * n),
                amount_expected=Decimal("0"),
            )
            for n in range(1, self.termin_count + 1)
        ])

    def recalculate_unrealized_termin_amounts(self):
        """
        Called from ContractImport.apply() every time an import
        successfully applies — the contract's real total budget only
        exists once vehicles/line items actually exist, and can
        legitimately change again later (a contract amendment adding
        vehicles via a revised import). This deliberately keeps
        amount_expected live-recalculable, NOT a permanent snapshot —
        different from Invoice/InvoiceLineItem's own "financial
        values are frozen at creation, never a live read" discipline,
        because this figure represents an evolving planning
        expectation, not an issued financial document.

        The one thing that IS frozen forever: any TerminPeriod
        already realized (amount_received is not None) is explicitly
        excluded from recalculation — a termin that's already been
        paid must never have its own "expected" figure retroactively
        rewritten after the fact, regardless of what the contract's
        scope does later.
        """
        total_budget = sum(
            (cv.allocated_budget for cv in self.contract_vehicles.all()), Decimal("0"),
        )
        unrealized = self.termin_periods.filter(amount_received__isnull=True)
        count = unrealized.count()
        if count == 0:
            return
        each_share = (total_budget / count).quantize(Decimal("0.01"))
        for period in unrealized:
            period.amount_expected = each_share
            period.save(update_fields=["amount_expected"])


class TerminPeriod(TenantScopedModel):
    """
    One disbursement period within an institutional Contract — the
    concrete answer to Made's own real, worked example from the 28
    Jul meeting (the Avanza 849 XXXI-28 termin tracking he showed
    directly). All periods for a Contract are generated together, in
    full, at Contract creation — see Contract.generate_termin_periods().

    jatuh_tempo (due date) is calculated once, at generation time,
    from Contract.start_date — confirmed with Chris: automatic, not
    manually typed per period. amount_expected is genuinely NOT
    frozen the same way — see Contract.recalculate_unrealized_termin_
    amounts() for why it stays live-recalculable for any period not
    yet realized.

    amount_received is deliberately a real, separate field from
    amount_expected, not a boolean — confirmed with Chris: actual
    institutional disbursement can genuinely differ from what was
    expected/invoiced, and that difference is real information worth
    keeping, not collapsing into a single "were we paid, yes/no."
    """
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract        = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="termin_periods", verbose_name="Contract")
    sequence        = models.PositiveSmallIntegerField(verbose_name="Termin Ke-")
    jatuh_tempo     = models.DateField(verbose_name="Jatuh Tempo")
    amount_expected = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), verbose_name="Perkiraan Nilai")
    amount_received = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Nilai Realisasi")
    received_at     = models.DateField(null=True, blank=True, verbose_name="Tanggal Realisasi")
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Termin Period"
        verbose_name_plural  = "Termin Periods"
        ordering             = ["sequence"]
        unique_together      = [("contract", "sequence")]

    def __str__(self):
        return f"Termin {self.sequence} — {self.contract.title}"

    def _resolve_organization(self):
        return self.contract.organization

    @property
    def is_realized(self):
        return self.amount_received is not None

    @property
    def is_overdue(self):
        """Jatuh tempo has passed with nothing received yet — an
        already-realized period is never overdue, regardless of
        whether it was paid before or after its own due date."""
        if self.is_realized:
            return False
        return date.today() > self.jatuh_tempo

    def record_realization(self, amount, received_date=None):
        """
        No caller currently has another field to save in the same
        request (unlike WorkOrder.mark_started()/WorkOrderStage.
        start()), so this saves directly rather than leaving that to
        the caller — the simpler, equally correct choice here.
        """
        self.amount_received = amount
        self.received_at = received_date or date.today()
        self.save(update_fields=["amount_received", "received_at"])


class ContractVehicle(TenantScopedModel):
    """
    Join between a Contract and an existing service.Vehicle —
    deliberately NOT a direct FK on Vehicle itself (no
    Vehicle.contract field). The exact same real police fleet vehicle
    will very plausibly reappear across multiple fiscal years' worth
    of tenders; a direct FK would only ever allow one contract per
    vehicle, ever, which is wrong the moment a contract renews.
    """
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="contract_vehicles")
    vehicle  = models.ForeignKey(
        "service.Vehicle", on_delete=models.PROTECT, related_name="contract_vehicles",
        verbose_name="Kendaraan",
    )
    # As printed on the document (e.g. "Rp 21.600.000" per vehicle in
    # the real HPS reviewed for this project) — stored, not always
    # recomputed. A real mismatch against the sum of this vehicle's
    # own line items is a genuine signal worth surfacing during
    # import review, not something silently overridden.
    allocated_budget = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Anggaran Dialokasikan")

    class Meta:
        verbose_name        = "Contract Vehicle"
        verbose_name_plural  = "Contract Vehicles"
        unique_together      = [("contract", "vehicle")]

    def __str__(self):
        return f"{self.vehicle.plate_number} — {self.contract.title}"

    def _resolve_organization(self):
        return self.contract.organization


class ContractLineItem(TenantScopedModel):
    """
    One pre-authorized scope-of-work + price for one vehicle under
    one contract — the actual "menu" a future WorkOrder for this
    vehicle should be able to draw from.

    source_row_no, not description text, is the real matching key
    used to reconcile a re-imported revision against this line. This
    is a deliberate choice, not an oversight: the one real document
    reviewed for this project already uses different wording for
    conceptually-the-same job across different vehicles (Group I:
    "Service transmisi matic (ATF + Filter + Gasket)" vs Group II:
    "Servis transmisi (ATF/manual overhaul ringan)") — so description
    text can't be trusted to stay stable across a revision either,
    but a line's printed position within its own vehicle's list can.
    """
    STATUS_CHOICES = [
        ("ACTIVE",     "Aktif"),
        ("SUPERSEDED", "Digantikan"),
    ]

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract_vehicle = models.ForeignKey(ContractVehicle, on_delete=models.CASCADE, related_name="line_items")
    source_row_no    = models.PositiveIntegerField(verbose_name="Nomor Baris Sumber")

    description = models.CharField(max_length=255, verbose_name="Item Pekerjaan")
    volume      = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Volume")
    unit        = models.CharField(max_length=50, verbose_name="Satuan")
    unit_price  = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Harga Satuan")
    subtotal    = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Jumlah")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE", verbose_name="Status")
    # Never hard-deleted, same Principle 2 reasoning as everywhere
    # else in this codebase — a real WorkOrder created earlier may
    # already reference this exact row, and losing it silently would
    # break that reference's own history.
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes",
    )
    source_import = models.ForeignKey(
        "ContractImport", on_delete=models.PROTECT, related_name="created_line_items",
        null=True, blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Contract Line Item"
        verbose_name_plural  = "Contract Line Items"
        ordering             = ["contract_vehicle", "source_row_no"]
        constraints = [
            # A real, DB-level guarantee, not just an application-level
            # assumption — matches this project's general preference
            # (see Invoice<->ServiceRecord's OneToOneField: "the
            # database itself refuses to let a visit be invoiced
            # twice"). Only ever one ACTIVE row per position; historical
            # SUPERSEDED rows at the same position are fine and expected.
            models.UniqueConstraint(
                fields=["contract_vehicle", "source_row_no"],
                condition=models.Q(status="ACTIVE"),
                name="unique_active_line_item_per_position",
            ),
        ]

    def __str__(self):
        return f"{self.description} — {self.contract_vehicle.vehicle.plate_number}"

    def _resolve_organization(self):
        return self.contract_vehicle.contract.organization


class ContractImport(TenantScopedModel):
    """
    The speculative side of the promotion pattern, used here a 4th
    time: uploading an Excel file never touches live
    ContractLineItem rows directly. It parses into `parsed_diff` and
    sits in PENDING_REVIEW — a human reviews exactly what would
    change, and only an explicit apply() call (below) promotes it
    into real, live rows. This mirrors Estimate -> WorkOrder and
    WorkOrder -> ServiceRecord exactly: nothing about
    ContractLineItem's own shape had to change to support this: the
    safety lives entirely in this one extra stage.

    Also deliberately how a Contract's very FIRST import works too —
    there's no separate "create contract from scratch" code path.
    A brand-new Contract just starts with zero ContractVehicles, so
    its first upload's diff happens to be all "added" — same
    mechanism, same review screen, one less code path to maintain.
    """
    STATUS_CHOICES = [
        ("PENDING_REVIEW", "Menunggu Peninjauan"),
        ("APPLIED",        "Diterapkan"),
        ("REJECTED",       "Ditolak"),
    ]

    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="imports")
    original_file = models.FileField(upload_to="contract_imports/%Y/%m/", verbose_name="File Asli")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING_REVIEW", verbose_name="Status")

    # {"added_vehicles": [...], "added_items": [...],
    #  "changed_items": [...], "removed_items": [...],
    #  "unchanged_count": int} — see apps.contracts.parsing's own
    # diff_against_contract() for the exact shape. Stored as JSON so
    # the review screen can render it without re-parsing the file.
    parsed_diff = models.JSONField(default=dict, blank=True, verbose_name="Hasil Perbandingan")

    # Cheap, real validation that costs nothing extra to check: the
    # source document itself always prints its own grand total
    # ("TOTAL KESELURUHAN"). Comparing the parser's own summed total
    # against that printed number catches a genuine misread before a
    # human is ever asked to approve anything.
    document_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Total Tertulis di Dokumen")
    computed_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Total Hasil Parsing")

    parse_error = models.TextField(blank=True, verbose_name="Error Parsing")

    uploaded_by = models.ForeignKey("authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    applied_by  = models.ForeignKey("authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    applied_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = "Contract Import"
        verbose_name_plural  = "Contract Imports"
        ordering             = ["-uploaded_at"]

    def __str__(self):
        return f"Import {self.uploaded_at:%Y-%m-%d} — {self.contract.title}"

    def _resolve_organization(self):
        return self.contract.organization

    @property
    def totals_match(self):
        if self.document_total is None or self.computed_total is None:
            return None
        return abs(self.document_total - self.computed_total) < Decimal("1.00")

    def apply(self, confirmed_diff, applied_by=None):
        """
        Promotes a reviewed diff into real ContractVehicle /
        ContractLineItem rows. `confirmed_diff` is deliberately taken
        as an explicit argument, NOT read back from self.parsed_diff —
        a human reviewing "added_vehicles" may have filled in fields
        the source document never provided at all (Vehicle.
        manufacture_year, most notably: a required, non-nullable
        field on the existing Vehicle model that appears nowhere in
        the real HPS reviewed for this project). Silently re-reading
        the raw machine parse here would discard exactly the
        corrections review exists to make.

        Runs in its own transaction regardless of what calls it, same
        reasoning as WorkOrder.close() — this is business logic
        complex enough (multiple creates, multiple status changes)
        that it should guarantee its own atomicity, not rely on the
        caller to have wrapped one. Note there's no XSequence here
        (Contract isn't a numbered document the way Invoice/WorkOrder/
        Estimate are) — this atomic() block is protecting general
        partial-failure integrity, not working around the
        select_for_update()-needs-a-transaction gotcha documented
        elsewhere in this project.
        """
        # cross-app reasoning as WorkOrder.close()'s own local import
        # of ServiceRecord — apps.contracts depends on apps.service,
        # not the other way around, and this keeps that direction
        # obvious without a module-level circular-import risk.
        from apps.letters.models import OutgoingLetter
        from apps.service.models import Vehicle  # local import, same

        # Same local-import reasoning — apps.contracts depends on
        # apps.letters, not the other way around.

        if self.status != "PENDING_REVIEW":
            raise ValueError("Import ini sudah diproses sebelumnya.")

        with transaction.atomic():
            for entry in confirmed_diff.get("added_vehicles", []):
                existing_vehicle_id = entry.get("existing_vehicle_id")
                if existing_vehicle_id:
                    # The real scenario ContractVehicle was built as
                    # its own join table for: this exact fleet
                    # vehicle already exists in the org — from a
                    # prior fiscal year's contract, most plausibly —
                    # just not yet linked to THIS contract. Reuse it
                    # rather than attempting Vehicle.objects.create()
                    # again, which would violate the (organization,
                    # plate_number) unique constraint outright, not
                    # "fail gracefully" — this shipped to production
                    # once as exactly that crash before this check
                    # existed. Deliberately does not touch
                    # manufacture_year/vehicle_type from the entry —
                    # the existing Vehicle's own fields are the real
                    # ones; a reviewer's guess for a brand-new vehicle
                    # (the only case those fields are even collected
                    # for) has no business overwriting an
                    # already-real record.
                    vehicle = Vehicle.objects.get(
                        organization=self.organization, id=existing_vehicle_id,
                    )
                else:
                    vehicle = Vehicle.objects.create(
                        organization=self.organization,
                        customer=self.contract.customer,
                        plate_number=entry["fleet_code"],
                        manufacture_year=entry["manufacture_year"],
                        vehicle_type=entry.get("vehicle_type", "Mobil"),
                        model=entry.get("vehicle_model") or entry["fleet_code"],
                    )
                contract_vehicle = ContractVehicle.objects.create(
                    organization=self.organization, contract=self.contract,
                    vehicle=vehicle, allocated_budget=entry["allocated_budget"],
                )
                ContractLineItem.objects.bulk_create([
                    # bulk_create — same reasoning as every other
                    # promotion boundary in this project: no per-
                    # instance side effects to worry about here, but
                    # consistent with the established convention for
                    # "copying a batch of line items across a
                    # promotion boundary."
                    ContractLineItem(
                        organization=self.organization, contract_vehicle=contract_vehicle,
                        source_row_no=li["row_no"], description=li["description"],
                        volume=li["volume"], unit=li["unit"],
                        unit_price=li["unit_price"], subtotal=li["subtotal"],
                        source_import=self,
                    )
                    for li in entry["line_items"]
                ])

            for entry in confirmed_diff.get("added_items", []):
                contract_vehicle = ContractVehicle.objects.get(
                    contract=self.contract, vehicle__plate_number=entry["fleet_code"],
                )
                ContractLineItem.objects.create(
                    organization=self.organization, contract_vehicle=contract_vehicle,
                    source_row_no=entry["row_no"], description=entry["description"],
                    volume=entry["volume"], unit=entry["unit"],
                    unit_price=entry["unit_price"], subtotal=entry["subtotal"],
                    source_import=self,
                )

            for entry in confirmed_diff.get("changed_items", []):
                contract_vehicle = ContractVehicle.objects.get(
                    contract=self.contract, vehicle__plate_number=entry["fleet_code"],
                )
                old_item = ContractLineItem.objects.get(
                    contract_vehicle=contract_vehicle, source_row_no=entry["row_no"], status="ACTIVE",
                )
                # Supersede the OLD row first, then create the new
                # one — deliberately in this order, not the reverse.
                # Creating the new ACTIVE row before retiring the old
                # one would momentarily put two ACTIVE rows at the
                # same (contract_vehicle, source_row_no) position,
                # which the UniqueConstraint above would reject
                # outright. Reordering avoids ever hitting that state
                # at all, rather than working around it.
                old_item.status = "SUPERSEDED"
                old_item.save(update_fields=["status"])
                new_item = ContractLineItem.objects.create(
                    organization=self.organization, contract_vehicle=contract_vehicle,
                    source_row_no=entry["row_no"], description=entry["new"]["description"],
                    volume=entry["new"]["volume"], unit=entry["new"]["unit"],
                    unit_price=entry["new"]["unit_price"], subtotal=entry["new"]["subtotal"],
                    source_import=self,
                )
                old_item.superseded_by = new_item
                old_item.save(update_fields=["superseded_by"])

            for entry in confirmed_diff.get("removed_items", []):
                contract_vehicle = ContractVehicle.objects.get(
                    contract=self.contract, vehicle__plate_number=entry["fleet_code"],
                )
                ContractLineItem.objects.filter(
                    contract_vehicle=contract_vehicle, source_row_no=entry["row_no"], status="ACTIVE",
                ).update(status="SUPERSEDED")

            self.status = "APPLIED"
            self.applied_by = applied_by
            self.applied_at = timezone.now()
            self.save(update_fields=["status", "applied_by", "applied_at"])

            # The contract's real total budget only exists once this
            # apply() has actually run — see Contract.recalculate_
            # unrealized_termin_amounts()'s own docstring for why
            # this stays live-recalculable rather than a one-time
            # snapshot, and why an already-realized period is
            # excluded from it.
            self.contract.recalculate_unrealized_termin_amounts()

            # D1 (Surat Keluar), Chris's own confirmed trigger, 6 Aug
            # — specifically, phone-confirmed: "plan to request or
            # withdraw funds from Arya Motor to institutional." NOT
            # Contract creation, NOT tied to an individual TerminPeriod
            # — the moment a contract's scope/budget is confirmed via
            # a successfully-applied import. Same transaction as
            # everything above. Silently skipped if the org has no
            # invoice_code configured — same reasoning as the
            # Estimate.approve() hook, nothing about this import's own
            # correctness depends on the letter existing.
            if self.organization.invoice_code:
                OutgoingLetter.objects.create(
                    organization=self.organization, source="CONTRACT_FUNDS_REQUEST",
                    contract_import=self,
                    recipient=self.contract.customer.name,
                    subject=f"Permohonan Pencairan Dana — {self.contract.title}",
                    created_by=applied_by,
                )

    def reject(self):
        if self.status != "PENDING_REVIEW":
            raise ValueError("Import ini sudah diproses sebelumnya.")
        self.status = "REJECTED"
        self.save(update_fields=["status"])
