"use client";
// =============================================================================
// === frontend/app/dashboard/purchasing/supplier-reliability/page.tsx ===
// =============================================================================
import PurchasingSubNav from "@/components/purchasing/PurchasingSubNav";
import { purchasingReportsApi, SupplierReliabilityResponse } from "@/lib/api/purchasing";
import { Loader2 } from "lucide-react";
import { ChangeEvent, useEffect, useState } from "react";

function toNumber(value: string | number | null): number {
  if (value === null) return 0;
  return typeof value === "string" ? parseFloat(value) : value;
}

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(toNumber(value));
}

function onTimePillType(rate: string | number | null): string {
  if (rate === null) return "soon";
  const n = toNumber(rate);
  if (n >= 80) return "ok";
  if (n >= 50) return "soon";
  return "due";
}

export default function SupplierReliabilityPage() {
  const today = new Date().toISOString().slice(0, 10);
  const [since, setSince] = useState(`${new Date().getFullYear()}-01-01`);
  const [asOf, setAsOf] = useState(today);
  const [data, setData] = useState<SupplierReliabilityResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    purchasingReportsApi.supplierReliability(since, asOf).then((res) => { setData(res); setLoading(false); });
  }, [since, asOf]);

  return (
    <div>
      <div style={{ marginBottom: 4 }}>
        <h1 className="display" style={{ fontSize: 30, textTransform: "none" }}>Pembelian</h1>
        <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 4 }}>
          Ketepatan waktu pengiriman dan tingkat retur per supplier.
        </p>
      </div>

      <PurchasingSubNav />

      <div className="card">
        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          <div style={{ flex: 1 }}>
            <div className="label">Dari Tanggal</div>
            <input type="date" className="input" value={since} onChange={(e: ChangeEvent<HTMLInputElement>) => setSince(e.target.value)} />
          </div>
          <div style={{ flex: 1 }}>
            <div className="label">Sampai Tanggal</div>
            <input type="date" className="input" value={asOf} onChange={(e: ChangeEvent<HTMLInputElement>) => setAsOf(e.target.value)} />
          </div>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--steel)" }}>
            <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
          </div>
        ) : !data || data.suppliers.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", color: "var(--steel)" }}>
            Belum ada aktivitas supplier pada periode ini.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Ketepatan Waktu</th>
                <th>Tingkat Retur</th>
                <th>Nilai Diterima</th>
                <th>Nilai Diretur</th>
              </tr>
            </thead>
            <tbody>
              {data.suppliers.map((s) => (
                <tr key={s.supplier_id}>
                  <td style={{ fontWeight: 600 }}>{s.supplier_name}</td>
                  <td>
                    {s.on_time_rate === null ? (
                      <span style={{ color: "var(--steel-lt)", fontSize: 13 }}>Belum ada data</span>
                    ) : (
                      <>
                        <span className={`pill ${onTimePillType(s.on_time_rate)}`}>
                          {toNumber(s.on_time_rate).toFixed(0)}%
                        </span>
                        <span style={{ fontSize: 11.5, color: "var(--steel)", marginLeft: 6 }}>
                          ({s.on_time_pos}/{s.total_pos_judged} PO)
                        </span>
                      </>
                    )}
                  </td>
                  <td className="mono">{toNumber(s.return_rate).toFixed(1)}%</td>
                  <td className="mono">{formatRupiah(s.total_received_value)}</td>
                  <td className="mono">{formatRupiah(s.total_returned_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
