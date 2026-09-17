# =============================================================================
# NEW FILE: backend/apps/accounting/services/required_accounts.py
# =============================================================================
"""
Arthasee — Required Posting Account Registry

Brand-New Workshop Readiness, Pillar 4 ("Arthasee Accounting
Rules"). Chris's own confirmed scope, 17 Sep 2026: Arthasee owns the
event -> account posting logic; the owner never configures it. What
readiness DOES need to verify is that every account code those
hardcoded rules depend on actually EXISTS in this org's seeded COA —
this file is that real, enumerable list, built by reading
posting_engine.py and cancellations.py directly, not guessed at.

Deliberately a STATIC list — only codes that are hardcoded literals
in a posting rule. Three real posting rules reference a DYNAMIC
account code instead (chosen at the point the underlying record was
created, not fixed by the rule itself) — deliberately EXCLUDED here,
not omitted by oversight:

  - OperatingExpenseRecorded.account_code — Made's own chosen debit
    account per entry. Self-validating at OperatingExpense.record()
    time (Account.resolve() already raises there if invalid) — a
    workflow-specific concern, not an org-level readiness one.
  - InternalCashMutationRecorded.to_account_code/from_account_code —
    same reasoning; validated as real Cash/Bank codes at
    InternalCashMutation.record() time already.
  - PurchaseReturned.debit_account_code — constrained to exactly
    {"2010", "2001"}, both of which ARE already in the static list
    below for other reasons (SupplierInvoiceReceived/GoodsReceived),
    so no separate entry is needed for this one.

Real source, code by code — every one traced to its own real
reference, not copied from memory:

  posting_engine.py:
    1001  cash_or_bank_account_code("cash")  -- PaymentReceived, OperatingExpenseRecorded,
                                                 QuickPurchaseRecorded, SupplierPaymentMade,
                                                 cancellations.reverse_for_refund_event()
    1101  cash_or_bank_account_code(other)   -- same call sites as 1001
    1201  InvoiceIssued (debit AR), PaymentReceived (credit AR)
    1301  PartConsumed (credit), GoodsReceived (debit),
          QuickPurchaseRecorded (debit), PurchaseReturned (credit),
          StockOpnameCompleted (both sides)
    1302  PartConsumed (debit, WIP), WorkOrderCompleted (credit, WIP)
    2001  SupplierInvoiceReceived (credit AP), SupplierPaymentMade (debit AP)
    2010  GoodsReceived (credit, GR/IR), SupplierInvoiceReceived (debit, GR/IR)
    4001  InvoiceIssued (credit, Pendapatan Jasa)
    4002  InvoiceIssued (credit, Pendapatan Parts)
    4004  StockOpnameCompleted (credit, surplus)
    5001  WorkOrderCompleted (debit, Beban Pokok Jasa)
    5004  StockOpnameCompleted (debit, shortage)

  models.py (Arthasee's own internal postings — Asset acquisition,
  Depreciation, Period Closing, Opening Balance plug — just as much
  real, hardcoded Arthasee posting logic as the domain-event rules
  above, so included on the same real principle):
    1401  Asset.record() (debit), DepreciationRun.execute() (credit, accumulated)
    1402  DepreciationRun.execute() (credit)
    3002  OpeningBalanceSession.post() (opening-balance variance plug)
    3101  AccountingPeriod.close() (net income closing entry)
    6004  DepreciationRun.execute() (debit, Beban Penyusutan)

Note: this list was built from posting_engine.py, cancellations.py,
and models.py as uploaded 17 Sep 2026. If a future posting rule adds
a new hardcoded account code, it must be added here too — nothing
enforces that sync automatically; this is a deliberate, reviewed
registry, not a derived one.
"""

REQUIRED_POSTING_ACCOUNT_CODES = frozenset({
    "1001",  # Kas
    "1101",  # Bank
    "1201",  # Piutang Usaha (AR)
    "1301",  # Persediaan (Inventory)
    "1302",  # Barang Dalam Proses (WIP)
    "1401",  # Aset Tetap
    "1402",  # Akumulasi Penyusutan
    "2001",  # Utang Usaha (AP)
    "2010",  # Persediaan Belum Ditagih (Accrued Inventory / GR-IR)
    "3002",  # Ekuitas Saldo Awal (Opening Balance Equity plug)
    "3101",  # Laba Ditahan (Period Closing net income)
    "4001",  # Pendapatan Jasa
    "4002",  # Pendapatan Suku Cadang
    "4004",  # Pendapatan Lain-lain (Stock Opname surplus)
    "5001",  # Beban Pokok Jasa
    "5004",  # Beban Pokok — Selisih Stock Opname
    "6004",  # Beban Penyusutan
})
