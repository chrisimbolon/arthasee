# =============================================================================
# Bank Statement Import — NEW FILE: backend/apps/accounting/bank_statement_import.py
# =============================================================================
"""
Arthasee — Bulk Bank Statement Import

15 Sep 2026 — real, deliberate v1 scope, directly mirroring
account_import.py's own exact preview/commit shape (Phase 18, Task
18.8) — the same proven pattern for "many rows, review everything
before committing anything" already established in this codebase,
not a new design invented from scratch.

Real, architectural context this whole feature is built AROUND, not
despite — confirmed directly with Chris before writing this: a bank
statement line in Arthasee is a VERIFICATION artifact, never a
posting trigger. It exists to be matched against journal activity
that was already posted by a real domain event or a real Payment/
SupplierPayment/OperatingExpense/InternalCashMutation record() call
— it NEVER creates a JournalEntry itself, and this import mechanism
does not change that in any way. Bulk-importing 40 statement lines
still only ever creates 40 real BankStatementLine rows, exactly as
40 individual POSTs to the existing single-row endpoint would —
this is purely a faster way to get real bank data INTO the
reconciliation screen's own unmatched-lines list, never a shortcut
around real, structured posting.

Backend receives a plain JSON array of row dicts, never a raw file —
same "structured JSON in, Django validates" shape every other bulk
write in this app uses. File parsing (CSV/pasted bank export data)
is the frontend's job, same deliberate choice already made for
Account import (avoids a new backend file-parsing dependency).

preview_import() and commit_import() BOTH delegate to the exact same
_validate_import_rows() underneath — same "one real calculation,
never duplicated" discipline account_import.py already established.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Account, BankStatementLine


def _validate_import_rows(organization, rows):
    """
    The one real validation pass, shared by preview_import() and
    commit_import() below. Never raises — a validation failure is
    DATA (a row-indexed error), not an exception, same reasoning
    account_import._validate_import_rows() already established.

    Returns (valid_rows, errors):
      - valid_rows: list of dicts, one per structurally-valid row,
        fully resolved and ready for BankStatementLine.record()
        (statement_date/amount already real date/Decimal objects,
        not raw strings).
      - errors: list of {"row": <1-based index>, "description": <str>,
        "message": <str>} dicts, one per row that failed.

    account_code is resolved against a real Account here at PREVIEW
    time (Account.resolve()) — same real function every other
    account_code in this codebase resolves through — so a typo'd
    code surfaces as a clear, real row error before commit, not a
    raw exception the caller has to interpret.
    """
    errors = []
    valid_rows = []

    for i, row in enumerate(rows, start=1):
        row_errors = []

        account_code = (row.get("account_code") or "").strip()
        description = (row.get("description") or "").strip()
        statement_date_raw = row.get("statement_date")
        amount_raw = row.get("amount")

        if not account_code:
            row_errors.append("Kode Akun wajib diisi.")
        else:
            try:
                Account.resolve(organization, account_code)
            except ValueError as e:
                row_errors.append(str(e))

        if not description:
            row_errors.append("Deskripsi wajib diisi.")

        statement_date = None
        if not statement_date_raw:
            row_errors.append("Tanggal Transaksi wajib diisi.")
        else:
            try:
                statement_date = date.fromisoformat(str(statement_date_raw))
            except ValueError:
                row_errors.append(
                    f"Tanggal {statement_date_raw!r} tidak valid — gunakan format YYYY-MM-DD."
                )

        amount = None
        if amount_raw in (None, ""):
            row_errors.append("Jumlah wajib diisi.")
        else:
            try:
                amount = Decimal(str(amount_raw))
                if amount == Decimal("0"):
                    row_errors.append("Jumlah tidak boleh nol.")
            except InvalidOperation:
                row_errors.append(f"Jumlah {amount_raw!r} tidak valid.")

        if row_errors:
            errors.append({"row": i, "description": description, "message": " ".join(row_errors)})
        else:
            valid_rows.append({
                "row": i, "account_code": account_code, "statement_date": statement_date,
                "description": description, "amount": amount,
            })

    return valid_rows, errors


def preview_import(organization, rows):
    """
    The real, read-only pre-commit review. Writes NOTHING — safe to
    call any number of times, same guarantee AccountImportPreviewView
    already gives.
    """
    valid_rows, errors = _validate_import_rows(organization, rows)
    return {
        "total_rows": len(rows),
        "valid_count": len(valid_rows),
        "error_count": len(errors),
        "valid_rows": valid_rows,
        "errors": errors,
        "can_commit": len(errors) == 0 and len(valid_rows) > 0,
    }


def commit_import(organization, rows, *, created_by=None):
    """
    The real, final commit. Re-validates from scratch against the
    CURRENT real database state — never trusts a client-side "the
    preview already passed" claim, same reasoning account_import.
    commit_import() already established (an account code that
    resolved fine at preview time could theoretically have been
    deactivated/removed in the real gap between the two separate
    HTTP calls a real wizard flow always has).

    All-or-nothing — ANY row failing validation means NOTHING is
    created. Each valid row goes through the real, single-row
    BankStatementLine.record() — the exact same real entry point
    the existing single-row endpoint already uses — never a
    bulk-specific shortcut that could drift from that method's own
    real validation.
    """
    valid_rows, errors = _validate_import_rows(organization, rows)
    if errors:
        raise ValueError(
            f"{len(errors)} baris tidak valid — perbaiki dan pratinjau ulang "
            f"sebelum mengimpor."
        )
    if not valid_rows:
        raise ValueError("Tidak ada baris untuk diimpor.")

    created = []
    with transaction.atomic():
        for row in valid_rows:
            line = BankStatementLine.record(
                organization=organization, account_code=row["account_code"],
                statement_date=row["statement_date"], description=row["description"],
                amount=row["amount"], created_by=created_by,
            )
            created.append(line)
    return created
