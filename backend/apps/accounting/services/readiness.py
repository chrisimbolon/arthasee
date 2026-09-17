# =============================================================================
# NEW FILE: backend/apps/accounting/services/readiness.py
# =============================================================================
"""
Arthasee — Brand-New Workshop Readiness

Real, reusable ORGANIZATION-LEVEL readiness check — locked spec,
17 Sep 2026 (see brand-new-workshop-readiness-spec.md). Deliberately
separate from any individual workflow's own preconditions (a Work
Order still requires its own assigned mechanic at close() time, an
Invoice still requires an open period for its own specific posting
date, etc.) — this answers ONE question: is Arthasee's own
accounting foundation safe to build real operational/accounting
records on top of, for this organization, right now.

Every consuming app (apps.estimates, apps.workorders, apps.invoicing,
apps.payments) calls check_organization_readiness() directly — this
module has zero knowledge of any of them, and none of them duplicate
this logic themselves.

Response shape is deliberately machine-readable, not a message
string to parse — Chris's own confirmed requirement, so the Indonesian
UI copy can change freely without ever touching calling code:

    {
        "ready": bool,
        "blocks": [{"code": str, "message": str, "action": str}, ...],
        "warnings": [{"code": str, "message": str}, ...],
    }

`blocks` is empty exactly when `ready` is True — never a separate
thing to check independently. `action` on a block is one of a small,
real, fixed set of frontend routing hints (see ACTION_* constants
below) — never a free-form string a frontend would have to guess at.
"""
from apps.accounting.models import Account, AccountingPeriod, OpeningBalanceSession
from apps.accounting.services.required_accounts import REQUIRED_POSTING_ACCOUNT_CODES

# Real, fixed set of frontend routing hints a block's own "action"
# can carry — never a free-form string. Both point at real,
# already-existing screens (Pengaturan Bengkel's own Akuntansi
# section, and the Opening Balance wizard) — this module names them,
# it doesn't invent new frontend routes.
ACTION_OPEN_ACCOUNTING_SETUP = "OPEN_ACCOUNTING_SETUP"
ACTION_OPEN_OPENING_BALANCE = "OPEN_OPENING_BALANCE"


def check_organization_readiness(organization) -> dict:
    """
    The one real, shared readiness check. Never raises for a
    genuinely not-ready org — that's the real, expected BLOCKED
    case, returned as data (ready=False + blocks), not an exception.
    Only a genuine programming error (e.g. organization is None)
    would raise, same as any other real bug.
    """
    blocks = []
    warnings = []

    # --- Hard block 1: COA seeded -------------------------------------
    # --- Hard block 2: required posting accounts exist ----------------
    # Nested deliberately — if COA hasn't been seeded AT ALL, every
    # required account is trivially missing too; showing both blocks
    # would just be redundant noise for the same real root cause. The
    # required-accounts check only fires once SOME accounts already
    # exist (a partially-seeded or manually-edited COA missing
    # something Arthasee's own posting rules depend on).
    seeded_count = Account.objects.filter(organization=organization).count()
    if seeded_count == 0:
        blocks.append({
            "code": "COA_NOT_SEEDED",
            "message": "COA Arthasee belum dikonfigurasi.",
            "action": ACTION_OPEN_ACCOUNTING_SETUP,
        })
    else:
        existing_codes = set(
            Account.objects.filter(
                organization=organization, code__in=REQUIRED_POSTING_ACCOUNT_CODES,
            ).values_list("code", flat=True)
        )
        missing_codes = REQUIRED_POSTING_ACCOUNT_CODES - existing_codes
        if missing_codes:
            blocks.append({
                "code": "REQUIRED_ACCOUNTS_MISSING",
                "message": (
                    f"Akun wajib berikut belum ada di COA: "
                    f"{', '.join(sorted(missing_codes))}."
                ),
                "action": ACTION_OPEN_ACCOUNTING_SETUP,
            })

    # --- Hard block 3: accounting periods configured -------------------
    if not AccountingPeriod.objects.filter(organization=organization).exists():
        blocks.append({
            "code": "NO_ACCOUNTING_PERIOD",
            "message": "Belum ada periode akuntansi yang dikonfigurasi.",
            "action": ACTION_OPEN_ACCOUNTING_SETUP,
        })

    # --- Hard block 4: opening position resolved ------------------------
    # POSTED, or explicitly confirmed zero — see
    # OpeningBalanceSession.is_opening_position_resolved's own
    # docstring for exactly why an empty DRAFT session alone is NOT
    # enough (the real, previously-indistinguishable "hasn't finished
    # yet" gap this whole feature exists to close).
    session = OpeningBalanceSession.objects.filter(organization=organization).first()
    if session is None or not session.is_opening_position_resolved:
        blocks.append({
            "code": "OPENING_BALANCE_NOT_RESOLVED",
            "message": "Saldo awal belum diposting atau dikonfirmasi nihil.",
            "action": ACTION_OPEN_OPENING_BALANCE,
        })

    # --- Warnings (never block) -----------------------------------------
    # Local imports — apps.accounting has no other reason to depend on
    # apps.inventory/apps.workorders/apps.service/apps.purchasing at
    # module level, same cross-app convention this codebase already
    # follows everywhere else (e.g. WorkOrder.close()'s own local
    # ServiceRecord import).
    from apps.inventory.models import Part
    from apps.workorders.models import Mechanic
    from apps.service.models import Customer
    from apps.purchasing.models import Supplier

    if not Part.objects.filter(organization=organization, current_stock__gt=0).exists():
        warnings.append({
            "code": "ZERO_INVENTORY",
            "message": "Belum ada saldo persediaan (parts & fluids).",
        })
    if not Mechanic.objects.filter(organization=organization, is_active=True).exists():
        warnings.append({
            "code": "NO_MECHANICS",
            "message": "Belum ada mekanik yang tercatat.",
        })
    if not Customer.objects.filter(organization=organization).exists():
        warnings.append({
            "code": "NO_CUSTOMERS",
            "message": "Belum ada pelanggan yang tercatat.",
        })
    if not Supplier.objects.filter(organization=organization).exists():
        warnings.append({
            "code": "NO_SUPPLIERS",
            "message": "Belum ada supplier yang tercatat.",
        })

    return {
        "ready": len(blocks) == 0,
        "blocks": blocks,
        "warnings": warnings,
    }
