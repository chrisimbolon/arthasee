# =============================================================================
# NEW FILE: backend/apps/accounting/services/required_accounts.py
# =============================================================================
"""
Arthasee — Required Posting Account Registry

Brand-New Workshop Readiness, Pillar 4 ("Arthasee Accounting Rules").
Chris's own confirmed scope, 17 Sep 2026: Arthasee owns the event ->
account posting logic; the owner never configures it. What readiness
DOES need to verify is that every account code those hardcoded rules
depend on actually EXISTS in this org's seeded COA.

6 Oct 2026 — REWRITTEN to DERIVE from coa.py's own seed data instead
of a hand-maintained literal list, closing the exact drift this file's
original docstring already warned about ("nothing enforces that sync
automatically"). That warning turned out to be concretely true: the old
hand-maintained list was missing 1403/1404/6007 (the Kendaraan asset
category, added 4 Oct 2026) entirely — found by reading this file
directly against the real coa.py while reconciling the Account Role
Mapping inventory. Any readiness check that ran for an org relying on
Kendaraan-category assets was never actually verifying those three
codes existed. This rewrite fixes that as a side effect, not a
deliberate separate change — nothing about the READINESS CHECK's own
behavior is intended to change beyond now also covering those three
codes, which it always should have.

Two real sources compose this set now:

  - STANDARD_ACCOUNT_ROLE_MAPPINGS (coa.py) — the 14 global, org-wide
    account-role dependencies posting_engine.py/models.py hardcode. See
    AccountRole's own docstring (models.py) for the full reconciliation
    this went through (Sansan's review, 6 Oct 2026).
  - STANDARD_ASSET_CATEGORIES (coa.py) — every fixed-asset category's
    own three account codes (fixed asset, accumulated depreciation,
    depreciation expense), covering every category Asset/DepreciationRun
    can post to — not just Peralatan's.

Still a real, reviewed registry, not a blind union of "every code
coa.py happens to mention" — STANDARD_COA itself seeds several codes
(4003, 5002, 5003, 6001–6006, etc.) that no hardcoded Arthasee
posting rule depends on; a shop is free to never have those and still
be fully "ready" to post. Composing from these two specific lists,
rather than from STANDARD_COA wholesale, keeps that distinction intact.
"""
from apps.accounting.coa import (STANDARD_ACCOUNT_ROLE_MAPPINGS,
                                 STANDARD_ASSET_CATEGORIES)

REQUIRED_POSTING_ACCOUNT_CODES = frozenset(
    {code for _role, code in STANDARD_ACCOUNT_ROLE_MAPPINGS}
    | {
        code
        for _name, fixed_code, accum_code, expense_code, _life, _default in STANDARD_ASSET_CATEGORIES
        for code in (fixed_code, accum_code, expense_code)
    }
)
