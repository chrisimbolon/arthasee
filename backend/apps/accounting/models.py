# =============================================================================
# === backend/apps/accounting/models.py ===
# =============================================================================
"""
Arthasee — Accounting

The multi-tenant ledger core (Roadmap v2.2, Phase 1). Every model
here follows the exact conventions already proven elsewhere in this
codebase — UUID primary keys, TenantScopedModel, a Sequence model +
select_for_update() for gap-free numbering (mirrors
apps.workorders.models.WorkOrderSequence exactly), PROTECT on any FK
whose target must never disappear out from under real history.

JournalEntry.post() is the single real write path for creating a
balanced journal entry — every Sprint 2 domain-event handler and the
future Phase 4 manual-adjustment endpoint both go through this,
never construct JournalEntry/JournalLine directly. This mirrors
WorkOrder.close()'s own shape: one method owns its own
transaction.atomic() block and raises BEFORE writing anything at all
if the entry wouldn't balance, rather than trusting every future
caller to get the arithmetic right individually.

Honest limitation, not a silent gap: the "sum(debits) == sum(credits)"
constraint is enforced at the APPLICATION layer (inside post()'s own
validation, before any row is written) rather than as a database
CHECK constraint — a check spanning multiple JournalLine rows isn't
expressible as a single-row Postgres CHECK constraint without a
trigger. JournalLine's own CheckConstraint below enforces the
narrower, single-row rule (exactly one of debit/credit set) at the DB
level; the cross-row balance rule is post()'s responsibility as the
sole write path. If direct-ORM-bypass ever becomes a real risk (e.g.
a future data-migration script constructing entries by hand), a
Postgres trigger would be the next layer of defense — not needed yet
since post() is genuinely the only way any calling code creates one.
"""
import uuid
from decimal import Decimal

from apps.core.models import TenantScopedModel
from django.db import models, transaction
from django.db.models import Sum


class Account(TenantScopedModel):
    """
    One row per Chart-of-Accounts line, per Organization — see
    management/commands/seed_coa.py for the standard set every shop
    starts with (Roadmap v2.2 COA Blueprint). Shops can add their own
    beyond the standard set later; nothing here restricts that.
    """
    class AccountType(models.TextChoices):
        ASSET     = "ASSET", "Aset"
        LIABILITY = "LIABILITY", "Kewajiban"
        EQUITY    = "EQUITY", "Ekuitas"
        REVENUE   = "REVENUE", "Pendapatan"
        COGS      = "COGS", "Harga Pokok Penjualan"
        EXPENSE   = "EXPENSE", "Beban"

    class NormalBalance(models.TextChoices):
        DEBIT  = "DEBIT", "Debit"
        CREDIT = "CREDIT", "Kredit"

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=10, verbose_name="Kode Akun")
    name = models.CharField(max_length=200, verbose_name="Nama Akun")
    account_type = models.CharField(
        max_length=20, choices=AccountType.choices, verbose_name="Tipe Akun",
    )
    normal_balance = models.CharField(
        max_length=10, choices=NormalBalance.choices, verbose_name="Saldo Normal",
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="Deskripsi")
    is_active  = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Account"
        verbose_name_plural  = "Accounts"
        ordering             = ["code"]
        unique_together      = [("organization", "code")]

    def __str__(self):
        return f"{self.code} — {self.name}"

    def balance(self, *, as_of=None) -> Decimal:
        """
        Computed on the fly from JournalLine, the real source of
        truth — no denormalized running total on this model. Unlike
        Part.current_stock (a deliberate, documented exception to
        that rule elsewhere in this codebase), an Account's balance
        feeds directly into real financial statements (Phase 4) —
        getting a cached figure wrong would misstate them. The extra
        aggregate query is worth it.
        """
        qs = JournalLine.objects.filter(account=self)
        if as_of is not None:
            qs = qs.filter(journal_entry__posting_date__lte=as_of)
        totals = qs.aggregate(debit=Sum("debit_amount"), credit=Sum("credit_amount"))
        debit  = totals["debit"] or Decimal("0")
        credit = totals["credit"] or Decimal("0")
        if self.normal_balance == self.NormalBalance.DEBIT:
            return debit - credit
        return credit - debit

    @classmethod
    def resolve(cls, organization, code):
        """
        The one real place "account code -> real Account row" gets
        resolved, with a clear, actionable error if the Chart of
        Accounts hasn't been seeded. Used by both
        apps.accounting.journal_generator (posting NEW facts) and
        apps.accounting.cancellations (reversing OLD ones) — one
        shared implementation, so a missing-COA failure reads
        identically no matter which path hit it, not two slightly
        different messages that could drift apart.
        """
        try:
            return cls.objects.get(organization=organization, code=code)
        except cls.DoesNotExist as exc:
            raise ValueError(
                f"No Account with code={code!r} found for organization "
                f"{organization.name!r} — has the Chart of Accounts been "
                f"seeded (python manage.py seed_coa)?"
            ) from exc

class AccountingPeriod(TenantScopedModel):
    """
    Schema only, for now — Phase 4, Task 4.3 (Fiscal Period Lock
    Engine) is where an actual posting-time guard against
    is_closed/is_locked periods gets wired into JournalEntry.post().
    The column exists on JournalEntry already (see accounting_period
    below, nullable) so that Phase 4 work is pure logic, not another
    schema migration.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    start_date = models.DateField(verbose_name="Tanggal Mulai")
    end_date   = models.DateField(verbose_name="Tanggal Selesai")
    is_closed  = models.BooleanField(default=False, verbose_name="Ditutup")
    is_locked  = models.BooleanField(default=False, verbose_name="Terkunci")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Accounting Period"
        verbose_name_plural  = "Accounting Periods"
        ordering             = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__gt=models.F("start_date")),
                name="accountingperiod_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.start_date} – {self.end_date} ({self.organization})"

    @property
    def is_open_for_posting(self) -> bool:
        return not (self.is_closed or self.is_locked)


class JournalEntrySequence(TenantScopedModel):
    """
    One row per organization — mirrors
    apps.workorders.models.WorkOrderSequence exactly, same
    select_for_update()-based gap-free numbering, same reasoning.
    Not exposed via any API; internal plumbing behind
    JournalEntry.save()'s own number generation.
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Journal Entry Sequence"
        verbose_name_plural  = "Journal Entry Sequences"
        unique_together      = [("organization",)]

    def __str__(self):
        return f"{self.organization}: {self.last_sequence}"

    @classmethod
    def next_number(cls, organization):
        seq, _ = cls.objects.select_for_update().get_or_create(
            organization=organization, defaults={"last_sequence": 0},
        )
        seq.last_sequence += 1
        seq.save(update_fields=["last_sequence"])
        return seq.last_sequence


class JournalEntry(TenantScopedModel):
    """
    One balanced double-entry posting. Never constructed directly —
    always via JournalEntry.post() (see module docstring above).
    """
    class Source(models.TextChoices):
        DOMAIN_EVENT = "DOMAIN_EVENT", "Event Domain"
        MANUAL       = "MANUAL", "Jurnal Manual"

    class Status(models.TextChoices):
        PENDING   = "PENDING", "Menunggu"
        VALIDATED = "VALIDATED", "Tervalidasi"
        POSTED    = "POSTED", "Terposting"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry_number    = models.CharField(max_length=30, editable=False, verbose_name="Nomor Jurnal")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    posting_date    = models.DateField(verbose_name="Tanggal Posting")
    accounting_period = models.ForeignKey(
        AccountingPeriod, on_delete=models.PROTECT, null=True, blank=True,
        related_name="journal_entries", verbose_name="Periode Akuntansi",
    )
    source     = models.CharField(max_length=20, choices=Source.choices, verbose_name="Sumber")
    event_type = models.CharField(max_length=100, blank=True, default="", verbose_name="Tipe Event")
    reference_event_id = models.UUIDField(null=True, blank=True, verbose_name="ID Event Rujukan")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.POSTED, verbose_name="Status",
    )
    memo = models.CharField(max_length=255, blank=True, verbose_name="Keterangan")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Dibuat Oleh",
        # Null for domain-event-driven entries — nobody "typed" these
        # in. Only ever set for source=MANUAL, the SAK ETAP/EMKM
        # adjusting-journal path (Phase 4, Task 4.4).
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Journal Entry"
        verbose_name_plural  = "Journal Entries"
        ordering             = ["-posting_date", "-sequence_number"]
        unique_together      = [("organization", "entry_number")]

    def __str__(self):
        return f"JRN-{self.entry_number} ({self.source})"

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.entry_number:
            self.sequence_number = JournalEntrySequence.next_number(self.organization)
            self.entry_number = f"{self.sequence_number:06d}"
        super().save(*args, **kwargs)

    @classmethod
    def post(
        cls, *, organization, posting_date, source, lines,
        memo="", event_type="", reference_event_id=None,
        created_by=None, accounting_period=None,
    ):
        """
        The one real entry point for creating a balanced journal
        entry. `lines` is a plain list of dicts:

            [{"account": <Account>, "debit": Decimal("0"), "credit": Decimal("0"), "description": ""}, ...]

        Validates BEFORE writing anything: at least two lines, total
        debit == total credit, non-zero total, and exactly one side
        set per line. A JournalEntry with mismatched or malformed
        lines must never be able to exist even transiently — same
        "guarantee your own atomicity, don't trust the caller"
        discipline as WorkOrder.close()/cancel().
        """
        if len(lines) < 2:
            raise ValueError(
                "A journal entry needs at least two lines to be a real "
                "double-entry posting."
            )

        zero = Decimal("0")
        total_debit  = sum((line.get("debit") or zero) for line in lines)
        total_credit = sum((line.get("credit") or zero) for line in lines)

        if total_debit != total_credit:
            raise ValueError(
                f"Journal entry is not balanced: total debit {total_debit} "
                f"!= total credit {total_credit}."
            )
        if total_debit == zero:
            raise ValueError("Journal entry has zero total value — nothing to post.")

        for line in lines:
            debit  = line.get("debit") or zero
            credit = line.get("credit") or zero
            if (debit > zero) == (credit > zero):
                raise ValueError(
                    f"Line for account {line['account']} must have exactly "
                    f"one of debit/credit set, not both or neither."
                )

        with transaction.atomic():
            # Task 4.3 — Fiscal Period Lock. Auto-resolves the period
            # for posting_date if the caller didn't already pass one
            # (nobody has, historically — accounting_period has sat
            # unused by every event handler since Sprint 1). Chris's
            # own explicit call: NO period found is a hard failure,
            # not a silent pass-through — "every posting must belong
            # to a real period, no exceptions." This is what makes
            # apps.accounting.periods.ensure_current_year_period() a
            # genuine prerequisite for a new organization now, same
            # as seed_chart_of_accounts() already was — see that
            # function's own module docstring.
            if accounting_period is None:
                accounting_period = AccountingPeriod.objects.filter(
                    organization=organization,
                    start_date__lte=posting_date, end_date__gte=posting_date,
                ).first()

            if accounting_period is None:
                raise ValueError(
                    f"Tidak ada periode akuntansi yang mencakup tanggal "
                    f"{posting_date} untuk organisasi '{organization.name}' — "
                    f"buat AccountingPeriod yang mencakup tanggal ini sebelum "
                    f"memposting jurnal."
                )
            if accounting_period.is_closed:
                raise ValueError(
                    f"Periode akuntansi {accounting_period.start_date}–"
                    f"{accounting_period.end_date} sudah ditutup — tidak bisa "
                    f"memposting jurnal apa pun ke periode ini."
                )
            # Locked blocks automatic (DOMAIN_EVENT) postings only —
            # a manual adjusting journal (Task 4.4) can still post
            # through a locked period, Chris's own explicit call.
            # CLOSED, above, blocks everything unconditionally,
            # including manual entries — a genuinely different,
            # stronger state than locked, checked first and never
            # bypassed by source.
            if accounting_period.is_locked and source != cls.Source.MANUAL:
                raise ValueError(
                    f"Periode akuntansi {accounting_period.start_date}–"
                    f"{accounting_period.end_date} sedang terkunci — hanya "
                    f"jurnal manual (adjusting journal) yang bisa diposting "
                    f"ke periode ini."
                )

            entry = cls.objects.create(
                organization=organization,
                posting_date=posting_date,
                accounting_period=accounting_period,
                source=source,
                event_type=event_type,
                reference_event_id=reference_event_id,
                memo=memo,
                created_by=created_by,
                status=cls.Status.POSTED,
            )
            JournalLine.objects.bulk_create([
                JournalLine(
                    organization=organization,
                    journal_entry=entry,
                    account=line["account"],
                    debit_amount=line.get("debit") or zero,
                    credit_amount=line.get("credit") or zero,
                    description=line.get("description", ""),
                )
                for line in lines
            ])
        return entry


class JournalLine(TenantScopedModel):
    """
    One debit or credit line within a JournalEntry. account is
    PROTECT, not CASCADE/SET_NULL — same Principle 2 reasoning as
    Part/PartUsage elsewhere: an Account with real posted history can
    never be deleted out from under that history.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal_entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="lines",
        verbose_name="Entri Jurnal",
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="journal_lines",
        verbose_name="Akun",
    )
    debit_amount  = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), verbose_name="Debit")
    credit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), verbose_name="Kredit")
    description = models.CharField(max_length=255, blank=True, verbose_name="Keterangan")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Journal Line"
        verbose_name_plural  = "Journal Lines"
        ordering             = ["created_at"]
        constraints = [
            # Single-row rule only — see module docstring for why the
            # cross-row "entry balances" rule can't live here too.
            models.CheckConstraint(
                check=(
                    models.Q(debit_amount__gt=0, credit_amount=0)
                    | models.Q(credit_amount__gt=0, debit_amount=0)
                ),
                name="journalline_exactly_one_side",
            ),
        ]

    def __str__(self):
        side = f"Dr {self.debit_amount}" if self.debit_amount else f"Cr {self.credit_amount}"
        return f"{self.account.code} {side}"

    def _resolve_organization(self):
        return self.journal_entry.organization
