# =============================================================================
# === backend/apps/accounting/admin.py ===
# =============================================================================
"""
6 Sep 2026 — real, substantial lockdown, found via a design-review
trace (Sansan's own "can Django Admin modify a posted journal
directly" question, Q72), not a live incident. Five real gaps closed,
each calibrated to that model's own actual risk — not a blanket
"make everything readonly" pass:

  - JournalEntry/JournalLine: NOTHING about a posted entry may ever
    change through admin — no edit, no add, no delete, matching the
    exact "frozen once real" discipline this whole codebase already
    enforces everywhere else (JournalEntry.post() is the only real
    write path; there is no edit/delete endpoint anywhere in this
    app's own urls.py either). Admin here is for inspection/audit
    ONLY, never a second, unguarded write path standing next to a
    codebase that's otherwise extremely disciplined about this.

  - AccountingPeriod: same treatment — is_closed/is_locked must ONLY
    ever change through the real AccountingPeriod.close()/reopen()
    methods (via their own owner-only, audited views), never a raw
    admin field edit that skips every guard those methods enforce.

  - Account: a real, different risk profile — name/description/
    is_active are safe, legitimate admin edits (is_active especially,
    given the real historical-report fix already applied there — see
    reports.py's own "is_active must never gate a reporting query"
    note). code/account_type/normal_balance are NOT safe once real
    postings exist against an account — Account.balance() reads these
    fields LIVE, so changing one retroactively reinterprets every
    historical balance calculation for that account. Locked down
    specifically, not the whole model.

  - JournalEntrySequence: last_sequence readonly — a manual edit here
    couldn't create a real DUPLICATE entry_number (the real
    unique_together constraint on JournalEntry itself would catch
    that as an IntegrityError), but could silently SKIP a number,
    a real if low-stakes cosmetic gap in the sequence, not worth
    leaving open for no reason.
"""
from apps.accounting.models import (Account, AccountingPeriod, JournalEntry,
                                    JournalEntrySequence, JournalLine)
from django.contrib import admin


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display  = ("code", "name", "account_type", "normal_balance", "organization", "is_active")
    list_filter   = ("account_type", "normal_balance", "is_active", "organization")
    search_fields = ("code", "name")
    ordering      = ("organization", "code")
    # 6 Sep 2026 — real fix: code/account_type/normal_balance are
    # NOT safe to edit once real postings exist against an account —
    # Account.balance() reads these fields LIVE at query time, so
    # changing one here would retroactively reinterpret every
    # historical balance calculation for that account. name/
    # description/is_active stay editable — genuinely safe, ordinary
    # lifecycle edits, no historical-interpretation risk.
    #
    # 9 Sep 2026 — real, follow-up fix: account_subtype/is_contra
    # added to this tuple. Both predate this lockdown (Phase 16, 8
    # Sep 2026) and were never added when Account.record()/
    # apply_edit() shipped (Phase 17, Tasks 17.1/17.2) — a genuine
    # gap, found during that work's own test-writing pass, not a
    # live incident. Worse than merely "unprotected": Account.save()
    # DERIVES account_type/normal_balance from account_subtype
    # unconditionally (see that method's own docstring) — editing
    # account_subtype directly here would silently overwrite the
    # very two fields this tuple already locks down, making that
    # existing protection illusory. Locked down UNCONDITIONALLY
    # (always readonly, not just once real history exists) —
    # deliberately matching the same simple, categorical, static
    # pattern code/account_type/normal_balance already use here,
    # rather than a dynamic per-object check. Now that a real,
    # guarded creation/edit path exists (AccountListCreateView/
    # AccountDetailView, backend views.py — Account.apply_edit()'s
    # own has-posted-history guard, enforced there, not here), Admin
    # no longer needs to be a fallback way to set classification at
    # all.
    #
    # 9 Sep 2026 — Phase 18, Task 18.1. is_control_account MOVED into
    # readonly_fields above — real reversal of the 6 Sep note this
    # replaces. It's no longer a free, independently-settable field
    # at all: Account.save() now derives it unconditionally from
    # account_subtype whenever one is set (IS_CONTROL_SUBTYPES,
    # models.py), the same "derived, never a checkbox" treatment
    # account_type/normal_balance already had. Leaving it editable
    # here would make that derivation illusory — the same class of
    # gap the 9 Sep 2026 account_subtype/is_contra fix above already
    # closed once. `parent` remains deliberately NOT in this tuple —
    # pure presentation metadata, zero rollup math anywhere, genuinely
    # unaffected by this change.
    readonly_fields = (
        "code", "account_type", "normal_balance", "account_subtype", "is_contra",
        "is_control_account", "organization",
    )


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ("organization", "start_date", "end_date", "is_closed", "is_locked")
    list_filter  = ("is_closed", "is_locked", "organization")
    # 6 Sep 2026 — real fix: is_closed/is_locked must ONLY ever
    # change through AccountingPeriod.close()/reopen() themselves —
    # both real, audited, owner-only-gated methods with real
    # business logic (the chronological-order guard, the permanent
    # closed_at marker, reopened_by attribution) that a raw admin
    # field edit would completely bypass. Every field made readonly,
    # not just the two status flags — start_date/end_date defining a
    # period that real JournalEntry rows already resolved against
    # must never silently move either. Add/delete disabled below —
    # periods are only ever created via ensure_period_for_org().
    readonly_fields = (
        "organization", "year", "month", "start_date", "end_date",
        "is_closed", "is_locked", "closed_at", "closed_by",
        "reopened_at", "reopened_by",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    readonly_fields = ("account", "debit_amount", "credit_amount", "description")
    can_delete = False

    # 6 Sep 2026 — real fix: extra=0 only suppresses BLANK rows on
    # initial page load — it does NOT disable the "Add another" link
    # Django Admin still renders for the related model by default.
    # Without this override, a brand-new line (any account, any
    # amount) could be added to an already-posted, previously-
    # balanced entry, with zero re-validation — admin's default save
    # path never calls JournalEntry.post()'s own balance check.
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display  = ("entry_number", "organization", "posting_date", "source", "event_type", "status")
    list_filter   = ("source", "status", "organization")
    search_fields = ("entry_number", "event_type", "reference_event_id", "memo")
    ordering      = ("-posting_date", "-sequence_number")
    inlines       = [JournalLineInline]
    # 6 Sep 2026 — real fix, expanding the existing (incomplete)
    # readonly_fields to cover EVERY field, not just entry_number/
    # sequence_number/source/event_type/reference_event_id/status.
    # posting_date/accounting_period/organization/created_by/memo
    # were all still directly editable before this fix — organization
    # being editable was the sharpest one, a real tenant-reassignment
    # risk on a posted financial record. Journal entries are only
    # ever created via JournalEntry.post() — admin is for inspection/
    # audit only, never a second, unguarded write path. Add/delete
    # disabled below, closing the real gap that let a posted entry
    # (and, via cascade, every one of its lines) be deleted outright
    # through the default admin delete flow — directly contradicting
    # this whole codebase's own "a posted journal can never be
    # deleted" guarantee.
    readonly_fields = (
        "organization", "entry_number", "sequence_number", "posting_date",
        "accounting_period", "source", "event_type", "reference_event_id",
        "status", "memo", "created_by", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JournalEntrySequence)
class JournalEntrySequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "last_sequence")
    # 6 Sep 2026 — real fix: a manual edit here couldn't create a
    # true duplicate entry_number (JournalEntry's own real
    # unique_together constraint would catch that as an
    # IntegrityError at the DB level regardless), but could silently
    # SKIP a number — a real, if low-stakes, gap in the sequence with
    # no reason to leave open. Add/delete disabled — this row is
    # purely internal plumbing, created automatically on first real
    # use (see next_number()'s own get_or_create()), never something
    # to create or remove by hand.
    readonly_fields = ("organization", "last_sequence")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
