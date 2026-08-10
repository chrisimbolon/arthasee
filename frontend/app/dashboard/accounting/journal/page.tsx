"use client";
// =============================================================================
// === frontend/app/dashboard/accounting/journal/page.tsx ===
// =============================================================================
import AccountingSubNav from "@/components/accounting/AccountingSubNav";
import {
  accountingApi, FailedPosting, JournalEntryRow, JournalSource,
} from "@/lib/api/accounting";
import { ChevronDown, ChevronRight, Loader2, Plus, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { ChangeEvent, Fragment, useEffect, useState } from "react";


function toNumber(value: string | number): number {
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", maximumFractionDigits: 0,
  }).format(toNumber(value));
}

type SourceFilter = "ALL" | JournalSource;

const SOURCE_TABS: { id: SourceFilter; label: string }[] = [
  { id: "ALL", label: "Semua" },
  { id: "DOMAIN_EVENT", label: "Otomatis" },
  { id: "MANUAL", label: "Manual" },
];

function JournalEntriesTable({
  entries, expanded, onToggle,
}: {
  entries: JournalEntryRow[];
  expanded: Set<string>;
  onToggle: (id: string) => void;
}) {
  if (entries.length === 0) {
    return (
      <div style={{ textAlign: "center", color: "var(--steel-lt)", fontSize: 13, padding: 24 }}>
        Tidak ada entri jurnal untuk filter ini.
      </div>
    );
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th></th><th>No. Entri</th><th>Tanggal</th>
          <th>Sumber</th><th>Tipe Event</th><th>Memo</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <Fragment key={e.id}>
            <tr onClick={() => onToggle(e.id)} style={{ cursor: "pointer" }}>
              <td>{expanded.has(e.id) ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
              <td className="mono">{e.entry_number}</td>
              <td>{e.posting_date}</td>
              <td style={{ fontSize: 13 }}>{e.source === "MANUAL" ? "Manual" : "Otomatis"}</td>
              <td style={{ fontSize: 13, color: "var(--steel)" }}>{e.event_type || "—"}</td>
              <td style={{ fontSize: 13, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {e.memo}
              </td>
            </tr>
            {expanded.has(e.id) && (
              <tr>
                <td colSpan={6} style={{ background: "var(--paper)", padding: "12px 14px 12px 40px" }}>
                  <table style={{ width: "100%", fontSize: 13 }}>
                    <thead>
                      <tr style={{ color: "var(--steel)" }}>
                        <th style={{ textAlign: "left", fontWeight: 600, padding: "4px 8px" }}>Kode</th>
                        <th style={{ textAlign: "left", fontWeight: 600, padding: "4px 8px" }}>Akun</th>
                        <th style={{ textAlign: "right", fontWeight: 600, padding: "4px 8px" }}>Debit</th>
                        <th style={{ textAlign: "right", fontWeight: 600, padding: "4px 8px" }}>Kredit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {e.lines.map((l) => (
                        <tr key={l.id}>
                          <td className="mono" style={{ padding: "4px 8px" }}>{l.account_code}</td>
                          <td style={{ padding: "4px 8px" }}>{l.account_name}</td>
                          <td className="mono" style={{ textAlign: "right", padding: "4px 8px" }}>
                            {toNumber(l.debit_amount) > 0 ? formatRupiah(l.debit_amount) : ""}
                          </td>
                          <td className="mono" style={{ textAlign: "right", padding: "4px 8px" }}>
                            {toNumber(l.credit_amount) > 0 ? formatRupiah(l.credit_amount) : ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {e.created_by_name && (
                    <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 8 }}>
                      Dibuat oleh {e.created_by_name}
                    </div>
                  )}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function FailedPostingsPanel({ failures }: { failures: FailedPosting[] }) {
  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <TriangleAlert size={16} color="var(--danger)" />
        <div className="label" style={{ marginBottom: 0 }}>Postingan Gagal</div>
      </div>
      {failures.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--workshop)", padding: "8px 0" }}>
          Tidak ada postingan yang gagal — semua event berhasil diproses.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {failures.map((f) => (
            <div key={f.id} style={{ background: "var(--danger-light)", borderRadius: 6, padding: "10px 14px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, fontWeight: 600, gap: 12 }}>
                <span>{f.event_type}</span>
                <span style={{ color: "var(--steel)", fontWeight: 500, flexShrink: 0 }}>
                  {new Date(f.occurred_at).toLocaleString("id-ID")}
                </span>
              </div>
              <div style={{ fontSize: 12.5, color: "var(--danger)", marginTop: 4 }}>{f.last_error}</div>
              <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 4 }}>Percobaan: {f.attempts}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function JournalPage() {
  const [source, setSource] = useState<SourceFilter>("ALL");
  const [since, setSince] = useState(`${new Date().getFullYear()}-01-01`);
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [entries, setEntries] = useState<JournalEntryRow[] | null>(null);
  const [failures, setFailures] = useState<FailedPosting[] | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      accountingApi.journalEntries({ source: source === "ALL" ? undefined : source, since, asOf }),
      accountingApi.failedPostings({ since, asOf }),
    ]).then(([e, f]) => {
      setEntries(e);
      setFailures(f);
      setLoading(false);
    });
  }, [source, since, asOf]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <h1 className="display" style={{ fontSize: 34 }}>Jurnal &amp; Audit Log</h1>
          <div style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
            Setiap entri jurnal yang sudah diposting, dan postingan yang gagal — langsung dari Outbox.
          </div>
        </div>
        <Link
          href="/dashboard/accounting/manual-journal"
          className="btn-rust"
          style={{ display: "inline-flex", alignItems: "center", gap: 7, textDecoration: "none", flexShrink: 0 }}
        >
          <Plus size={15} /> Jurnal Manual
        </Link>
      </div>

      <AccountingSubNav />

      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 10 }}>
          {SOURCE_TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setSource(t.id)}
              className={source === t.id ? "btn-rust" : "btn-ghost"}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <div>
            <div className="label">Dari</div>
            <input
              type="date" className="input" value={since}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setSince(e.target.value)}
            />
          </div>
          <div>
            <div className="label">Sampai</div>
            <input
              type="date" className="input" value={asOf}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)}
            />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 60, color: "var(--steel)" }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div className="card">
            <JournalEntriesTable entries={entries ?? []} expanded={expanded} onToggle={toggle} />
          </div>
          <FailedPostingsPanel failures={failures ?? []} />
        </div>
      )}
    </div>
  );
}
