"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/control-accounts/page.tsx ===
// =============================================================================
// 19 Sep 2026 — Phase 18, Task 18.2 (frontend, second pass). New page.
//
// "Cek Akun Kontrol": compares each control account's own General Ledger
// balance against its real subledger, side by side, for all three
// supported accounts at once — Piutang Usaha (1201), Utang Usaha (2001)
// and Persediaan (1301). Runs automatically when the page opens, and again
// whenever the date changes or "Periksa Ulang" is pressed.
//
// Why this exists as a page of its own: the first version of this feature
// lived inline inside Daftar Akun's per-account edit drawer — one account
// at a time, buried, and with no explanation for Inventory. This page is
// the "detection net" for silent posting failures (Roadmap Open Decision
// #31): an operational action can succeed while its ledger posting quietly
// dies as a FAILED Outbox row, and the first visible symptom is exactly
// an AR/AP balance that no longer matches its invoices.
//
// Read-only, everywhere. Nothing here ever writes to the ledger. The
// backend endpoint (GET /api/accounting/control-account-reconciliation/
// <code>/, reports.reconcile_control_account()) is on-demand by design
// (Open Decision #26) — this page simply calls it for the three codes.
//
// Two things about Inventory (1301) the page explains rather than hides,
// because a raw red "Selisih" there would scare owners for no reason:
//   1. Its subledger total is stock × LAST purchase price (Last Cost, Phase
//      8 / Phase 15.8's confirmed trade-off), while the ledger records each
//      purchase and each usage at the price of that moment. The two can
//      therefore differ legitimately whenever a part is restocked at a
//      different price than what is already on the shelf.
//   2. The backend computes that stock value from CURRENT stock, ignoring
//      the chosen date (reports.py: Part.objects.filter(...).aggregate(...)
//      has no as_of). For a past date the Inventory comparison is
//      structurally apples-to-oranges — the page says so.
// AR/AP have no such excuse: a difference there is shown in red, with a
// pointer to the "Postingan Gagal" panel on the Jurnal page.
//
// The list of accounts comes from RECONCILABLE_CONTROL_ACCOUNT_CODES
// (lib/api/accounting.ts), not from "every is_control_account account":
// 1302 (WIP) is a control account too, but has no subledger to compare
// against and the backend rejects it with a 400.
//
// Default date comes from todayISO() (lib/format.ts) — the shop's own
// calendar day, never `new Date().toISOString().slice(0, 10)`, which is the
// UTC day and reads "yesterday" between 00:00 and 07:00 WIB.
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  controlAccountReconciliationApi,
  ControlAccountReconciliationResult,
  RECONCILABLE_CONTROL_ACCOUNT_CODES,
} from "@/lib/api/accounting";
import { todayISO } from "@/lib/format";
import { Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

type ControlCode = (typeof RECONCILABLE_CONTROL_ACCOUNT_CODES)[number];
type ResultMap = Partial<Record<ControlCode, ControlAccountReconciliationResult>>;

function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

// maxFraction is 0 for balances, 2 for the difference: a rounding
// difference under Rp 0,50 must never render as "Selisih Rp 0".
function formatRupiah(value: string | number | null | undefined, maxFraction = 0): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: maxFraction,
  }).format(toNumber(value));
}

interface AccountInfo {
  fallbackName: string;
  subledgerLabel: string;
  subledgerHelp: string;
}

// Static, per-account wording. Names come from the backend when the check
// succeeds; fallbackName is only shown while loading or when it failed.
const ACCOUNT_INFO: Record<ControlCode, AccountInfo> = {
  "1201": {
    fallbackName: "Piutang Usaha",
    subledgerLabel: "Total Faktur Belum Lunas",
    subledgerHelp: "Sisa tagihan dari semua faktur pelanggan yang sudah terbit dan belum lunas.",
  },
  "2001": {
    fallbackName: "Utang Usaha",
    subledgerLabel: "Total Faktur Supplier Belum Dibayar",
    subledgerHelp: "Sisa tagihan dari semua faktur supplier yang sudah dicatat dan belum dibayar.",
  },
  "1301": {
    fallbackName: "Persediaan",
    subledgerLabel: "Nilai Stok Saat Ini",
    subledgerHelp:
      "Jumlah stok saat ini × harga beli terakhir (jika suatu suku cadang belum pernah dibeli, memakai harga jual).",
  },
};

function ControlAccountCard({ code, result, loading, isPastDate }: {
  code: ControlCode;
  result: ControlAccountReconciliationResult | undefined;
  loading: boolean;
  isPastDate: boolean;
}) {
  const info = ACCOUNT_INFO[code];
  const isInventory = code === "1301";

  const okResult = result && result.success ? result : null;
  const failedResult = result && !result.success ? result : null;
  const reconciled = okResult?.is_reconciled === true;
  const mismatch = okResult !== null && !reconciled;
  const differenceValue = okResult?.difference !== undefined ? toNumber(okResult.difference) : 0;

  // AR/AP mismatch = a real warning (red). Inventory mismatch = neutral —
  // it can be perfectly normal (see the note below the figures).
  const statusColor = reconciled
    ? "var(--workshop)"
    : isInventory ? "var(--steel)" : "var(--danger)";

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Akun {code}</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{okResult?.account_name ?? info.fallbackName}</div>
        </div>
        {okResult && !loading && (
          <div style={{ fontSize: 14, fontWeight: 600, color: statusColor }}>
            {reconciled ? "Seimbang" : `Selisih ${formatRupiah(okResult.difference, 2)}`}
          </div>
        )}
      </div>

      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 24, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : failedResult ? (
        <div style={{ fontSize: 13, color: "var(--danger)" }}>
          {failedResult.message ?? "Gagal memeriksa rekonsiliasi."}
        </div>
      ) : okResult ? (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            <div>
              <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Saldo Buku Besar</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{formatRupiah(okResult.gl_balance)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11.5, color: "var(--steel)" }}>{info.subledgerLabel}</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{formatRupiah(okResult.subledger_total)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11.5, color: "var(--steel)" }}>Selisih</div>
              <div className="mono" style={{ fontSize: 20, fontWeight: 600, color: statusColor }}>
                {formatRupiah(okResult.difference, 2)}
              </div>
            </div>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 10 }}>{info.subledgerHelp}</div>
          {mismatch && (
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 4 }}>
              {differenceValue > 0
                ? "Saldo Buku Besar lebih besar dari sub-ledger."
                : "Saldo Buku Besar lebih kecil dari sub-ledger."}
            </div>
          )}
        </>
      ) : null}

      {/* AR / AP mismatch — a real warning, with a concrete next step. */}
      {!loading && mismatch && !isInventory && (
        <div style={{ background: "var(--paper-2)", borderRadius: 6, padding: 12, marginTop: 14, fontSize: 13 }}>
          <div style={{ fontWeight: 600, color: "var(--danger)", marginBottom: 4 }}>Perlu diperiksa</div>
          Saldo Buku Besar dan daftar faktur tidak lagi sama. Penyebab yang paling umum: ada postingan yang
          gagal diproses. Buka panel <b>Postingan Gagal</b> di halaman{" "}
          <Link href="/dashboard/accounting/journal" style={{ color: "var(--rust)", fontWeight: 600 }}>Jurnal</Link>.
          Jika panel itu kosong, periksa jurnal yang bersangkutan bersama akuntan Anda.
        </div>
      )}

      {/* Inventory — always explained, so a difference never reads as an alarm. */}
      {isInventory && !failedResult && (
        <div style={{ background: "var(--paper-2)", borderRadius: 6, padding: 12, marginTop: 14, fontSize: 13 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Cara membaca angka Persediaan</div>
          Nilai stok di sini dihitung dari jumlah stok saat ini × harga beli terakhir (Last Cost). Buku Besar
          mencatat setiap pembelian dan pemakaian pada harga saat kejadian itu terjadi. Karena itu selisih bisa
          muncul secara wajar — terutama saat suku cadang dibeli ulang dengan harga yang berbeda dari stok yang
          masih ada. Selisih kecil bukan tanda ada yang salah. Selisih yang besar atau terus membesar tetap perlu
          dicek, misalnya lewat panel <b>Postingan Gagal</b> di halaman{" "}
          <Link href="/dashboard/accounting/journal" style={{ color: "var(--rust)", fontWeight: 600 }}>Jurnal</Link>{" "}
          atau dengan Stock Opname.
          {isPastDate && (
            <div style={{ marginTop: 8, color: "var(--steel)" }}>
              <b>Catatan tanggal:</b> nilai stok selalu memakai stok saat ini, bukan stok pada tanggal yang dipilih.
              Untuk tanggal yang sudah lewat, selisih Persediaan tidak bermakna — pilih tanggal hari ini untuk
              perbandingan yang sebenarnya.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ControlAccountsPage() {
  const [asOf, setAsOf] = useState(() => todayISO());
  const [results, setResults] = useState<ResultMap>({});
  const [loading, setLoading] = useState(true);

  // Guards against a slow, older response overwriting a newer one when the
  // date is changed quickly — only the most recently started check may
  // write to state.
  const latestRequest = useRef(0);

  const runChecks = useCallback(async (date: string) => {
    const requestId = ++latestRequest.current;
    setLoading(true);
    const settled = await Promise.all(
      RECONCILABLE_CONTROL_ACCOUNT_CODES.map(async (code) => ({
        code,
        result: await controlAccountReconciliationApi.check(code, date),
      })),
    );
    if (requestId !== latestRequest.current) return;
    const next: ResultMap = {};
    settled.forEach(({ code, result }) => { next[code] = result; });
    setResults(next);
    setLoading(false);
  }, []);

  useEffect(() => {
    runChecks(asOf);
  }, [asOf, runChecks]);

  const isPastDate = asOf !== "" && asOf < todayISO();

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
        <div>
          <h1 className="display" style={{ fontSize: 34 }}>Cek Akun Kontrol</h1>
          <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4, maxWidth: 620 }}>
            Bandingkan saldo Buku Besar setiap akun kontrol dengan sub-ledger-nya — daftar faktur atau stok.
            Halaman ini hanya membaca data; tidak mengubah jurnal apa pun.
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <div style={{ width: 170 }}>
            <div className="label">Per Tanggal</div>
            <input
              type="date" className="input" value={asOf}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)}
            />
          </div>
          <button onClick={() => runChecks(asOf)} disabled={loading} className="btn-ghost">
            <RefreshCw size={15} /> Periksa Ulang
          </button>
        </div>
      </div>

      <AccountingSubNav />

      {RECONCILABLE_CONTROL_ACCOUNT_CODES.map((code) => (
        <ControlAccountCard
          key={code}
          code={code}
          result={results[code]}
          loading={loading}
          isPastDate={isPastDate}
        />
      ))}
    </div>
  );
}
