# =============================================================================
# Task 18.8 — NEW FILE: backend/apps/accounting/account_import.py
# =============================================================================
"""
Arthasee — Bulk Account Import (Phase 18, Task 18.8)

Real, deliberate v1 scope, matching the locked design spec exactly:
  - Fixed template columns only (code, name, account_subtype,
    is_contra, parent_code, description) -- no fuzzy auto-detected
    column mapping. A "Download Template" button on the frontend is
    the real answer to "what columns do I need" -- not this backend
    guessing at a user's own arbitrary header names.
  - `parent_code` must resolve to an account ALREADY in the database
    -- never another row in the same import file. This isn't just a
    simplifying rule: it's what makes a genuine parent-cycle within
    one file structurally impossible, for free, with zero extra
    cycle-detection code needed here (Account._would_create_cycle()
    still guards the real, separate case of REASSIGNING an existing
    account's parent later, via apply_edit() -- that guard is
    untouched by this file).
  - Real, in-file duplicate-code check -- a gap Account.record()
    itself never needed to worry about (it only ever sees one row at
    a time), but a bulk file genuinely can contain two rows sharing
    a code.
  - No generic ImportJob framework -- Account import only, concretely
    (Open Decision #30). Extract a shared abstraction only once a
    second real consumer (bank statement import) actually needs one.

Backend receives a plain JSON array of row dicts, never a raw file --
same "structured JSON in, Django validates" shape every other real
write endpoint in this app already uses (ManualJournalRecordSerializer's
own `lines`, JournalEntryCorrectRecordSerializer's own `lines`,
every OpeningBalance line endpoint). File parsing (CSV or pasted
Excel data) is the frontend's job -- this deliberately avoids a new
backend dependency (openpyxl or similar) for a v1 feature, and keeps
this file's only real job "is this accounting data valid," not "can
I read this binary file format."

preview_import() and commit_import() BOTH delegate to the exact same
_validate_import_rows() underneath -- same "one real calculation,
never duplicated" discipline OpeningBalanceSession._build_line_specs()
already established for the opening-balance wizard. This is what
GUARANTEES the exact rows an owner reviews on the preview screen are
the exact rows that get created a moment later -- preview and commit
cannot silently drift apart on what counts as valid, even if one of
them is edited later without the other.
"""
from django.db import transaction

from apps.accounting.models import Account


def _validate_import_rows(organization, rows):
    """
    The one real validation pass, shared by preview_import() and
    commit_import() below. Never raises -- a validation failure is
    DATA (a row-indexed error), not an exception, since the entire
    point of a preview is showing every real problem at once, not
    stopping at the first one a caller happens to hit.

    Returns (valid_rows, errors):
      - valid_rows: list of dicts, one per structurally-valid row,
        fully resolved and ready for Account.record() (parent_code
        already resolved to a real parent_id, or None).
      - errors: list of {"row": <1-based index>, "code": <str>,
        "message": <str>} dicts, one per row that failed.

    Real, deliberate design: rows is a plain list of dicts, no
    per-field DRF serializer used here -- the friendly, row-indexed,
    Indonesian-language error shape this function produces is the
    real point; DRF's own default per-field error format would be a
    worse fit for a wizard-style bulk preview screen.
    """
    errors = []
    valid_rows = []
    seen_codes_in_file = set()

    # One real query for every account this organization already
    # has -- used for BOTH the "code already exists" check and
    # parent resolution, never one query per row.
    existing_accounts = {a.code: a for a in Account.objects.filter(organization=organization)}

    for i, row in enumerate(rows, start=1):
        row_errors = []

        code = (row.get("code") or "").strip()
        name = (row.get("name") or "").strip()
        account_subtype = (row.get("account_subtype") or "").strip()
        parent_code = (row.get("parent_code") or "").strip()
        description = (row.get("description") or "").strip()

        # is_contra: a real bool or omitted (defaults False) --
        # never a string. The frontend owns normalizing whatever a
        # real spreadsheet cell contains ("TRUE"/"FALSE"/"1"/blank/
        # etc.) into a real JSON boolean before this ever reaches
        # the backend -- this endpoint's own contract is JSON, the
        # same as every other real write path in this app.
        is_contra_raw = row.get("is_contra", False)
        if isinstance(is_contra_raw, bool):
            is_contra = is_contra_raw
        else:
            row_errors.append("Akun Kontra harus bernilai true/false.")
            is_contra = False

        if not code:
            row_errors.append("Kode Akun wajib diisi.")
        if not name:
            row_errors.append("Nama Akun wajib diisi.")
        if account_subtype not in Account.SUBTYPE_CLASSIFICATION:
            row_errors.append(f"Sub-Tipe Akun tidak valid: {account_subtype!r}.")

        if code:
            if code in seen_codes_in_file:
                row_errors.append(f"Kode {code!r} duplikat di dalam file ini.")
            elif code in existing_accounts:
                row_errors.append(f"Kode {code!r} sudah ada untuk organisasi ini.")
            else:
                seen_codes_in_file.add(code)

        parent_id = None
        if parent_code:
            parent_account = existing_accounts.get(parent_code)
            if parent_account is None:
                row_errors.append(
                    f"Akun induk {parent_code!r} tidak ditemukan — akun induk harus "
                    f"sudah ada di Chart of Accounts sebelum diimpor (tidak bisa "
                    f"merujuk ke baris lain dalam file yang sama)."
                )
            else:
                parent_id = str(parent_account.id)

        if row_errors:
            errors.append({"row": i, "code": code, "message": " ".join(row_errors)})
        else:
            valid_rows.append({
                "row": i, "code": code, "name": name, "account_subtype": account_subtype,
                "is_contra": is_contra, "parent_code": parent_code or None,
                "parent_id": parent_id, "description": description,
            })

    return valid_rows, errors


def preview_import(organization, rows):
    """
    The real, read-only pre-commit review. Writes NOTHING -- safe to
    call any number of times, same "genuinely read-only" guarantee
    OpeningBalancePreviewView already gives.
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
    CURRENT real database state -- never trusts a client-side "the
    preview already passed" claim, since the file content or the
    organization's own accounts could genuinely have changed in the
    real gap between the two separate HTTP calls a real wizard flow
    always has.

    All-or-nothing -- ANY row failing validation means NOTHING is
    created, same "no mystery plug, no partial success" doctrine
    OpeningBalanceSession.post() already established for its own
    multi-line commit. Account.record()'s own per-row transaction is
    a real, safe Django savepoint nested inside this one outer
    transaction.atomic() -- if the Nth row's own real database write
    fails for a reason this validation pass couldn't have caught in
    advance (a genuine race against a concurrent request, say), the
    whole outer transaction still rolls back cleanly, not just that
    one row.
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
            account = Account.record(
                organization=organization, code=row["code"], name=row["name"],
                account_subtype=row["account_subtype"], is_contra=row["is_contra"],
                description=row["description"], parent=row["parent_id"],
            )
            created.append(account)
    return created
