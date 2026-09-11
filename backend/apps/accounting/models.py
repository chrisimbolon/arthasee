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

8 Sep 2026 — Granular Account Subtypes & Control-Account Enforcement,
following a direct review with a professional accountant (Aris —
Chris's brother) against a real, mature reference implementation.
Real, deliberate design, confirmed with Chris before writing this:
  1. `account_subtype` (21 granular values, matching the reference's
     own real taxonomy exactly) is ADDITIVE, not a replacement for
     the existing 6-bucket `account_type` — every report function in
     reports.py keeps reading `account_type` completely unchanged.
     When `account_subtype` is set, `account_type`/`normal_balance`
     are DERIVED from it automatically (save(), below) — matching
     the reference's own real UI behavior ("Ditentukan otomatis
     berdasarkan tipe akun sesuai standar akuntansi"), not two
     independently-settable fields that could drift apart.
     Deliberately left OPTIONAL at the model level (blank=True),
     unlike the reference's own required field — hundreds of existing
     tests across this whole codebase create Account rows with a
     manually-set account_type/normal_balance and no subtype at all;
     making it required would break every one of them for a cosmetic
     reason. New/updated accounts should set it; nothing forces
     migration of untouched historical test fixtures.
  2. `is_contra` — a real, explicit boolean, matching the reference's
     own "Akun Kontra" checkbox exactly. Flips the DERIVED
     normal_balance only; account_type itself never flips (a contra-
     asset is still an ASSET-type account, appearing in the Asset
     section of the Balance Sheet, just reducing rather than adding
     to the total — see Account.balance()'s own arithmetic, already
     correct for this via normal_balance alone). This is the real,
     general mechanism `1402` (Accumulated Depreciation) always
     needed and never had a name for — no special-casing anywhere
     else in this codebase now required for a future second contra
     account.
  3. `is_control_account` — a real, explicit boolean. Enforcement
     moved from a soft, view-layer WARNING (ManualJournalListCreate
     View.post()'s own old _CONTROL_ACCOUNT_CODES set) into a hard,
     engine-level BLOCK inside JournalEntry.post() itself — see that
     method's own updated docstring. Deliberately scoped to
     source == MANUAL only: DOMAIN_EVENT, OPENING_BALANCE,
     ASSET_ACQUISITION, PERIOD_CLOSING, and DEPRECIATION all touch
     control accounts legitimately, every single day, and must never
     be blocked by this guard.
  4. Opening Balance Equity plug — real, deliberate hybrid design,
     confirmed with Chris: JournalEntry.post() stays 100% strict, no
     hidden balancing anywhere inside the engine. OpeningBalanceSession
     itself is the ONE orchestration layer allowed to compute and
     append a real, visible plug line to a new account, 3002 (Ekuitas
     Saldo Awal) — but ONLY after a real pre-commit review endpoint
     (see views.py's new OpeningBalancePreviewView) has already shown
     the exact figure. See OpeningBalanceSession._build_line_specs(),
     .compute_variance(), and .post() below for the full mechanism.
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from apps.core.models import TenantScopedModel
from django.db import models, transaction
from django.db.models import Sum

_UNSET = object()  # real sentinel — see Account.apply_edit()'s own docstring
                    # for why `parent` needs three states (untouched / clear /
                    # set), which plain `None` alone can't express.

class Account(TenantScopedModel):
    """
    One row per Chart-of-Accounts line, per Organization — see
    management/commands/seed_coa.py for the standard set every shop
    starts with (Roadmap v2.2 COA Blueprint). Shops can add their own
    beyond the standard set later; nothing here restricts that.

    9 Sep 2026 — Phase 17, Task 17.2. `parent` is DELIBERATELY pure
    presentation/organizational metadata — a real, confirmed design
    call, not a placeholder for a future rollup. Account.balance()
    and every report function in reports.py (trial_balance(),
    balance_sheet(), etc.) sum every individual Account row flatly
    by account_type/normal_balance, completely unchanged by this
    field's existence — a parent and its children are simply two
    (or more) independent rows in that same flat sum, mathematically
    identical to today's behavior for a shop that only ever posts at
    the child (till) level. This closes off the exact class of risk
    that produced the real, live contra-asset summation bug caught
    in balance_sheet() before it shipped (Phase 12) — a rollup here
    would mean re-deriving balance summation logic, which is
    precisely what that incident proved is easy to get wrong. If a
    real "parent + children combined total" need ever surfaces, it
    becomes its own new, separately-tested report function — never
    a change to Account.balance() or the two trusted, already-proven
    report functions (Open Decision #21).    
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

    class AccountSubtype(models.TextChoices):
        """
        8 Sep 2026 — the 21 granular subtypes, matching Aris's own
        real reference implementation exactly (verbatim labels, same
        order as that system's own "Daftar 21 tipe akun" list). This
        is the REAL classification a shop's own accountant thinks
        in — "Kas dan Setara Kas" vs "Piutang Lainnya" vs "Aset
        Tetap" — one level more specific than the 6-bucket
        AccountType this system already had, which only distinguishes
        Asset/Liability/Equity/Revenue/COGS/Expense.
        """
        KAS_SETARA_KAS            = "KAS_SETARA_KAS", "Kas dan Setara Kas"
        PIUTANG_USAHA              = "PIUTANG_USAHA", "Piutang Usaha"
        PIUTANG_LAINNYA            = "PIUTANG_LAINNYA", "Piutang Lainnya"
        PERSEDIAAN                 = "PERSEDIAAN", "Persediaan"
        BIAYA_DIBAYAR_DIMUKA       = "BIAYA_DIBAYAR_DIMUKA", "Biaya Dibayar Dimuka"
        ASET_TETAP                 = "ASET_TETAP", "Aset Tetap"
        ASET_TAKBERWUJUD           = "ASET_TAKBERWUJUD", "Aset Takberwujud"
        INVESTASI                  = "INVESTASI", "Investasi"
        ASET_LAINNYA               = "ASET_LAINNYA", "Aset Lainnya"
        UTANG_USAHA                = "UTANG_USAHA", "Utang Usaha"
        UTANG_LAINNYA              = "UTANG_LAINNYA", "Utang Lainnya"
        UTANG_PAJAK                = "UTANG_PAJAK", "Utang Pajak"
        LIABILITAS_KEUANGAN        = "LIABILITAS_KEUANGAN", "Liabilitas Keuangan"
        PENDAPATAN_DITERIMA_DIMUKA = "PENDAPATAN_DITERIMA_DIMUKA", "Pendapatan Diterima Dimuka"
        UTANG_JANGKA_PANJANG       = "UTANG_JANGKA_PANJANG", "Utang Jangka Panjang"
        EKUITAS                    = "EKUITAS", "Ekuitas"
        PENDAPATAN                 = "PENDAPATAN", "Pendapatan"
        PENDAPATAN_LAIN_LAIN       = "PENDAPATAN_LAIN_LAIN", "Pendapatan Lain-lain"
        BEBAN_POKOK_PENJUALAN      = "BEBAN_POKOK_PENJUALAN", "Beban Pokok Penjualan"
        BEBAN_USAHA                = "BEBAN_USAHA", "Beban Usaha"
        BEBAN_LAIN_LAIN            = "BEBAN_LAIN_LAIN", "Beban Lain-lain"

    SUBTYPE_CLASSIFICATION = {
        AccountSubtype.KAS_SETARA_KAS:            (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.PIUTANG_USAHA:              (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.PIUTANG_LAINNYA:            (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.PERSEDIAAN:                 (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.BIAYA_DIBAYAR_DIMUKA:       (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.ASET_TETAP:                 (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.ASET_TAKBERWUJUD:           (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.INVESTASI:                  (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.ASET_LAINNYA:               (AccountType.ASSET, NormalBalance.DEBIT),
        AccountSubtype.UTANG_USAHA:                (AccountType.LIABILITY, NormalBalance.CREDIT),
        AccountSubtype.UTANG_LAINNYA:              (AccountType.LIABILITY, NormalBalance.CREDIT),
        AccountSubtype.UTANG_PAJAK:                (AccountType.LIABILITY, NormalBalance.CREDIT),
        AccountSubtype.LIABILITAS_KEUANGAN:        (AccountType.LIABILITY, NormalBalance.CREDIT),
        AccountSubtype.PENDAPATAN_DITERIMA_DIMUKA: (AccountType.LIABILITY, NormalBalance.CREDIT),
        AccountSubtype.UTANG_JANGKA_PANJANG:       (AccountType.LIABILITY, NormalBalance.CREDIT),
        AccountSubtype.EKUITAS:                    (AccountType.EQUITY, NormalBalance.CREDIT),
        AccountSubtype.PENDAPATAN:                 (AccountType.REVENUE, NormalBalance.CREDIT),
        AccountSubtype.PENDAPATAN_LAIN_LAIN:       (AccountType.REVENUE, NormalBalance.CREDIT),
        AccountSubtype.BEBAN_POKOK_PENJUALAN:      (AccountType.COGS, NormalBalance.DEBIT),
        AccountSubtype.BEBAN_USAHA:                (AccountType.EXPENSE, NormalBalance.DEBIT),
        AccountSubtype.BEBAN_LAIN_LAIN:            (AccountType.EXPENSE, NormalBalance.DEBIT),
    }

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=10, verbose_name="Kode Akun")
    name = models.CharField(max_length=200, verbose_name="Nama Akun")
    account_type = models.CharField(
        max_length=20, choices=AccountType.choices, verbose_name="Tipe Akun",
    )
    normal_balance = models.CharField(
        max_length=10, choices=NormalBalance.choices, verbose_name="Saldo Normal",
    )
    account_subtype = models.CharField(
        max_length=40, choices=AccountSubtype.choices, blank=True, default="",
        verbose_name="Sub-Tipe Akun",
        help_text="Menentukan posisi akun di laporan keuangan secara otomatis "
                  "(mengisi Tipe Akun & Saldo Normal). Opsional untuk akun lama.",
    )
    is_contra = models.BooleanField(
        default=False, verbose_name="Akun Kontra",
        help_text="Akun kontra dikurangkan dari total, bukan ditambahkan — "
                  "contoh: Akumulasi Penyusutan, Cadangan Kerugian Piutang. "
                  "Membalik Saldo Normal yang diturunkan dari Sub-Tipe Akun.",
    )
    is_control_account = models.BooleanField(
        default=False, verbose_name="Akun Kontrol",
        help_text="Akun kontrol tidak dapat menerima entri jurnal manual — "
                  "saldonya harus selalu sama dengan total sub-ledger terkait "
                  "(mis. AR harus sama dengan total tagihan pelanggan).",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="children", verbose_name="Sub-Akun Dari",
        help_text="Menjadikan akun ini sebagai sub-akun dari akun lain — "
                  "murni untuk pengelompokan tampilan (mis. beberapa Kas Kecil "
                  "di bawah satu Kas & Bank). TIDAK mempengaruhi Account.balance() "
                  "atau laporan mana pun — lihat class docstring Account di atas.",
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

    def save(self, *args, **kwargs):
        """
        8 Sep 2026 — real derivation step, added for account_subtype.
        Only runs when account_subtype is actually set — an account
        with no subtype (every pre-existing row, and any future row
        that deliberately doesn't use this feature) passes through
        completely unchanged, preserving today's exact behavior. When
        a subtype IS set, account_type/normal_balance are ALWAYS
        overwritten from SUBTYPE_CLASSIFICATION — never independently
        trusted from whatever was passed in, matching the reference's
        own real UI ("Ditentukan otomatis... Pilih Tipe Akun terlebih
        dahulu"). is_contra flips normal_balance only, never
        account_type — see class docstring for why that's correct
        (a contra-asset is still an ASSET-type account).
        """
        if self.account_subtype:
            base_type, base_normal = self.SUBTYPE_CLASSIFICATION[self.account_subtype]
            self.account_type = base_type
            if self.is_contra:
                self.normal_balance = (
                    self.NormalBalance.CREDIT if base_normal == self.NormalBalance.DEBIT
                    else self.NormalBalance.DEBIT
                )
            else:
                self.normal_balance = base_normal
        super().save(*args, **kwargs)

    def balance(self, *, since=None, as_of=None, exclude_closing_entries=False) -> Decimal:
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
        try:
            return cls.objects.get(organization=organization, code=code)
        except cls.DoesNotExist as exc:
            raise ValueError(
                f"No Account with code={code!r} found for organization "
                f"{organization.name!r} — has the Chart of Accounts been "
                f"seeded (python manage.py seed_coa)?"
            ) from exc

    @classmethod
    def record(
        cls, *, organization, code, name, account_subtype,
        is_contra=False, is_control_account=False, description="", parent=None,
    ):
        """
        9 Sep 2026 — Phase 17, Task 17.1 (create), extended in Task
        17.2 with real `parent` support. The one real entry point for
        creating a CUSTOM Account via the live API
        (AccountListCreateView.post()). `seed_coa.py`'s own idempotent
        `get_or_create()` remains the separate, deliberate path for
        the standard COA at signup/backfill time — unchanged by this.

        `account_subtype` is REQUIRED here — `account_type`/
        `normal_balance` are never accepted as direct input at all,
        always derived server-side by `save()` (see Phase 16's own
        precedent). `parent`, if given, is resolved against a real
        Account belonging to the SAME organization — never trusted as
        a bare cross-tenant UUID (same tenant-isolation discipline as
        every other real FK resolution in this codebase, e.g.
        OpeningBalanceReceivableListCreateView's own Customer lookup).
        No cycle check is needed here — a brand-new account cannot
        already be an ancestor of anything, so setting its parent at
        creation time can never create a cycle. Cycle prevention only
        matters for `apply_edit()` below, where an EXISTING account's
        parent can be reassigned after the fact.
        """
        code = (code or "").strip()
        if not code:
            raise ValueError("Kode akun tidak boleh kosong.")
        name = (name or "").strip()
        if not name:
            raise ValueError("Nama akun tidak boleh kosong.")
        if account_subtype not in cls.SUBTYPE_CLASSIFICATION:
            raise ValueError(f"Sub-tipe akun tidak valid: {account_subtype!r}.")

        parent_account = None
        if parent is not None:
            parent_account = cls.objects.filter(organization=organization, pk=parent).first()
            if parent_account is None:
                raise ValueError("Akun induk (parent) tidak ditemukan untuk organisasi ini.")

        with transaction.atomic():
            if cls.objects.filter(organization=organization, code=code).exists():
                raise ValueError(f"Akun dengan kode {code!r} sudah ada untuk organisasi ini.")
            try:
                account = cls.objects.create(
                    organization=organization,
                    code=code,
                    name=name,
                    account_subtype=account_subtype,
                    is_contra=is_contra,
                    is_control_account=is_control_account,
                    description=description,
                    parent=parent_account,
                )
            except IntegrityError:
                raise ValueError(f"Akun dengan kode {code!r} sudah ada untuk organisasi ini.")

        return account

    def _would_create_cycle(self, candidate_parent):
        """
        True if setting `candidate_parent` as this account's own
        parent would create a cycle in the hierarchy — i.e.
        candidate_parent IS this account, or candidate_parent is
        currently a DESCENDANT of this account. Walks UP from
        candidate_parent through its own real chain of parents,
        checking whether that chain ever reaches back to self — if it
        does, self is already an ancestor of candidate_parent, so
        making candidate_parent the new parent of self would close a
        loop (self -> candidate_parent -> ... -> self).

        Real, defensive hop limit (100) — should be genuinely
        unreachable given this exact guard is what prevents a cycle
        from ever being created in the first place, but a malformed
        or corrupted hierarchy must never hang a real request in an
        infinite loop. A real shop's own till hierarchy is expected
        to be 2-3 levels deep at most; 100 is a circuit breaker, not
        a realistic depth limit.
        """
        if candidate_parent.pk == self.pk:
            return True
        seen = {self.pk}
        node = candidate_parent
        hops = 0
        while node is not None:
            if node.pk in seen:
                return True
            seen.add(node.pk)
            node = node.parent
            hops += 1
            if hops > 100:
                raise ValueError(
                    "Struktur akun induk terlalu dalam atau tidak valid — "
                    "tidak bisa memverifikasi apakah perubahan ini aman."
                )
        return False

    def apply_edit(
        self, *, name=None, description=None, is_active=None,
        account_subtype=None, is_contra=None, is_control_account=None,
        parent=_UNSET,
    ):
        """
        9 Sep 2026 — Phase 17, Task 17.1 (base fields), extended in
        Task 17.2 with real `parent` reassignment. The one real path
        for editing an existing Account — called only from
        AccountDetailView.patch(). `code` is deliberately still not a
        parameter at all — immutable after creation.

        `parent` uses the module-level `_UNSET` sentinel as its
        default, not `None` — a genuine three-state field: omitted
        entirely (this call doesn't touch parent at all), explicitly
        `None` (clear it — this account becomes top-level), or a real
        Account id (reassign it). Plain `None` as the default
        couldn't distinguish "don't touch" from "clear" the way every
        other field here safely can, since every other field's
        "don't touch" state (`None`) is not itself a real, valid value
        a caller would ever intentionally set — `parent` is the one
        exception, since NULL is a genuine, meaningful state for it
        (top-level account).

        Real, deliberate split in what gets guarded and what doesn't:
        the classification guard below (account_subtype/is_contra vs.
        real posted history) is UNCHANGED from Task 17.1 and does NOT
        cover `parent` — reassigning a parent never touches
        Account.balance()'s own arithmetic for a single existing
        JournalLine (see this class's own docstring: parent is pure
        presentation metadata, zero rollup math anywhere). A real
        cycle check (`_would_create_cycle()` above) is the only real
        guard `parent` itself needs — a structural validity check,
        not a financial-integrity one.
        """
        classification_changed = (
            (account_subtype is not None and account_subtype != self.account_subtype)
            or (is_contra is not None and is_contra != self.is_contra)
        )
        if classification_changed and JournalLine.objects.filter(account=self).exists():
            raise ValueError(
                f"Akun {self.code} sudah memiliki riwayat transaksi terposting — "
                f"sub-tipe akun dan status akun kontra tidak bisa diubah lagi, "
                f"karena akan membalik interpretasi saldo dari transaksi yang "
                f"sudah ada. Buat akun baru jika klasifikasi yang benar berbeda."
            )

        if name is not None:
            stripped = name.strip()
            if not stripped:
                raise ValueError("Nama akun tidak boleh kosong.")
            self.name = stripped
        if description is not None:
            self.description = description
        if is_active is not None:
            self.is_active = is_active
        if account_subtype is not None:
            self.account_subtype = account_subtype
        if is_contra is not None:
            self.is_contra = is_contra
        if is_control_account is not None:
            self.is_control_account = is_control_account

        if parent is not _UNSET:
            if parent is None:
                self.parent = None
            else:
                parent_account = Account.objects.filter(organization=self.organization, pk=parent).first()
                if parent_account is None:
                    raise ValueError("Akun induk (parent) tidak ditemukan untuk organisasi ini.")
                if self._would_create_cycle(parent_account):
                    raise ValueError(
                        f"Tidak bisa menjadikan {parent_account.code} sebagai induk dari "
                        f"{self.code} — akan membuat struktur akun melingkar (circular)."
                    )
                self.parent = parent_account

        self.save()
        return self        

class AccountingPeriod(TenantScopedModel):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    year       = models.PositiveIntegerField(verbose_name="Tahun")
    month      = models.PositiveSmallIntegerField(verbose_name="Bulan")  # 1-12
    start_date = models.DateField(verbose_name="Tanggal Mulai")
    end_date   = models.DateField(verbose_name="Tanggal Selesai")
    is_closed  = models.BooleanField(default=False, verbose_name="Ditutup")
    is_locked  = models.BooleanField(default=False, verbose_name="Terkunci")
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
        from apps.accounting.reports import _period_totals
        from django.utils import timezone

        if self.closed_at is not None:
            raise ValueError(
                "Periode ini sudah pernah ditutup sebelumnya — tidak bisa ditutup "
                "ulang, bahkan setelah dibuka kembali. Diperlukan penanganan manual "
                "untuk koreksi lebih lanjut."
            )

        # 9 Sep 2026 — Phase 18, Task 18.6. Real, deliberate LOOSENING
        # of this exact guard (added 4 Sep 2026) — now conditional on
        # the organization's own requires_sequential_period_closing
        # flag (Organization model, apps.organizations). default=True
        # means every existing organization gets byte-identical
        # behavior to before this shipped; only an organization that
        # explicitly opts out via Pengaturan Bengkel can close periods
        # out of order. See that field's own docstring for the full
        # reasoning — sequential closing is a real, deliberate ERP-
        # level policy choice, not an accounting law, per Chris's own
        # confirmed call. Every OTHER guard in this method (the
        # closed_at check above, the permanent closed_at marker set
        # below) is completely unaffected by this flag — it only ever
        # relaxes the sequential-order check specifically.
        if self.organization.requires_sequential_period_closing:
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
        PERIOD_CLOSING = "PERIOD_CLOSING", "Penutupan Periode"
        ASSET_ACQUISITION = "ASSET_ACQUISITION", "Perolehan Aset"
        DEPRECIATION = "DEPRECIATION", "Penyusutan Aset"
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
        debit == total credit, non-zero total, exactly one side set
        per line, and — 8 Sep 2026 — that a MANUAL entry never
        touches a real control account. A JournalEntry with
        mismatched, malformed, or illegally-targeted lines must never
        be able to exist even transiently — same "guarantee your own
        atomicity, don't trust the caller" discipline as
        WorkOrder.close()/cancel().

        8 Sep 2026 — real control-account guard, promoted from a
        soft, view-layer WARNING (ManualJournalListCreateView.post()'s
        own old _CONTROL_ACCOUNT_CODES set, which still let the post
        through) into a hard, engine-level BLOCK — following a direct
        review with a professional accountant against a real
        reference implementation, which enforces this at the engine,
        never the view. Deliberately scoped to source == MANUAL only:
        DOMAIN_EVENT, OPENING_BALANCE, ASSET_ACQUISITION,
        PERIOD_CLOSING, and DEPRECIATION all touch control accounts
        (1201/1301/2001, as of this same review) legitimately, every
        single day — this guard must never block any of them. Checked
        here, in the one real write path every source goes through,
        not duplicated in each individual view.
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

        if source == cls.Source.MANUAL:
            control_codes_touched = sorted({
                line["account"].code for line in lines
                if getattr(line["account"], "is_control_account", False)
            })
            if control_codes_touched:
                raise ValueError(
                    f"Akun kontrol ({', '.join(control_codes_touched)}) tidak bisa "
                    f"menerima entri jurnal manual — saldo akun kontrol harus selalu "
                    f"sama dengan total sub-ledger terkait (mis. Piutang Usaha harus "
                    f"sama dengan total tagihan pelanggan yang belum lunas)."
                )

        with transaction.atomic():
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

"""
Real, manual bank-statement reconciliation — v1 scope, per the Phase
17 design spec: manual statement entry only, no live bank-feed
integration (Open Decision #20). Synchronous, no event bus — matching
BankStatementLine/ReconciliationMatch are both a read-and-match
concern entirely internal to this app, never a domain event another
app needs to react to (same "would this still make sense if the
event bus were deleted?" test Asset.record()/AccountingPeriod.close()
already pass).

Neither model ever touches JournalEntry/JournalLine's own write path
— a BankStatementLine is never part of the real ledger, and a
ReconciliationMatch creates or alters NOTHING in it either. Directly
aligned with Principle #15 (Immutable-on-Post): reconciling a
statement line can never cause drift, because it never mutates a
posted fact, only annotates a correspondence between two already-
real, already-correct records.
"""


class BankStatementLine(TenantScopedModel):
    """
    One real, manually-entered line from a bank statement. Never
    itself part of the real ledger — purely a second, independent
    record of what the bank itself reports, to be compared against
    what this system already posted.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="statement_lines",
        verbose_name="Akun",
    )
    statement_date = models.DateField(verbose_name="Tanggal Transaksi")
    description = models.CharField(max_length=255, verbose_name="Keterangan")
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name="Jumlah",
        help_text="Positif untuk uang masuk, negatif untuk uang keluar.",
    )
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Dicatat Oleh",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Bank Statement Line"
        verbose_name_plural  = "Bank Statement Lines"
        ordering             = ["-statement_date"]

    def __str__(self):
        return f"{self.account.code} {self.statement_date} {self.amount}"

    @property
    def is_matched(self) -> bool:
        """
        Computed, never stored — same "never a second source of
        truth" discipline as Asset.accumulated_depreciation/
        book_value (both derived live from real
        AssetDepreciationEntry rows, never a cached field that could
        drift). A statement line is matched exactly when a real
        ReconciliationMatch row references it — nothing else needs
        to track or sync this.
        """
        return self.matches.exists()

    @classmethod
    def record(cls, *, organization, account_code, statement_date, description, amount, created_by=None):
        """The one real entry point for manually entering a
        statement line. `account_code` resolved the same way every
        other real posting in this codebase resolves one
        (Account.resolve()) — never a bare Account UUID."""
        account = Account.resolve(organization, account_code)
        if amount == Decimal("0"):
            raise ValueError("Jumlah baris rekening koran tidak boleh nol.")
        return cls.objects.create(
            organization=organization, account=account, statement_date=statement_date,
            description=description, amount=amount, created_by=created_by,
        )


class ReconciliationMatch(TenantScopedModel):
    """
    One real correspondence between a BankStatementLine and a
    JournalLine. `statement_line`/`journal_line` are both PROTECT —
    same "a target with real linked history must never vanish out
    from under it" discipline as JournalLine.account: deleting a
    matched statement line or journal line is blocked until the
    match itself is removed first.

    Real grain: one row per (statement_line, journal_line) PAIR — a
    genuine 1-to-many correspondence (one statement line matching
    several journal lines, or vice versa) is supported by
    CONSTRUCTION, simply as multiple rows sharing one side. Full
    N-to-N combination matching is deliberately deferred (Open
    Decision #22).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    statement_line = models.ForeignKey(
        BankStatementLine, on_delete=models.PROTECT, related_name="matches",
        verbose_name="Baris Rekening Koran",
    )
    journal_line = models.ForeignKey(
        JournalLine, on_delete=models.PROTECT, related_name="reconciliation_matches",
        verbose_name="Baris Jurnal",
    )
    matched_at = models.DateTimeField(auto_now_add=True)
    matched_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Dicocokkan Oleh",
    )

    class Meta:
        verbose_name        = "Reconciliation Match"
        verbose_name_plural  = "Reconciliation Matches"
        ordering             = ["-matched_at"]
        unique_together      = [("statement_line", "journal_line")]

    def __str__(self):
        return f"{self.statement_line} <-> {self.journal_line}"

    def _resolve_organization(self):
        return self.statement_line.organization

    @classmethod
    def record(cls, *, statement_line, journal_line, matched_by=None):
        """
        The one real entry point. Validates BEFORE writing: same
        organization on both sides (tenant isolation — a match must
        never span two different shops), and journal_line's own
        account must be the SAME account as statement_line — the
        entire point of reconciliation is comparing one real account
        against its own bank statement; matching a Cash statement
        line against a COGS journal line would be structurally
        meaningless. The unique_together above is the final DB-level
        backstop against a genuine duplicate pairing.
        """
        if statement_line.organization_id != journal_line.journal_entry.organization_id:
            raise ValueError("Baris rekening koran dan baris jurnal harus berasal dari organisasi yang sama.")
        if journal_line.account_id != statement_line.account_id:
            raise ValueError(
                f"Baris jurnal ini terkait akun {journal_line.account.code}, bukan "
                f"{statement_line.account.code} — hanya baris jurnal pada akun yang sama "
                f"dengan baris rekening koran yang bisa dicocokkan."
            )
        if cls.objects.filter(statement_line=statement_line, journal_line=journal_line).exists():
            raise ValueError("Baris ini sudah pernah dicocokkan satu sama lain.")

        return cls.objects.create(
            organization=statement_line.organization,
            statement_line=statement_line, journal_line=journal_line, matched_by=matched_by,
        )

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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    accounting_period = models.ForeignKey(
        AccountingPeriod, on_delete=models.PROTECT, related_name="depreciation_runs",
        verbose_name="Periode Akuntansi",
    )
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name="depreciation_run", verbose_name="Jurnal Penyusutan",
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
        with transaction.atomic():
            assets = (
                Asset.objects
                .filter(organization=organization, is_active=True)
                .select_for_update()
            )

            entries_to_create = []
            total = Decimal("0")

            for asset in assets:
                same_month_as_acquisition = (
                    accounting_period.start_date.year == asset.acquisition_date.year
                    and accounting_period.start_date.month == asset.acquisition_date.month
                )
                if same_month_as_acquisition or accounting_period.start_date < asset.acquisition_date:
                    continue

                entries_so_far = asset.depreciation_entries.count()
                if entries_so_far >= asset.useful_life_months:
                    continue

                remaining = asset.cost - asset.accumulated_depreciation
                is_final_month = (entries_so_far + 1) >= asset.useful_life_months
                amount = remaining if is_final_month else asset.monthly_depreciation

                if amount <= Decimal("0"):
                    continue

                entries_to_create.append((asset, amount, is_final_month))
                total += amount

            if not entries_to_create:
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

            fully_depreciated_ids = [asset.id for asset, _, is_final in entries_to_create if is_final]
            if fully_depreciated_ids:
                Asset.objects.filter(pk__in=fully_depreciated_ids).update(is_active=False)

            return run


class AssetDepreciationEntry(TenantScopedModel):
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

    def __str__(self):
        return f"{self.asset.name} — {self.amount} ({self.depreciation_run})"

    def _resolve_organization(self):
        return self.asset.organization


# =============================================================================
# Opening Balance — new-workshop onboarding (3 Sep 2026)
# =============================================================================

class OpeningBalanceSession(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT  = "DRAFT", "Draf"
        POSTED = "POSTED", "Terposting"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    start_date = models.DateField(verbose_name="Tanggal Mulai Akuntansi")
    status     = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, verbose_name="Status")
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name="opening_balance_session", verbose_name="Jurnal Saldo Awal",
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

    def _build_line_specs(self):
        """
        8 Sep 2026 — the one real, shared calculation behind BOTH
        post() and the new preview endpoint (Chris/Aris's own
        confirmed hybrid design for the Opening Balance Equity plug).
        Returns RAW specs — account_code, debit/credit amount,
        description — never a resolved Account instance and never a
        created Part/Asset row. This is what GUARANTEES the exact
        figure Made reviews on the pre-commit screen is the exact
        figure that gets committed a moment later: preview and
        post() both call this same method, so they cannot drift
        apart on the arithmetic even if one of them is later edited
        without the other.

        `part_line`/`asset_line` keys carry the originating model
        instance back to post() so IT knows which real Part/Asset to
        create and which row to update afterward — the preview path
        never looks at either key, since a preview must never create
        a real side-effecting row.
        """
        specs = []

        for cash in self.cash_lines.all():
            specs.append({
                "account_code": cash.account_code, "debit": cash.amount, "credit": None,
                "description": "Saldo awal kas/bank",
            })

        for part_line in self.part_lines.all():
            amount = part_line.quantity * part_line.cost_price
            if amount > Decimal("0"):
                specs.append({
                    "account_code": "1301", "debit": amount, "credit": None,
                    "description": f"Saldo awal stok — {part_line.part_name}",
                    "part_line": part_line,
                })

        for asset_line in self.asset_lines.all():
            specs.append({
                "account_code": "1401", "debit": asset_line.current_book_value, "credit": None,
                "description": f"Saldo awal aset — {asset_line.name}",
                "asset_line": asset_line,
            })

        for ar in self.receivable_lines.all():
            specs.append({
                "account_code": "1201", "debit": ar.balance_due, "credit": None,
                "description": f"Saldo awal piutang — {ar.customer.name}",
            })

        for ap in self.payable_lines.all():
            specs.append({
                "account_code": "2001", "debit": None, "credit": ap.balance_due,
                "description": f"Saldo awal utang — {ap.supplier.name}",
            })

        for other in self.other_lines.all():
            spec = {
                "account_code": other.account_code, "description": other.description,
                "debit": None, "credit": None,
            }
            if other.side == OpeningBalanceOtherLine.Side.DEBIT:
                spec["debit"] = other.amount
            else:
                spec["credit"] = other.amount
            specs.append(spec)

        return specs

    def compute_variance(self):
        """
        8 Sep 2026 — the real, explicit variance computation behind
        the new pre-commit review gate (GET .../opening-balance/
        preview/). Chris/Aris's own confirmed doctrine: NEVER balance
        silently — Made must see this exact figure before committing.
        `plug_side` names which side (debit/credit) the 3002 plug
        line will land on if he proceeds — None when already
        balanced, matching JournalEntry.post()'s own "nothing to
        plug" case.
        """
        zero = Decimal("0")
        specs = self._build_line_specs()
        total_debit  = sum((s["debit"] or zero) for s in specs)
        total_credit = sum((s["credit"] or zero) for s in specs)
        if total_debit == total_credit:
            return {
                "total_debit": total_debit, "total_credit": total_credit,
                "variance": zero, "is_balanced": True, "plug_side": None,
            }
        variance = abs(total_debit - total_credit)
        plug_side = "credit" if total_debit > total_credit else "debit"
        return {
            "total_debit": total_debit, "total_credit": total_credit,
            "variance": variance, "is_balanced": False, "plug_side": plug_side,
        }

    def post(self, *, posted_by=None, confirm_variance=False):
        """
        The one real entry point — posts every line item across all
        six categories into ONE consolidated JournalEntry, matching
        the canonical onboarding doctrine's own worked example
        exactly (one opening journal, not N separate ones).

        8 Sep 2026 — real, explicit Opening Balance Equity plug
        added, Chris and Aris's own confirmed hybrid design following
        direct review against a real reference implementation:
        JournalEntry.post() itself stays 100% strict — no hidden
        balancing anywhere inside the engine, the "no mystery plug"
        guarantee this whole system was built on is completely
        unchanged. This orchestration layer is the ONE, deliberate,
        visible place a variance is ever allocated. Posts any
        variance to 3002 (Ekuitas Saldo Awal) — kept deliberately
        separate from 3001 (Owner Capital), so a real, explicit
        capital contribution Made states himself is never silently
        mixed together with a rounding/data-entry variance the
        system allocated on his behalf.

        8 Sep 2026 — real, second fix, found by the test suite's own
        test_unbalanced_session_rejected_with_400 immediately after
        the plug above first shipped: the plug alone made ANY
        variance silently succeed, whether or not the frontend ever
        actually showed Made the number first — nothing stopped a
        client from calling this endpoint directly, skipping the new
        preview screen entirely. That directly contradicts Chris's
        own explicit confirmation: "Made must explicitly review and
        confirm the variance before the system calls the final
        commit." `confirm_variance` closes that gap — defaults to
        False (fail closed, matching this whole codebase's own
        established discipline for anything consequential), and this
        method now REFUSES to proceed when a real variance exists and
        confirm_variance wasn't explicitly passed True. A session
        that's already balanced needs no confirmation at all — there
        is nothing to confirm — so confirm_variance is only ever
        consulted once a real variance is already known to exist.
        """
        from apps.inventory.models import Part, StockAdjustment

        with transaction.atomic():
            locked_self = OpeningBalanceSession.objects.select_for_update().get(pk=self.pk)
            if locked_self.status != self.Status.DRAFT:
                raise ValueError("Sesi saldo awal ini sudah pernah diposting.")

            self._validate_before_posting()

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

            specs = self._build_line_specs()
            lines = []

            for spec in specs:
                if "part_line" in spec:
                    part_line = spec["part_line"]
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
                elif "asset_line" in spec:
                    asset_line = spec["asset_line"]
                    asset = Asset.record(
                        organization=self.organization, name=asset_line.name,
                        acquisition_date=self.start_date, cost=asset_line.current_book_value,
                        useful_life_months=asset_line.remaining_useful_life_months,
                        created_by=posted_by, post_acquisition_entry=False,
                    )
                    asset_line.asset = asset
                    asset_line.save(update_fields=["asset"])

                lines.append({
                    "account": Account.resolve(self.organization, spec["account_code"]),
                    "debit": spec["debit"],
                    "credit": spec["credit"],
                    "description": spec["description"],
                })

            zero = Decimal("0")
            total_debit  = sum((line["debit"] or zero) for line in lines)
            total_credit = sum((line["credit"] or zero) for line in lines)
            if total_debit != total_credit:
                variance = abs(total_debit - total_credit)
                if not confirm_variance:
                    raise ValueError(
                        f"Saldo awal belum seimbang — selisih Rp{variance} akan "
                        f"dibukukan ke akun 3002 (Ekuitas Saldo Awal). Tinjau "
                        f"selisih ini terlebih dahulu (GET .../opening-balance/"
                        f"preview/), lalu kirim ulang permintaan ini dengan "
                        f"konfirmasi eksplisit untuk melanjutkan."
                    )
                plug_account = Account.resolve(self.organization, "3002")
                if total_debit > total_credit:
                    lines.append({
                        "account": plug_account, "debit": None, "credit": variance,
                        "description": "Selisih saldo awal — Ekuitas Saldo Awal",
                    })
                else:
                    lines.append({
                        "account": plug_account, "debit": variance, "credit": None,
                        "description": "Selisih saldo awal — Ekuitas Saldo Awal",
                    })

            entry = JournalEntry.post(
                organization=self.organization,
                posting_date=self.start_date,
                source=JournalEntry.Source.OPENING_BALANCE,
                memo=f"Saldo awal — {self.organization.name}",
                created_by=posted_by,
                lines=lines,
            )

            self.status = self.Status.POSTED
            self.journal_entry = entry
            self.posted_at = timezone.now()
            self.posted_by = posted_by
            self.save(update_fields=["status", "journal_entry", "posted_at", "posted_by"])

        return entry


class OpeningBalanceCashLine(TenantScopedModel):
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

    def __str__(self):
        return f"{self.account_code} — {self.amount}"

    def _resolve_organization(self):
        return self.session.organization


class OpeningBalancePartLine(TenantScopedModel):
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
