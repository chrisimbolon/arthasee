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

3 Sep 2026 — Opening Balance onboarding, Sansan's own canonical
onboarding proposal, meticulously reviewed and revised before any
code was written (two real corrections made during that review, not
just implemented as originally pitched):
  1. Source.OPENING_BALANCE needs NO exclusion in Account.balance() —
     unlike PERIOD_CLOSING, every opening-balance line posts to a
     real Asset/Liability/Equity account, never Revenue/COGS/Expense,
     so it structurally cannot contaminate a P&L date-range query the
     way a closing entry can. Added purely for honest Jurnal-page
     labeling, same reason ASSET_ACQUISITION exists as its own value
     rather than reusing MANUAL.
  2. A legacy Fixed Asset entered at onboarding is NOT given its real
     original cost/acquisition_date/useful_life — DepreciationRun.
     execute()'s own entries_so_far logic would then depreciate it
     from zero, as if bought today, silently ignoring however much
     real wear it already has. Instead, OpeningBalanceAssetLine asks
     for current_book_value and remaining_useful_life_months, mapped
     onto Asset.cost/acquisition_date=session.start_date/
     useful_life_months — zero schema changes, and the existing
     no-proration rule does the right thing for free (the opening
     month itself gets no depreciation; straight-line depreciation of
     the REMAINING value begins cleanly the month after).
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal

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

    def balance(self, *, since=None, as_of=None, exclude_closing_entries=False) -> Decimal:
        """
        Computed on the fly from JournalLine, the real source of
        truth — no denormalized running total on this model. Unlike
        Part.current_stock (a deliberate, documented exception to
        that rule elsewhere in this codebase), an Account's balance
        feeds directly into real financial statements (Task 4.1) —
        getting a cached figure wrong would misstate them. The extra
        aggregate query is worth it.

        `since`, added for Task 4.1's P&L/Balance-Sheet reporting —
        without it, this is cumulative since the account's own
        inception (as_of alone), correct for Trial Balance and
        Balance Sheet. A Profit & Loss statement needs a genuine date
        RANGE ("revenue THIS MONTH," not "revenue ever") — passing
        since=X restricts to postings on or after that date. Fully
        backward compatible: every existing caller across three
        sprints only ever passes as_of=, so since=None (the default)
        preserves today's exact behavior unchanged.

        `exclude_closing_entries`, added 28 Aug 2026 — real bug
        found live: a period's own closing entry is dated INSIDE
        that same period's date range (deliberately, so
        JournalEntry.post() resolves it into the right period). A
        plain date-range balance() call for that range — exactly
        what _period_totals() does — would sum the closing entry's
        own reversing debits/credits together with the real original
        activity, netting Revenue/COGS/Expense back toward zero.
        Default False: Trial Balance and Balance Sheet's own
        cumulative account balances correctly, deliberately DO want
        to see the real, current, already-closed state (that IS what
        closing the books means) — only a period-scoped report
        asking "what really happened in this window" should exclude
        the closing mechanism's own bookkeeping from the answer.

        3 Sep 2026 — deliberately NOT extended to also exclude
        Source.OPENING_BALANCE. Considered during the Opening Balance
        design review and rejected: every opening-balance line posts
        to Asset/Liability/Equity accounts only, never Revenue/COGS/
        Expense — the same double-counting risk PERIOD_CLOSING's own
        reversing entry creates cannot occur here, since
        _period_totals() only ever queries REVENUE/COGS/EXPENSE
        account types in the first place. Adding an unused exclusion
        parameter here would be dead code standing in for a risk that
        can't happen — see OpeningBalanceSession's own module note
        above for the fuller reasoning.
        """
        qs = JournalLine.objects.filter(account=self)
        if since is not None:
            qs = qs.filter(journal_entry__posting_date__gte=since)
        if as_of is not None:
            qs = qs.filter(journal_entry__posting_date__lte=as_of)
        if exclude_closing_entries:
            qs = qs.exclude(journal_entry__source=JournalEntry.Source.PERIOD_CLOSING)
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
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    year       = models.PositiveIntegerField(verbose_name="Tahun")
    month      = models.PositiveSmallIntegerField(verbose_name="Bulan")  # 1-12
    start_date = models.DateField(verbose_name="Tanggal Mulai")
    end_date   = models.DateField(verbose_name="Tanggal Selesai")
    is_closed  = models.BooleanField(default=False, verbose_name="Ditutup")
    is_locked  = models.BooleanField(default=False, verbose_name="Terkunci")
    # 28 Aug 2026 — real month-end closing. closed_at is deliberately
    # SEPARATE from is_closed: is_closed flips back to False on a
    # reopen, but closed_at is set ONCE and never cleared — the real,
    # permanent marker close() checks to enforce Chris's own confirmed
    # hard guard ("block re-closing outright, even after a reopen").
    # is_closed alone can't do this job, since a reopen would silently
    # defeat it.
    closed_at   = models.DateTimeField(null=True, blank=True, verbose_name="Waktu Ditutup")
    closed_by   = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Ditutup Oleh",
    )
    reopened_at = models.DateTimeField(null=True, blank=True, verbose_name="Waktu Dibuka Kembali")
    reopened_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Dibuka Kembali Oleh",
    )    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Accounting Period"
        verbose_name_plural  = "Accounting Periods"
        ordering             = ["-year", "-month"]
        unique_together      = [("organization", "year", "month")]
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__gt=models.F("start_date")),
                name="accountingperiod_end_after_start",
            ),
            models.CheckConstraint(
                check=models.Q(month__gte=1, month__lte=12),
                name="accountingperiod_month_valid_range",
            ),
        ]

    def __str__(self):
        return f"{self.start_date} – {self.end_date} ({self.organization})"

    @property
    def is_open_for_posting(self) -> bool:
        return not (self.is_closed or self.is_locked)

    @classmethod
    def assert_open_for_posting(cls, organization, posting_date):
        """
        Raises ValueError if `posting_date` falls outside every known
        period, OR the period covering it is closed/locked. Callers
        should catch ValueError and return it as a real 400 response,
        same "raise a plain ValueError, let the view translate it"
        discipline already used by every other real write-path guard in
        this codebase (PurchaseOrder.cancel(), WorkOrder.close(), etc.).

        Deliberately the SAME is_open_for_posting check JournalEntry.post()
        itself already uses — a period locked (not closed) still blocks
        real operational actions here, same as it already blocks
        DOMAIN_EVENT-sourced postings there; only a MANUAL adjusting
        journal is allowed through a merely-locked period, and none of
        these operational write paths are ever that.
        """
        period = cls.objects.filter(
            organization=organization,
            start_date__lte=posting_date, end_date__gte=posting_date,
        ).first()
        if period is None:
            raise ValueError(
                f"Tidak ada periode akuntansi yang mencakup tanggal {posting_date} "
                f"untuk organisasi '{organization.name}'."
            )
        if not period.is_open_for_posting:
            state = "ditutup" if period.is_closed else "terkunci"
            raise ValueError(
                f"Periode akuntansi {period.start_date}–{period.end_date} sedang "
                f"{state} — tidak bisa melakukan transaksi baru untuk tanggal ini."
            )
        return period    

    def close(self, *, closed_by=None):
        """
        Real month-end close, Made's own confirmed requirement (25 Aug
        meeting, via his tax & accounting consultant) — rolls this
        period's own Revenue/COGS/Expense activity into Retained
        Earnings (3101) via one real, balanced JournalEntry, then marks
        the period closed.

        Reuses reports._period_totals() directly — the EXACT SAME
        numbers Made already saw on the P&L report for this period get
        posted here, not a second, independently-derived calculation
        that could quietly drift from what he reviewed before clicking
        close.

        Hard guard, Chris's own explicit sign-off, 28 Aug 2026: blocked
        outright if this period has EVER been closed before, even after
        a reopen. Checks closed_at, not is_closed — is_closed flips back
        to False on reopen, but closed_at is a permanent marker (see its
        own field comment). Re-closing risks double-counting the FIRST
        closing entry's own lines, since profit_and_loss() reads by real
        date range, not by resetting account balances to zero — a second
        close on the same period would debit/credit accounts that
        already correctly reflect the first closing entry sitting inside
        that same range. Full close -> correct -> re-close support is a
        real, separate design problem, deliberately deferred rather than
        solved partially here.

        Only Revenue/COGS/Expense accounts with a genuinely NONZERO
        period balance get a line — same zero-filtering discipline
        posting_engine.py's own _lines() already uses. A period with
        real activity in only some of these three types still produces a
        correct, balanced entry; a period with literally zero activity
        across all three closes with NO journal entry at all, matching
        the existing precedent set by WorkOrderCompleted's own "$0 ->
        post nothing, the action still succeeds" behavior.

        Posted with posting_date=self.end_date — always the LAST day of
        this period's own real range, so JournalEntry.post()'s own
        period-resolution always finds this exact period, and the
        closing entry itself is correctly still open for posting (is_closed
        is only set True AFTER the entry posts successfully, not before).

        29 Aug 2026 — real pipeline restructuring, Chris's own
        confirmed ordering: the ENTIRE close() operation — the
        depreciation run, the P&L calculation, the Retained Earnings
        posting, the lock flag — now runs inside ONE
        transaction.atomic() block, not just its own tail end as
        before. Real reason: DepreciationRun's own
        unique_together(organization, accounting_period) guard means
        a second call for the same period is a hard, permanent
        block — if depreciation posted successfully but something
        LATER in this method then failed, a retry would immediately
        hit "already run for this period" while the period itself
        never actually closed, a genuine lock-out trap. Wrapping the
        whole method means a failure ANYWHERE rolls back EVERYTHING
        cleanly, including the depreciation run itself, so a retry
        always starts clean.

        Depreciation MUST run before the P&L totals below are
        computed — otherwise this month's own real depreciation
        expense (6004) would never reach the closing entry at all,
        silently understating expenses for a month that genuinely
        had real depreciation. DepreciationRun.execute()'s own
        posting (source=DEPRECIATION) is picked up correctly by
        _period_totals() below — it's real, new expense activity for
        this month, not a reversal of anything, so it's deliberately
        NOT excluded the way PERIOD_CLOSING's own lines are.
        """
        from apps.accounting.reports import _period_totals
        from django.utils import timezone

        if self.closed_at is not None:
            raise ValueError(
                "Periode ini sudah pernah ditutup sebelumnya — tidak bisa ditutup "
                "ulang, bahkan setelah dibuka kembali. Diperlukan penanganan manual "
                "untuk koreksi lebih lanjut."
            )

        # 4 Sep 2026 — real, hard chronological-order guard, found
        # necessary via a careful design-review trace, not a live
        # incident. Closing periods out of order silently broke TWO
        # separate things that both quietly assumed strict
        # chronological closing:
        #   - balance_sheet()'s own current_year_earnings — an
        #     earlier, still-open period's real income would be
        #     DISCARDED ENTIRELY once a later period closed and its
        #     own "is the period covering as_of closed" branch fired,
        #     not just miscounted (see reports.py's own
        #     _unclosed_earnings_start() docstring for the full
        #     trace).
        #   - DepreciationRun.execute()'s own entries_so_far logic —
        #     an asset would silently post only ONE month of
        #     depreciation on an out-of-order close, not however many
        #     months should genuinely have accrued since its last
        #     real entry.
        # Rather than patch each downstream symptom separately, this
        # blocks the real root cause at its source: a period can
        # never close while an earlier period for the same
        # organization is still open. Matches how real bookkeeping
        # already works — January closes before February, never the
        # reverse. A period that was closed and later reopened (see
        # reopen() below) counts as open again here too — its own
        # closed_at being set in the past does not exempt it; only
        # is_closed, the real current state, matters for this check.
        earlier_open_period = AccountingPeriod.objects.filter(
            organization=self.organization, start_date__lt=self.start_date, is_closed=False,
        ).order_by("start_date").first()
        if earlier_open_period is not None:
            raise ValueError(
                f"Periode {earlier_open_period.start_date}–{earlier_open_period.end_date} "
                f"masih belum ditutup — tutup periode-periode sebelumnya secara "
                f"berurutan terlebih dahulu."
            )

        with transaction.atomic():
            DepreciationRun.execute(organization=self.organization, accounting_period=self, run_by=closed_by)

            revenue_rows, total_revenue = _period_totals(
                self.organization, Account.AccountType.REVENUE, since=self.start_date, as_of=self.end_date,
            )
            cogs_rows, total_cogs = _period_totals(
                self.organization, Account.AccountType.COGS, since=self.start_date, as_of=self.end_date,
            )
            expense_rows, total_expenses = _period_totals(
                self.organization, Account.AccountType.EXPENSE, since=self.start_date, as_of=self.end_date,
            )
            net_income = total_revenue - total_cogs - total_expenses

            lines = []
            for row in revenue_rows:
                if row["amount"] != Decimal("0"):
                    lines.append({"account": Account.resolve(self.organization, row["code"]), "debit": row["amount"]})
            for row in cogs_rows + expense_rows:
                if row["amount"] != Decimal("0"):
                    lines.append({"account": Account.resolve(self.organization, row["code"]), "credit": row["amount"]})

            if net_income > Decimal("0"):
                lines.append({"account": Account.resolve(self.organization, "3101"), "credit": net_income})
            elif net_income < Decimal("0"):
                lines.append({"account": Account.resolve(self.organization, "3101"), "debit": -net_income})
            # net_income == 0 with real, offsetting revenue/cogs/expense activity:
            # lines still balance on their own, no 3101 line needed at all.

            closing_entry = None
            if lines:
                closing_entry = JournalEntry.post(
                    organization=self.organization,
                    posting_date=self.end_date,
                    source=JournalEntry.Source.PERIOD_CLOSING,
                    memo=f"Penutupan periode {self.start_date}–{self.end_date}",
                    created_by=closed_by,
                    lines=lines,
                )
            self.is_closed = True
            self.closed_at = timezone.now()
            self.closed_by = closed_by
            self.save(update_fields=["is_closed", "closed_at", "closed_by"])

        return closing_entry, net_income


    def reopen(self, *, reopened_by=None):
        """
        Real, deliberately narrow action — flips is_closed back to False
        so genuine corrections can be posted, matching Made's own
        confirmed requirement ("heavily guarded, owner-only" — the
        owner-only check itself lives in the view, same "authorization
        belongs in the view, the write-path rule belongs in the model"
        split ManualJournalListCreateView's own owner check already
        uses).

        closed_at is deliberately NEVER cleared here — see close()'s own
        docstring for why that's the real, permanent guard against
        re-closing this exact period.
        """
        from django.utils import timezone

        if not self.is_closed:
            raise ValueError("Periode ini sedang tidak dalam status tertutup.")

        self.is_closed = False
        self.reopened_at = timezone.now()
        self.reopened_by = reopened_by
        self.save(update_fields=["is_closed", "reopened_at", "reopened_by"])

class JournalEntrySequence(TenantScopedModel):
    """One row per organization — mirrors WorkOrderSequence exactly."""
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
        DOMAIN_EVENT   = "DOMAIN_EVENT", "Event Domain"
        MANUAL         = "MANUAL", "Jurnal Manual"
        # 28 Aug 2026 — real bug found live: a closing entry dated
        # inside the very period it closes was originally posted as
        # MANUAL, indistinguishable from a real adjusting journal.
        # That meant re-querying that period's own P&L afterward
        # silently zeroed out — the closing entry's own reversing
        # debits to Revenue got summed together with the real
        # original revenue in the SAME date-range query, netting to
        # ~0. This distinct source lets reports.py's own
        # _period_totals() tell the difference and exclude it, so a
        # closed month's history stays intact and re-queryable.
        PERIOD_CLOSING = "PERIOD_CLOSING", "Penutupan Periode"
        # 29 Aug 2026 — Fixed Asset & Depreciation. Neither of these
        # two goes through the async event bus at all — unlike
        # QuickPurchase/OperatingExpense/GoodsReceived (which exist
        # to translate an OTHER domain's real business fact into GL
        # terms, a genuine cross-app decoupling need), Asset lives
        # HERE, in apps.accounting itself — there's no other domain
        # to decouple from, so both post directly and synchronously,
        # same precedent PERIOD_CLOSING above already set.
        #
        # ASSET_ACQUISITION is a normal, LOCK-RESPECTING transaction
        # — buying an asset is ordinary operational activity, same as
        # QuickPurchase/OperatingExpense, neither of which bypasses a
        # locked period either.
        ASSET_ACQUISITION = "ASSET_ACQUISITION", "Perolehan Aset"
        # DEPRECIATION, by contrast, DOES need the same lock-bypass
        # PERIOD_CLOSING already has — it runs INSIDE
        # AccountingPeriod.close()'s own atomic flow (Chris's own
        # confirmed pipeline ordering: depreciation must post BEFORE
        # the P&L totals are computed, or this month's own real
        # depreciation expense would never reach the closing entry),
        # so it must never be blocked by the very lock that Made's
        # real workflow (lock for review, then close) puts in place
        # immediately beforehand.
        DEPRECIATION = "DEPRECIATION", "Penyusutan Aset"
        # 3 Sep 2026 — Opening Balance onboarding. A normal,
        # LOCK-RESPECTING transaction, same treatment as
        # ASSET_ACQUISITION and for the same reason — it posts once,
        # into a period freshly created moments earlier by the
        # onboarding backfill, so it will never realistically hit an
        # already-locked period; there's no real scenario requiring
        # a bypass privilege it structurally never needs. Added
        # purely for honest Jurnal-page labeling and to keep the
        # opening entry unambiguously distinguishable from a real
        # MANUAL adjusting journal — see Account.balance()'s own note
        # above for why this does NOT also need a P&L-range exclusion
        # the way PERIOD_CLOSING does.
        OPENING_BALANCE = "OPENING_BALANCE", "Saldo Awal"

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
            # PERIOD_CLOSING and DEPRECIATION are allowed through the
            # SAME exception — 28-29 Aug 2026 — Made's own real
            # workflow is lock a period first (for review), THEN
            # close it, so neither the closing entry itself nor the
            # depreciation run that must complete before it (see
            # AccountingPeriod.close()'s own docstring) can ever be
            # blocked by the very lock that precedes them.
            # ASSET_ACQUISITION and OPENING_BALANCE deliberately do
            # NOT join this exception — buying an asset, or posting
            # the opening balance itself, is ordinary operational
            # activity, genuinely blocked by a lock same as any other
            # normal transaction. CLOSED, above, still blocks
            # everything unconditionally, including all of these —
            # a genuinely different, stronger state than locked,
            # checked first and never bypassed by source.
            if accounting_period.is_locked and source not in (
                cls.Source.MANUAL, cls.Source.PERIOD_CLOSING, cls.Source.DEPRECIATION,
            ):
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


class AssetSequence(TenantScopedModel):
    """Mirrors every other Sequence model in this codebase exactly."""
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    last_sequence = models.PositiveIntegerField(default=0, verbose_name="Nomor Urut Terakhir")

    class Meta:
        verbose_name        = "Asset Sequence"
        verbose_name_plural  = "Asset Sequences"
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


class Asset(TenantScopedModel):
    """
    A real fixed asset — a compressor, tools, equipment the shop
    owns and uses over multiple years, not consumed in one
    transaction the way Part inventory is. Made's own confirmed real
    request, 27 Aug meeting notes: "otomasi depresiasi... bahkan
    kunci/peralatan kecil izin dihitung penyusutannya."

    Straight-line depreciation only, v1 — the simplest, most
    standard real method, matching this whole system's own
    established "lean over precise" philosophy (same spirit as
    Part.cost_price's own plain "Last Cost" instead of a running
    weighted average). `method` is still a real field, not a
    hardcoded assumption — room to add a second method later without
    a schema change, same shape as Payment.METHOD_CHOICES.

    Salvage value is deliberately NOT a field here — Chris's own
    confirmed call: Made doesn't estimate resale values for shop
    tools, and asking for one on every asset would slow down exactly
    the kind of fast, low-ceremony entry this system optimizes for
    elsewhere (QuickPurchase, OperatingExpense). Always 0 in v1 —
    monthly_depreciation is a straight (cost / useful_life_months)
    division, no subtraction term.

    No proration in the month of acquisition — Chris's own confirmed
    call: depreciation starts the CALENDAR MONTH AFTER acquisition, a
    full month's worth every month thereafter, regardless of whether
    the asset was bought on the 1st or the 28th. See
    DepreciationRun.execute() below for exactly where this is
    enforced.

    Real, honest limitation, not a silent gap: disposal (an asset
    sold or scrapped before its useful life ends) is explicitly OUT
    OF SCOPE for v1 — real disposal accounting (writing off remaining
    book value, a possible gain/loss) is genuinely more complex,
    closer to PurchaseReturn's own multi-case scoping problem than a
    simple monthly posting. Tracked as a real, named open decision,
    not silently ignored. is_active exists so a future disposal
    feature has a real place to land without a schema change — for
    now it only ever flips False once an asset reaches full
    depreciation (see DepreciationRun.execute()).

    3 Sep 2026 — record() gained post_acquisition_entry, for the
    Opening Balance onboarding path. See that parameter's own
    docstring below for the full reasoning; every existing call site
    is unaffected, since it defaults True and preserves today's exact
    behavior unchanged.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number          = models.CharField(max_length=30, editable=False, verbose_name="Nomor Aset")
    sequence_number = models.PositiveIntegerField(editable=False, verbose_name="Nomor Urut")
    name = models.CharField(max_length=200, verbose_name="Nama Aset")
    acquisition_date = models.DateField(verbose_name="Tanggal Perolehan")
    cost = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga Perolehan")
    useful_life_months = models.PositiveIntegerField(verbose_name="Umur Manfaat (Bulan)")
    method = models.CharField(
        max_length=20, choices=[("straight_line", "Garis Lurus")],
        default="straight_line", verbose_name="Metode Penyusutan",
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Asset"
        verbose_name_plural  = "Assets"
        ordering             = ["-acquisition_date"]
        unique_together      = [("organization", "number")]

    def __str__(self):
        return f"{self.number} — {self.name}"

    @property
    def monthly_depreciation(self):
        # Straight-line, salvage value always 0 in v1. quantize() to
        # real currency precision — the ROUND_HALF_UP result is what
        # every non-final month actually posts; the FINAL month
        # never uses this value at all (see DepreciationRun.execute()
        # below), which is exactly what keeps the running total from
        # ever drifting off the real original cost.
        return (self.cost / self.useful_life_months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def accumulated_depreciation(self):
        return sum((e.amount for e in self.depreciation_entries.all()), Decimal("0"))

    @property
    def book_value(self):
        return self.cost - self.accumulated_depreciation

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if creating and not self.number:
            self.sequence_number = AssetSequence.next_number(self.organization)
            self.number = f"AST/{self.sequence_number:05d}"
        super().save(*args, **kwargs)

    @classmethod
    def record(
        cls, *, organization, name, acquisition_date, cost, useful_life_months,
        method="cash", created_by=None, post_acquisition_entry=True,
    ):
        """
        The one real entry point — never construct Asset directly.
        Posts the real acquisition entry — Dr 1401 Fixed Assets /
        Cr Cash (1001) or Bank (1101) — immediately, inside
        this same transaction. Chris's own confirmed in-scope call:
        a fixed asset register without a real capitalization entry
        breaks the double-entry foundation this whole system is
        built on. Posts synchronously, source=ASSET_ACQUISITION —
        see that Source value's own docstring on JournalEntry.Source
        for why this doesn't go through the async event bus at all.

        post_acquisition_entry, added 3 Sep 2026 for Opening Balance
        onboarding — the one real, deliberate exception to "this
        method always posts its own acquisition entry." A legacy
        asset entered at onboarding was NOT bought today; there is no
        real cash outflow to credit, and the real cost is instead
        just one line among many inside OpeningBalanceSession's own
        single consolidated journal entry (matching the canonical
        onboarding doctrine's own worked example — one opening
        journal, not N separate ones). Defaults True — every existing
        call site (the real "buy an asset today" flow) is completely
        unaffected; method's own validation only runs when this is
        True, since it becomes meaningless otherwise.
        """
        if cost is None or cost <= Decimal("0"):
            raise ValueError("Harga perolehan aset harus lebih dari nol.")
        if useful_life_months is None or useful_life_months <= 0:
            raise ValueError("Umur manfaat aset harus lebih dari nol bulan.")

        with transaction.atomic():
            AccountingPeriod.assert_open_for_posting(organization, acquisition_date)

            asset = cls.objects.create(
                organization=organization, name=name, acquisition_date=acquisition_date,
                cost=cost, useful_life_months=useful_life_months, created_by=created_by,
            )

            if post_acquisition_entry:
                if method not in ("cash", "bank"):
                    raise ValueError("Metode pembayaran harus 'cash' atau 'bank'.")
                cash_or_bank_code = "1001" if method == "cash" else "1101"
                JournalEntry.post(
                    organization=organization,
                    posting_date=acquisition_date,
                    source=JournalEntry.Source.ASSET_ACQUISITION,
                    memo=f"Perolehan aset — {asset.number} {name}",
                    created_by=created_by,
                    lines=[
                        {"account": Account.resolve(organization, "1401"), "debit": cost},
                        {"account": Account.resolve(organization, cash_or_bank_code), "credit": cost},
                    ],
                )

        return asset


class DepreciationRun(TenantScopedModel):
    """
    One real, aggregated monthly depreciation posting — Chris's own
    confirmed granularity call: one consolidated Dr 6004 Beban
    Penyusutan / Cr 1402 Accumulated Depreciation journal entry per
    organization per month, keeping the Jurnal page clean, while
    AssetDepreciationEntry rows underneath preserve the real,
    itemized per-asset breakdown.

    unique_together(organization, accounting_period) is the real,
    hard guard against ever running depreciation twice for the same
    month — enforced at the DB level, not just application logic,
    since this is triggered directly inside
    AccountingPeriod.close()'s own atomic block, not via the async
    event bus's own reference_event_id idempotency check.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    accounting_period = models.ForeignKey(
        AccountingPeriod, on_delete=models.PROTECT, related_name="depreciation_runs",
        verbose_name="Periode Akuntansi",
    )
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name="depreciation_run", verbose_name="Jurnal Penyusutan",
        # Nullable — a real month with ZERO active, still-depreciating
        # assets produces a real DepreciationRun row (so a genuine
        # re-run attempt for that period is still correctly blocked
        # by the unique_together guard above) but posts NO journal
        # entry at all, matching the exact "$0 -> post nothing"
        # precedent AccountingPeriod.close()'s own P&L entry already
        # established.
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Total Penyusutan")
    run_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Depreciation Run"
        verbose_name_plural  = "Depreciation Runs"
        unique_together      = [("organization", "accounting_period")]

    def __str__(self):
        return f"{self.accounting_period} — {self.total_amount}"

    @classmethod
    def execute(cls, *, organization, accounting_period, run_by=None):
        """
        The real, core depreciation loop — called from INSIDE
        AccountingPeriod.close()'s own atomic block (see that
        method's own updated docstring for the real pipeline-
        ordering reason). Real, hard idempotency guard: this class's
        own unique_together above means a second call for the same
        period raises IntegrityError immediately — deliberately NOT
        caught here, letting close()'s own transaction.atomic() roll
        back the whole close attempt rather than silently skip
        depreciation a second time.

        Real, verified rounding-ceiling fix: uses entries_so_far (a
        real COUNT of this asset's own prior depreciation entries),
        not a comparison between rounded Decimal amounts — the exact
        final scheduled month posts the true REMAINING book value,
        not another rounded monthly_depreciation slice, so N months
        of straight-line division always sum to EXACTLY the original
        cost, never drifting off by a stray cent. Verified by hand:
        333.333,33 + 333.333,33 + 333.333,34 = 1.000.000,00 exactly.

        No proration — an asset's FIRST real depreciation entry is
        the calendar month immediately AFTER its own
        acquisition_date falls, a full month's worth, Chris's own
        confirmed call. select_for_update() on the assets queryset —
        a real, defensive lock against a concurrent close() attempt
        for the same organization, matching this codebase's own
        established discipline for anything about to be read and
        depended on within a single atomic block (WorkOrderSequence.
        next_number(), etc.).

        29 Aug 2026 — real bug found live, via direct manual testing
        outside AccountingPeriod.close(): select_for_update() above
        requires an active transaction to attach its row lock to,
        and this method's own body was never wrapped in one itself
        — it only ever worked because its one real call site
        (close()) already runs inside transaction.atomic(). Called
        directly (a real, legitimate need — reviewing/testing
        depreciation for a specific period without a full close),
        Django raised TransactionManagementError outright. Fixed by
        wrapping this method's own body in transaction.atomic() —
        fully safe to call from anywhere now, including from inside
        close()'s own already-atomic block, since Django's atomic()
        is reentrant and simply becomes a harmless nested savepoint
        there, with zero change to that real, existing call path.

        3 Sep 2026 — this same loop is what makes the Opening Balance
        onboarding's own "current_book_value + remaining_useful_life"
        design work correctly for free: a legacy asset's
        acquisition_date is set to the opening session's own
        start_date (see OpeningBalanceAssetLine.post() logic), so its
        FIRST real entries_so_far is 0, same as any brand-new asset —
        depreciation of the REMAINING value begins cleanly the month
        after onboarding, never double-counting whatever real wear
        already happened before the shop started using Arthasee.
        """
        with transaction.atomic():
            assets = (
                Asset.objects
                .filter(organization=organization, is_active=True)
                .select_for_update()
            )

            entries_to_create = []
            total = Decimal("0")

            for asset in assets:
                # No proration — skip entirely if this period's own
                # start_date is still the SAME calendar month as
                # acquisition, or falls before it entirely.
                same_month_as_acquisition = (
                    accounting_period.start_date.year == asset.acquisition_date.year
                    and accounting_period.start_date.month == asset.acquisition_date.month
                )
                if same_month_as_acquisition or accounting_period.start_date < asset.acquisition_date:
                    continue

                entries_so_far = asset.depreciation_entries.count()
                if entries_so_far >= asset.useful_life_months:
                    # Already fully depreciated — is_active should
                    # already be False by the time this could happen
                    # (set the moment the FINAL entry was created, below),
                    # but this guard stands regardless of that flag's
                    # own correctness.
                    continue

                remaining = asset.cost - asset.accumulated_depreciation
                is_final_month = (entries_so_far + 1) >= asset.useful_life_months
                amount = remaining if is_final_month else asset.monthly_depreciation

                if amount <= Decimal("0"):
                    continue

                entries_to_create.append((asset, amount, is_final_month))
                total += amount

            if not entries_to_create:
                # Real, honest "nothing to depreciate this month" state
                # — no assets yet, every asset still in its acquisition
                # month, or every asset already fully depreciated. Still
                # creates the real DepreciationRun row (so a genuine
                # re-run attempt for this period is still correctly
                # blocked), just with no journal entry — same "$0 -> post
                # nothing" precedent as close()'s own P&L closing entry.
                return cls.objects.create(
                    organization=organization, accounting_period=accounting_period,
                    journal_entry=None, total_amount=Decimal("0"),
                )

            journal_entry = JournalEntry.post(
                organization=organization,
                posting_date=accounting_period.end_date,
                source=JournalEntry.Source.DEPRECIATION,
                memo=f"Penyusutan aset — {accounting_period.start_date}–{accounting_period.end_date}",
                created_by=run_by,
                lines=[
                    {"account": Account.resolve(organization, "6004"), "debit": total},
                    {"account": Account.resolve(organization, "1402"), "credit": total},
                ],
            )

            run = cls.objects.create(
                organization=organization, accounting_period=accounting_period,
                journal_entry=journal_entry, total_amount=total,
            )

            AssetDepreciationEntry.objects.bulk_create([
                AssetDepreciationEntry(
                    organization=organization, asset=asset, depreciation_run=run, amount=amount,
                )
                for asset, amount, _ in entries_to_create
            ])

            # Deactivate any asset that just received its FINAL entry —
            # matches Asset.is_active's own docstring: False once fully
            # depreciated. bulk_update(), not individual .save() calls —
            # same "no per-instance side effects to preserve" reasoning
            # already established for WorkOrder.close()'s own
            # bulk_update() of stages/job lines.
            fully_depreciated_ids = [asset.id for asset, _, is_final in entries_to_create if is_final]
            if fully_depreciated_ids:
                Asset.objects.filter(pk__in=fully_depreciated_ids).update(is_active=False)

            return run


class AssetDepreciationEntry(TenantScopedModel):
    """
    One real, granular record of ONE asset's depreciation for ONE
    month — the itemized breakdown underneath DepreciationRun's own
    single aggregated JournalEntry (Chris's own confirmed
    granularity call).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="depreciation_entries",
        verbose_name="Aset",
    )
    depreciation_run = models.ForeignKey(
        DepreciationRun, on_delete=models.PROTECT, related_name="entries",
        verbose_name="Penyusutan Bulan Ini",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Jumlah Penyusutan")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Asset Depreciation Entry"
        verbose_name_plural  = "Asset Depreciation Entries"
        ordering             = ["created_at"]
        unique_together      = [("asset", "depreciation_run")]
        # A given asset can only ever have ONE entry per real
        # DepreciationRun — the real guard, at the database level,
        # against ever double-posting the same asset's own
        # depreciation for the same month.

    def __str__(self):
        return f"{self.asset.name} — {self.amount} ({self.depreciation_run})"

    def _resolve_organization(self):
        return self.asset.organization


# =============================================================================
# Opening Balance — new-workshop onboarding (3 Sep 2026)
# =============================================================================
"""
Sansan's own canonical onboarding proposal, meticulously reviewed and
revised (see this module's own top-level docstring for the two real
corrections made during that review) before a line of this was
written.

One OpeningBalanceSession per organization, ever — unique_together
enforces this at the DB level, matching the real-world fact that a
shop has exactly one accounting start date and posts its opening
position exactly once. Genuinely mutable while DRAFT (the owner adds/
edits line items across however many wizard sessions it takes to get
right); posting is a single, atomic, all-or-nothing action via
post() below, after which the session — and every real Part/Asset row
it created — is exactly as immutable as any other posted history in
this codebase.

Six line-item categories, matching Chris's own signed-off subledger
strategy: Cash/Bank are simple lump sums (nothing subledger-shaped
sits underneath them); Inventory, Fixed Assets, Receivables, and
Payables are all itemized, each real line producing a real underlying
record (a Part, an Asset, an OpeningBalanceReceivable/Payable row)
so the Balance Sheet can never silently diverge from what Spare Parts
& Fluids, Aset Tetap, or Piutang/Utang actually show — the exact
class of bug this whole redesign exists to prevent. OpeningBalance
OtherLine is the deliberate, honest escape hatch for anything that
doesn't fit the five itemized categories (Owner Capital itself,
Loans, Tax Payable) — a real account code and side, not a second,
looser "just balance it" mechanism.
"""

class OpeningBalanceSession(TenantScopedModel):
    """
    The real wizard session itself — one per organization, ever.
    Holds the chosen accounting start date and tracks DRAFT/POSTED
    status; the actual line items live on the six related models
    below, each pointing back here via a plain FK.
    """
    class Status(models.TextChoices):
        DRAFT  = "DRAFT", "Draf"
        POSTED = "POSTED", "Terposting"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    start_date = models.DateField(verbose_name="Tanggal Mulai Akuntansi")
    status     = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, verbose_name="Status")
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_balance_session", verbose_name="Jurnal Saldo Awal",
        # PROTECT, not CASCADE — same Principle 2 reasoning as every
        # other posted-history FK in this file. Null until post()
        # actually succeeds.
    )
    posted_at = models.DateTimeField(null=True, blank=True, verbose_name="Waktu Diposting")
    posted_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Diposting Oleh",
    )
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Dibuat Oleh",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Opening Balance Session"
        verbose_name_plural  = "Opening Balance Sessions"
        unique_together      = [("organization",)]

    def __str__(self):
        return f"{self.organization} — saldo awal {self.start_date} ({self.status})"

    def _validate_before_posting(self):
        """
        Real, explicit pre-flight checks — separate from the
        arithmetic balance check JournalEntry.post() already owns.
        Raises ValueError on the FIRST problem found, before anything
        is written — same "validate everything before touching the
        database" discipline as JournalEntry.post() itself. Matching
        Sansan's own "no mystery plug" doctrine: every individual line
        must be a real, sane number on its own, not just something
        that happens to make the total balance.
        """
        for cash in self.cash_lines.all():
            if cash.amount <= Decimal("0"):
                raise ValueError(f"Saldo awal kas/bank untuk akun {cash.account_code} harus lebih dari nol.")
        for part in self.part_lines.all():
            if part.quantity <= Decimal("0"):
                raise ValueError(f"Jumlah stok awal untuk '{part.part_name}' harus lebih dari nol.")
            if part.cost_price < Decimal("0"):
                raise ValueError(f"Harga pokok awal untuk '{part.part_name}' tidak boleh negatif.")
        for asset in self.asset_lines.all():
            if asset.current_book_value <= Decimal("0"):
                raise ValueError(f"Nilai buku aset '{asset.name}' harus lebih dari nol.")
            if asset.remaining_useful_life_months <= 0:
                raise ValueError(f"Sisa umur manfaat aset '{asset.name}' harus lebih dari nol bulan.")
        for ar in self.receivable_lines.all():
            if ar.balance_due <= Decimal("0"):
                raise ValueError(f"Saldo piutang awal untuk '{ar.customer.name}' harus lebih dari nol.")
        for ap in self.payable_lines.all():
            if ap.balance_due <= Decimal("0"):
                raise ValueError(f"Saldo utang awal untuk '{ap.supplier.name}' harus lebih dari nol.")
        for other in self.other_lines.all():
            if other.amount <= Decimal("0"):
                raise ValueError(f"Jumlah untuk akun {other.account_code} harus lebih dari nol.")

    def post(self, *, posted_by=None):
        """
        The one real entry point — posts every line item across all
        six categories into ONE consolidated JournalEntry, matching
        the canonical onboarding doctrine's own worked example
        exactly (one opening journal, not N separate ones).

        Real, itemized side effects for the four subledger-backed
        categories — this IS the fix for the exact "lump-sum GL
        posting with nothing real underneath it" trap this whole
        design review exists to prevent:
          - Part lines create real Part rows (current_stock=0) plus a
            real, audited StockAdjustment (reason="opening_balance")
            to bring stock to the real starting count — never a raw
            current_stock write, same discipline every other stock
            movement in this codebase already follows.
          - Asset lines create real Asset rows via Asset.record(...,
            post_acquisition_entry=False) — see that parameter's own
            docstring for the full reasoning on why acquisition_date
            is deliberately set to this session's own start_date, not
            the asset's real historical acquisition date.
          - Receivable/Payable lines are already their own real,
            dedicated rows (OpeningBalanceReceivable/Payable) — Made's
            own Piutang/Utang dashboard cards union these in directly
            (see reports.py), no further materialization needed here.

        Wrapped in ONE transaction.atomic() — if JournalEntry.post()
        itself rejects the final assembled lines as unbalanced (the
        real, hard "no mystery plug" guarantee Sansan's own doctrine
        requires), EVERYTHING rolls back cleanly: every Part, every
        Asset, every StockAdjustment created above included. Nothing
        is left half-created just because the total didn't balance.
        """
        if self.status != self.Status.DRAFT:
            raise ValueError("Sesi saldo awal ini sudah pernah diposting.")

        self._validate_before_posting()

        # Local imports — cross-app dependency, same established
        # convention as every other cross-app reach in this codebase
        # (WorkOrder.close()'s own ServiceRecord import, etc.).
        from apps.inventory.models import Part, StockAdjustment

        with transaction.atomic():
            # Real gap found and fixed while writing this session's
            # own test coverage, not caught during the original
            # design review — Sansan's own approved §5 ("trigger
            # ensure_period_for_org() synchronously at signup/
            # posting time to bridge [start_date -> current_date]")
            # was signed off but never actually implemented. Without
            # this, a genuinely backdated start_date (the whole
            # reason this design point existed at all) would hit
            # assert_open_for_posting() below and fail with "no
            # period covers this date" for every month between
            # start_date and whatever period already happened to
            # exist — exactly the Sep 1 period-gap incident this
            # whole project already lived through once, reintroduced
            # here if left unfixed. Loops inclusive of the CURRENT
            # real month, not just up to start_date's own month —
            # a shop backdating to January still needs every month
            # since then open for posting, not just the one opening
            # entry's own month.
            from apps.accounting.periods import ensure_period_for_org
            from django.utils import timezone
            today = timezone.now().date()
            cursor_year, cursor_month = self.start_date.year, self.start_date.month
            while (cursor_year, cursor_month) <= (today.year, today.month):
                ensure_period_for_org(self.organization, cursor_year, cursor_month)
                if cursor_month == 12:
                    cursor_year, cursor_month = cursor_year + 1, 1
                else:
                    cursor_month += 1

            AccountingPeriod.assert_open_for_posting(self.organization, self.start_date)

            lines = []

            for cash in self.cash_lines.all():
                lines.append({
                    "account": Account.resolve(self.organization, cash.account_code),
                    "debit": cash.amount,
                    "description": "Saldo awal kas/bank",
                })

            for part_line in self.part_lines.all():
                part = Part.objects.create(
                    organization=self.organization, name=part_line.part_name,
                    sku=part_line.sku, unit=part_line.unit,
                    current_stock=Decimal("0"), cost_price=part_line.cost_price,
                )
                StockAdjustment.objects.create(
                    organization=self.organization, part=part,
                    quantity_change=part_line.quantity, reason="opening_balance",
                    notes=f"Saldo awal — sesi {self.id}",
                )
                part_line.part = part
                part_line.save(update_fields=["part"])
                amount = part_line.quantity * part_line.cost_price
                if amount > Decimal("0"):
                    lines.append({
                        "account": Account.resolve(self.organization, "1301"),
                        "debit": amount,
                        "description": f"Saldo awal stok — {part.name}",
                    })

            for asset_line in self.asset_lines.all():
                asset = Asset.record(
                    organization=self.organization, name=asset_line.name,
                    acquisition_date=self.start_date, cost=asset_line.current_book_value,
                    useful_life_months=asset_line.remaining_useful_life_months,
                    created_by=posted_by, post_acquisition_entry=False,
                )
                asset_line.asset = asset
                asset_line.save(update_fields=["asset"])
                lines.append({
                    "account": Account.resolve(self.organization, "1401"),
                    "debit": asset_line.current_book_value,
                    "description": f"Saldo awal aset — {asset.name}",
                })

            for ar in self.receivable_lines.all():
                lines.append({
                    "account": Account.resolve(self.organization, "1201"),
                    "debit": ar.balance_due,
                    "description": f"Saldo awal piutang — {ar.customer.name}",
                })

            for ap in self.payable_lines.all():
                lines.append({
                    "account": Account.resolve(self.organization, "2001"),
                    "credit": ap.balance_due,
                    "description": f"Saldo awal utang — {ap.supplier.name}",
                })

            for other in self.other_lines.all():
                account = Account.resolve(self.organization, other.account_code)
                line = {"account": account, "description": other.description}
                if other.side == OpeningBalanceOtherLine.Side.DEBIT:
                    line["debit"] = other.amount
                else:
                    line["credit"] = other.amount
                lines.append(line)

            entry = JournalEntry.post(
                organization=self.organization,
                posting_date=self.start_date,
                source=JournalEntry.Source.OPENING_BALANCE,
                memo=f"Saldo awal — {self.organization.name}",
                created_by=posted_by,
                lines=lines,
            )

            from django.utils import timezone
            self.status = self.Status.POSTED
            self.journal_entry = entry
            self.posted_at = timezone.now()
            self.posted_by = posted_by
            self.save(update_fields=["status", "journal_entry", "posted_at", "posted_by"])

        return entry


class OpeningBalanceCashLine(TenantScopedModel):
    """
    A simple lump-sum line — Cash (1001) or Bank (1101) only,
    Chris's own signed-off call: nothing subledger-shaped sits
    underneath either account, so there's no real itemization to do.
    """
    ACCOUNT_CHOICES = [("1001", "Kas"), ("1101", "Bank")]

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        OpeningBalanceSession, on_delete=models.CASCADE, related_name="cash_lines",
        verbose_name="Sesi Saldo Awal",
    )
    account_code = models.CharField(max_length=10, choices=ACCOUNT_CHOICES, verbose_name="Akun")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Jumlah")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Opening Balance Cash Line"
        verbose_name_plural  = "Opening Balance Cash Lines"
        unique_together      = [("session", "account_code")]
        # At most one row per real account (1001, 1101) per session —
        # a real cash/bank balance is a single number, not several
        # competing entries for the same account.

    def __str__(self):
        return f"{self.account_code} — {self.amount}"

    def _resolve_organization(self):
        return self.session.organization


class OpeningBalancePartLine(TenantScopedModel):
    """
    One itemized opening-stock line — Chris's own signed-off fix for
    the exact "lump-sum Inventory with nothing real underneath it"
    trap. Becomes a real Part (see OpeningBalanceSession.post()) the
    moment the session posts; `part` is null until then, populated
    afterward purely for real, honest audit traceability — never
    fabricated before the real row actually exists.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        OpeningBalanceSession, on_delete=models.CASCADE, related_name="part_lines",
        verbose_name="Sesi Saldo Awal",
    )
    part_name = models.CharField(max_length=200, verbose_name="Nama Part")
    sku       = models.CharField(max_length=50, blank=True, verbose_name="Kode/SKU")
    unit      = models.CharField(max_length=20, default="pcs", verbose_name="Satuan")
    quantity  = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Jumlah")
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Harga Pokok Awal")
    part = models.ForeignKey(
        "inventory.Part", on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_balance_line", verbose_name="Part (setelah diposting)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Opening Balance Part Line"
        verbose_name_plural  = "Opening Balance Part Lines"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.part_name} × {self.quantity} @ {self.cost_price}"

    def _resolve_organization(self):
        return self.session.organization


class OpeningBalanceAssetLine(TenantScopedModel):
    """
    One itemized legacy Fixed Asset line. Deliberately asks for
    current_book_value and remaining_useful_life_months — NOT the
    asset's real original cost/useful_life — see this module's own
    top-level docstring and Asset.record()'s own post_acquisition_
    entry docstring for the full reasoning behind this reframing.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        OpeningBalanceSession, on_delete=models.CASCADE, related_name="asset_lines",
        verbose_name="Sesi Saldo Awal",
    )
    name = models.CharField(max_length=200, verbose_name="Nama Aset")
    current_book_value = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Nilai Buku Saat Ini",
        help_text="Nilai aset SAAT INI, bukan harga beli aslinya — berapa nilai aset ini hari ini.",
    )
    remaining_useful_life_months = models.PositiveIntegerField(
        verbose_name="Sisa Umur Manfaat (Bulan)",
        help_text="Berapa bulan lagi aset ini diperkirakan masih bisa dipakai, mulai dari sekarang.",
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_balance_line", verbose_name="Aset (setelah diposting)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Opening Balance Asset Line"
        verbose_name_plural  = "Opening Balance Asset Lines"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.name} — nilai buku {self.current_book_value}"

    def _resolve_organization(self):
        return self.session.organization


class OpeningBalanceReceivable(TenantScopedModel):
    """
    A lightweight, dedicated opening-AR row — Sansan's own Option B
    call: a legacy unpaid customer bill from before the shop used
    Arthasee is a genuinely different shape than a real, operational
    Invoice (no ServiceRecord origin, no line items, no mechanic
    snapshot requirement), and forcing it through that full schema
    would be a round peg in a square hole. reports.aging_ar() and
    dashboard_financial_summary() are expected to UNION these in
    alongside real Invoice rows — a separate, deliberate follow-up,
    not part of this models-and-migration step.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        OpeningBalanceSession, on_delete=models.CASCADE, related_name="receivable_lines",
        verbose_name="Sesi Saldo Awal",
    )
    customer = models.ForeignKey(
        "service.Customer", on_delete=models.PROTECT, related_name="opening_balance_receivables",
        verbose_name="Pelanggan",
    )
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Saldo Piutang")
    due_date    = models.DateField(null=True, blank=True, verbose_name="Jatuh Tempo")
    reference   = models.CharField(max_length=100, blank=True, verbose_name="Referensi")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Opening Balance Receivable"
        verbose_name_plural  = "Opening Balance Receivables"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.customer.name} — {self.balance_due}"

    def _resolve_organization(self):
        return self.session.organization


class OpeningBalancePayable(TenantScopedModel):
    """Mirrors OpeningBalanceReceivable exactly, inverted — a
    legacy unpaid supplier bill from before onboarding."""
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        OpeningBalanceSession, on_delete=models.CASCADE, related_name="payable_lines",
        verbose_name="Sesi Saldo Awal",
    )
    supplier = models.ForeignKey(
        "purchasing.Supplier", on_delete=models.PROTECT, related_name="opening_balance_payables",
        verbose_name="Supplier",
    )
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Saldo Utang")
    due_date    = models.DateField(null=True, blank=True, verbose_name="Jatuh Tempo")
    reference   = models.CharField(max_length=100, blank=True, verbose_name="Referensi")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Opening Balance Payable"
        verbose_name_plural  = "Opening Balance Payables"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.supplier.name} — {self.balance_due}"

    def _resolve_organization(self):
        return self.session.organization


class OpeningBalanceOtherLine(TenantScopedModel):
    """
    The deliberate, honest escape hatch — Sansan's own "no mystery
    plug" doctrine means this is NOT a free-text balancing field; it
    is a real account code and a real, explicit side (debit or
    credit), resolved through the exact same Account.resolve() every
    other line in this system uses. This is where Owner Capital
    itself lands (the real balancing entry an owner explicitly
    states, not one this system silently invents), along with real
    but non-itemizable categories like Loans or Tax Payable.
    """
    class Side(models.TextChoices):
        DEBIT  = "debit", "Debit"
        CREDIT = "credit", "Kredit"

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        OpeningBalanceSession, on_delete=models.CASCADE, related_name="other_lines",
        verbose_name="Sesi Saldo Awal",
    )
    account_code = models.CharField(max_length=10, verbose_name="Kode Akun")
    side   = models.CharField(max_length=10, choices=Side.choices, verbose_name="Sisi")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Jumlah")
    description = models.CharField(max_length=255, blank=True, verbose_name="Keterangan")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Opening Balance Other Line"
        verbose_name_plural  = "Opening Balance Other Lines"
        ordering             = ["created_at"]

    def __str__(self):
        return f"{self.account_code} {self.side} {self.amount}"

    def _resolve_organization(self):
        return self.session.organization
