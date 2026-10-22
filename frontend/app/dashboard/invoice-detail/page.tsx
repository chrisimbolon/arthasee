"use client";
// =============================================================================
// === frontend/app/dashboard/invoice-detail/page.tsx ===
// Same query-param pattern as vehicle-detail — static export needs
// every route's HTML identical regardless of ?id= value, since real
// invoice UUIDs don't exist at build time.
//
// UPDATED — "Tandai Lunas" no longer PATCHes status directly. The
// backend now rejects that outright (Invoice.status can only ever
// become PAID by Payment.record() actually zeroing out balance_due —
// see apps.invoicing.views.InvoiceStatusUpdateView's own docstring).
// Replaced with a real payment-recording form hitting the new
// /api/invoices/<id>/payments/ endpoint, plus a payment history list
// — genuinely useful now that partial payments (a deposit, then a
// balance payment later) are a real, supported case, not just a
// single overwritable field.
// =============================================================================
import ReadinessBlockNotice from "@/components/readiness/ReadinessBlockNotice";
import JasaSearchInput, { priceLabel } from "@/components/service/JasaSearchInput";
import { Invoice, InvoiceStatus, invoicesApi } from "@/lib/api/invoicing";
import { organizationsApi } from "@/lib/api/organizations";
import { Payment, PaymentMethod, paymentsApi } from "@/lib/api/payments";
import { Part, ServiceItem, partsApi, serviceItemsApi } from "@/lib/api/service";
import { ReadinessBlockedError, readinessBlockFromError } from "@/lib/readiness";
import { ArrowLeft, Check, Download, Loader2, Pencil, Plus, Printer, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

const STATUS_LABEL: Record<InvoiceStatus, string> = {
  DRAFT: "Draf", ISSUED: "Diterbitkan", PARTIALLY_PAID: "Dibayar Sebagian", PAID: "Lunas", CANCELLED: "Dibatalkan",
};
const STATUS_COLOR: Record<InvoiceStatus, string> = {
  DRAFT: "var(--steel)", ISSUED: "var(--rust)", PARTIALLY_PAID: "var(--hazard-dark)", PAID: "#2e7d4f", CANCELLED: "var(--danger)",
};
// Mirrors backend/apps/payments/models.py's own METHOD_CHOICES
// exactly — keep in sync if that list ever changes.
const PAYMENT_METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: "Tunai", bank_transfer: "Transfer Bank", qris: "QRIS", card: "Kartu Debit/Kredit", other: "Lainnya",
};

function money(v: string | number) {
  return `Rp ${Number(v).toLocaleString("id-ID")}`;
}

// Chris's own ask, 5 Aug — Made's own handwritten meeting note,
// confirmed for Invoice only (not the Job Ticket, which deliberately
// shows zero prices anywhere). Mirrors backend/apps/invoicing/pdf.py's
// own terbilang_rupiah() exactly — same recursive algorithm, same
// output shape — so the on-screen Cetak view (window.print(), no
// backend PDF involved) and the actual downloaded PDF never
// disagree on what a given total spells out to.
const ONES = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"];

function terbilangWords(n: number): string {
  if (n < 12) return ONES[n];
  if (n < 20) return terbilangWords(n - 10) + " belas";
  if (n < 100) {
    const tens = Math.floor(n / 10), rest = n % 10;
    return terbilangWords(tens) + " puluh" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 200) {
    const rest = n - 100;
    return "seratus" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1000) {
    const hundreds = Math.floor(n / 100), rest = n % 100;
    return terbilangWords(hundreds) + " ratus" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 2000) {
    const rest = n - 1000;
    return "seribu" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1_000_000) {
    const thousands = Math.floor(n / 1000), rest = n % 1000;
    return terbilangWords(thousands) + " ribu" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1_000_000_000) {
    const millions = Math.floor(n / 1_000_000), rest = n % 1_000_000;
    return terbilangWords(millions) + " juta" + (rest ? " " + terbilangWords(rest) : "");
  }
  if (n < 1_000_000_000_000) {
    const billions = Math.floor(n / 1_000_000_000), rest = n % 1_000_000_000;
    return terbilangWords(billions) + " miliar" + (rest ? " " + terbilangWords(rest) : "");
  }
  const trillions = Math.floor(n / 1_000_000_000_000), rest = n % 1_000_000_000_000;
  return terbilangWords(trillions) + " triliun" + (rest ? " " + terbilangWords(rest) : "");
}

function terbilangRupiah(value: string | number): string {
  const n = Math.round(Number(value));
  if (n === 0) return "Nol Rupiah";
  const words = terbilangWords(n).split(" ").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  return `${words} Rupiah`;
}

// 22 Oct 2026 (Phase 21, Task C1) — Made's note, 12 Sep 2026: "Waktu invoice
// di posisi draft, masih bisa tambah & kurang barang / jasa." While the
// invoice is DRAFT, jasa lines can be added (with the same Daftar Jasa
// search box as the estimate, priced for this vehicle), edited and removed.
// Nothing is posted to the books until "Terbitkan Invoice" — the backend
// reads the lines at that moment. Parts are changed on the work order for
// now (Task C2 will add them here). Staff-only card: hidden when printing.
function DraftJasaEditor({ invoice, onUpdated }: { invoice: Invoice; onUpdated: () => void }) {
  const laborItems = invoice.line_items.filter((li) => li.kind === "labor");
  const [serviceItems, setServiceItems] = useState<ServiceItem[]>([]);
  const [vehicleClass, setVehicleClass] = useState("");
  const [desc, setDesc] = useState("");
  const [qty, setQty] = useState("1");
  const [price, setPrice] = useState("");
  const [picked, setPicked] = useState<ServiceItem | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [edit, setEdit] = useState({ description: "", quantity: "1", unit_price: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    serviceItemsApi.list({ vehicleId: invoice.vehicle_id })
      .then((res) => { setServiceItems(res.results); setVehicleClass(res.vehicle_class ?? ""); })
      .catch(() => setServiceItems([]));
  }, [invoice.vehicle_id]);

  const run = async (action: () => Promise<unknown>, fallback: string): Promise<boolean> => {
    setBusy(true); setError(null);
    try {
      await action();
      onUpdated();
      return true;
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(apiMessage || fallback);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const addLine = async () => {
    if (!desc.trim() || price === "") { setError("Isi nama jasa dan harganya."); return; }
    const ok = await run(
      () => invoicesApi.addLaborLine(invoice.id, { description: desc.trim(), quantity: Number(qty) || 1, unit_price: Number(price) }),
      "Gagal menambah jasa.",
    );
    if (ok) { setDesc(""); setQty("1"); setPrice(""); setPicked(null); }
  };

  const saveEdit = async (lineId: string) => {
    if (!edit.description.trim() || edit.unit_price === "") { setError("Isi nama jasa dan harganya."); return; }
    const ok = await run(
      () => invoicesApi.updateLaborLine(lineId, {
        description: edit.description.trim(), quantity: Number(edit.quantity) || 1, unit_price: Number(edit.unit_price),
      }),
      "Gagal menyimpan perubahan.",
    );
    if (ok) setEditingId(null);
  };

  const removeLine = async (lineId: string, description: string) => {
    if (!window.confirm(`Hapus jasa "${description}" dari invoice ini?`)) return;
    await run(() => invoicesApi.removeLaborLine(lineId), "Gagal menghapus jasa.");
  };

  const digitsOnly = (v: string) => v.replace(/[^0-9]/g, "");

  return (
    <div className="no-print card" style={{ maxWidth: 720, margin: "18px auto 0", padding: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Ubah Jasa (Draf)</h3>
      <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 14 }}>
        Selama invoice masih Draf, jasa bisa ditambah, diubah, atau dihapus. Setelah diterbitkan, invoice terkunci.
        Part diubah di kartu &quot;Ubah Part (Draf)&quot; di bawah.
      </p>
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
        {laborItems.length === 0 && <p style={{ color: "var(--steel)", fontSize: 13 }}>Belum ada jasa.</p>}
        {laborItems.map((li) => editingId === li.id ? (
          <div key={li.id} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input className="input" style={{ flex: 1, minWidth: 160 }} value={edit.description}
              onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
            <input className="input" style={{ width: 60 }} type="number" min={1} value={edit.quantity}
              onChange={(e) => setEdit({ ...edit, quantity: e.target.value })} />
            <input className="input mono" style={{ width: 120 }} inputMode="numeric" placeholder="Harga" value={edit.unit_price}
              onChange={(e) => setEdit({ ...edit, unit_price: digitsOnly(e.target.value) })} />
            <button className="btn-rust" style={{ fontSize: 12.5, padding: "6px 10px" }} disabled={busy} onClick={() => saveEdit(li.id)}>
              <Check size={13} />
            </button>
            <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 10px" }} disabled={busy} onClick={() => setEditingId(null)}>
              <X size={13} />
            </button>
          </div>
        ) : (
          <div key={li.id} className="mono" style={{ fontSize: 13, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <span>{li.description} × {Number(li.quantity)}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {money(li.subtotal)}
              <button title="Ubah" disabled={busy} style={{ background: "none", border: "none", display: "flex", color: "var(--steel)" }}
                onClick={() => {
                  setEditingId(li.id); setError(null);
                  setEdit({ description: li.description, quantity: String(Number(li.quantity)), unit_price: String(Math.round(Number(li.unit_price))) });
                }}>
                <Pencil size={14} />
              </button>
              <button title="Hapus" disabled={busy} style={{ background: "none", border: "none", display: "flex", color: "var(--steel)" }}
                onClick={() => removeLine(li.id, li.description)}>
                <Trash2 size={14} />
              </button>
            </span>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <JasaSearchInput
          style={{ flex: 1, minWidth: 180 }} placeholder="Tambah jasa — ketik, mis. Spooring"
          value={desc} items={serviceItems} showPrices vehicleClass={vehicleClass}
          onChange={(text) => { setDesc(text); if (picked && text !== picked.name) setPicked(null); }}
          onPick={(item) => {
            setDesc(item.name); setPicked(item);
            setPrice(String(Math.round(Number(item.price_for_vehicle ?? item.default_price))));
          }}
          onEnter={addLine}
        />
        <input className="input" style={{ width: 60 }} type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
        <input className="input mono" style={{ width: 120 }} inputMode="numeric" placeholder="Harga" value={price}
          onChange={(e) => setPrice(digitsOnly(e.target.value))} />
        <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} disabled={busy} onClick={addLine}>
          {busy ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={13} />} Tambah
        </button>
      </div>
      {picked && (
        <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>
          Dari Daftar Jasa: {priceLabel(picked, vehicleClass)} — harga boleh diubah.
        </div>
      )}
    </div>
  );
}

// 22 Oct 2026 (Phase 21, Task C2) — parts on a DRAFT invoice (Made's note,
// 12 Sep: "masih bisa tambah & kurang barang"). Unlike jasa, these move
// stock and post to the books right away (COGS <-> Inventory):
//   - Tambah: stock goes down, billed at the selling price (editable).
//   - Kembalikan ke stok: stock goes back, the cost is reversed. Since
//     23 Oct 2026 staff pick HOW MANY (e.g. 1 of 2 busi); the line shrinks,
//     or leaves the invoice when all of it goes back. Fluids: whole line only.
//   - Tidak ditagih: the part was used; the line stays at Rp 0 marked
//     "(tidak ditagih)" so the customer sees it was free. Nothing moves.
// Both posting actions can be stopped by the readiness gate; the shared
// notice explains why. Staff-only card: hidden when printing.
function DraftPartEditor({ invoice, onUpdated }: { invoice: Invoice; onUpdated: () => void }) {
  const partItems = invoice.line_items.filter((li) => li.kind === "part");
  const [catalog, setCatalog] = useState<Part[]>([]);
  const [partId, setPartId] = useState("");
  const [qty, setQty] = useState("1");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<ReadinessBlockedError | null>(null);

  // "How many?" row, shown under a line with more than one unit.
  const [pick, setPick] = useState<{ lineId: string; action: "return" | "not-charged"; max: number; qty: string } | null>(null);

  useEffect(() => { partsApi.list().then(setCatalog).catch(() => setCatalog([])); }, []);

  const isFluid = (partId: string | null) => catalog.find((p) => p.id === partId)?.item_type === "FLUID";

  const selected = catalog.find((p) => p.id === partId) ?? null;
  const selectedCost = selected && Number(selected.cost_price) > 0 ? Number(selected.cost_price) : null;

  const run = async (action: () => Promise<unknown>, fallback: string): Promise<boolean> => {
    setBusy(true); setError(null); setBlocked(null);
    try {
      await action();
      onUpdated();
      return true;
    } catch (err) {
      const gate = readinessBlockFromError(err, "Part belum dapat diubah.");
      if (gate) {
        setBlocked(gate);
      } else {
        const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
        setError(apiMessage || fallback);
      }
      return false;
    } finally {
      setBusy(false);
    }
  };

  const choosePart = (id: string) => {
    setPartId(id);
    const p = catalog.find((c) => c.id === id);
    setPrice(p ? String(Math.round(Number(p.unit_price))) : "");
  };

  const addPart = async () => {
    if (!partId || price === "") { setError("Pilih part dan isi harganya."); return; }
    const ok = await run(
      () => invoicesApi.addPartLine(invoice.id, { part: partId, quantity: Number(qty) || 1, unit_price: Number(price) }),
      "Gagal menambah part.",
    );
    if (ok) { setPartId(""); setQty("1"); setPrice(""); }
  };

  const returnWhole = async (lineId: string, description: string, quantity: number, fluid: boolean) => {
    const note = fluid ? "\n\nFluida hanya bisa dikembalikan seluruhnya." : "";
    if (!window.confirm(`Kembalikan "${description}" × ${quantity} ke stok?\n\nStok bertambah dan baris ini dihapus dari invoice.${note}`)) return;
    await run(() => invoicesApi.returnPartLine(lineId), "Gagal mengembalikan part.");
  };

  const notChargedWhole = async (lineId: string, description: string) => {
    if (!window.confirm(`Tandai "${description}" tidak ditagih?\n\nPart tetap tercatat terpakai, tampil di invoice dengan harga Rp 0.`)) return;
    await run(() => invoicesApi.markPartNotCharged(lineId), "Gagal mengubah part.");
  };

  // More than one unit (and, for returns, not a fluid): ask how many first.
  const startReturn = (lineId: string, description: string, quantity: number, partId: string | null) => {
    const fluid = isFluid(partId);
    if (quantity > 1 && !fluid) setPick({ lineId, action: "return", max: quantity, qty: String(quantity) });
    else returnWhole(lineId, description, quantity, fluid);
  };

  const startNotCharged = (lineId: string, description: string, quantity: number) => {
    if (quantity > 1) setPick({ lineId, action: "not-charged", max: quantity, qty: String(quantity) });
    else notChargedWhole(lineId, description);
  };

  const confirmPick = async () => {
    if (!pick) return;
    const n = Number(pick.qty);
    if (!(n > 0) || n > pick.max) { setError(`Jumlah harus antara 1 dan ${pick.max}.`); return; }
    const ok = pick.action === "return"
      ? await run(() => invoicesApi.returnPartLine(pick.lineId, n), "Gagal mengembalikan part.")
      : await run(() => invoicesApi.markPartNotCharged(pick.lineId, n), "Gagal mengubah part.");
    if (ok) setPick(null);
  };

  return (
    <div className="no-print card" style={{ maxWidth: 720, margin: "18px auto 0", padding: 20 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Ubah Part (Draf)</h3>
      <p style={{ fontSize: 12.5, color: "var(--steel)", marginBottom: 14 }}>
        Menambah atau mengembalikan part langsung mengubah stok dan pembukuan — bisa sebagian (mis. 1 dari 2 busi),
        kecuali fluida (oli, dll.) yang hanya bisa dikembalikan seluruhnya. &quot;Tidak ditagih&quot; = part
        dipakai tapi gratis untuk pelanggan (tampil Rp 0).
      </p>
      {blocked && <ReadinessBlockNotice blocked={blocked} />}
      {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
        {partItems.length === 0 && <p style={{ color: "var(--steel)", fontSize: 13 }}>Belum ada part.</p>}
        {partItems.map((li) => {
          const free = li.description.endsWith("(tidak ditagih)");
          const quantity = Number(li.quantity);
          const picking = pick?.lineId === li.id ? pick : null;
          return (
            <div key={li.id}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span className="mono" style={{ fontSize: 13 }}>{li.description} × {quantity}</span>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="mono" style={{ fontSize: 13 }}>{money(li.subtotal)}</span>
                <button className="btn-ghost" style={{ fontSize: 12, padding: "4px 8px" }} disabled={busy}
                  onClick={() => startReturn(li.id, li.description, quantity, li.part)}>
                  Kembalikan ke stok
                </button>
                {!free && (
                  <button className="btn-ghost" style={{ fontSize: 12, padding: "4px 8px" }} disabled={busy}
                    onClick={() => startNotCharged(li.id, li.description, quantity)}>
                    Tidak ditagih
                  </button>
                )}
              </span>
            </div>
            {picking && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6, padding: "8px 10px", background: "var(--paper, #f6f6f4)", borderRadius: 5, fontSize: 12.5 }}>
                <span>{picking.action === "return" ? "Berapa yang dikembalikan ke stok?" : "Berapa yang tidak ditagih?"}</span>
                <input className="input" style={{ width: 70 }} type="number" min={1} max={picking.max} step={1} value={picking.qty}
                  onChange={(e) => setPick({ ...picking, qty: e.target.value })} />
                <span style={{ color: "var(--steel)" }}>dari {picking.max}</span>
                <button className="btn-ghost" style={{ fontSize: 12, padding: "4px 10px" }} disabled={busy} onClick={confirmPick}>
                  {busy ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> : <Check size={12} />}
                  {picking.action === "return" ? " Kembalikan" : " Tandai gratis"}
                </button>
                <button className="btn-ghost" style={{ fontSize: 12, padding: "4px 10px" }} disabled={busy} onClick={() => setPick(null)}>
                  Batal
                </button>
              </div>
            )}
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select className="input" style={{ flex: 1, minWidth: 180 }} value={partId} onChange={(e) => choosePart(e.target.value)}>
          <option value="">— Tambah part —</option>
          {catalog.map((p) => <option key={p.id} value={p.id}>{p.name} ({Number(p.current_stock)} {p.unit})</option>)}
        </select>
        <input className="input" style={{ width: 60 }} type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
        <input className="input mono" style={{ width: 120 }} inputMode="numeric" placeholder="Harga" value={price}
          onChange={(e) => setPrice(e.target.value.replace(/[^0-9]/g, ""))} />
        <button className="btn-ghost" style={{ fontSize: 12.5, padding: "6px 12px" }} disabled={busy} onClick={addPart}>
          {busy ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Plus size={13} />} Tambah
        </button>
      </div>
      {selectedCost !== null && price !== "" && Number(price) <= selectedCost && (
        <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 6 }}>
          Harga di bawah atau sama dengan HPP ({money(selectedCost)}) — bengkel tidak akan untung dari part ini.
        </div>
      )}
    </div>
  );
}

function InvoiceDetailContent() {
  const searchParams = useSearchParams();
  const invoiceId = searchParams.get("id") ?? "";
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [orgName, setOrgName] = useState<string | null>(null);
  const [orgAddress, setOrgAddress] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 20 Sep 2026 — the readiness gate's own 409 for the two gated actions on this
  // page (issue an invoice; record a payment), shown with its real reason.
  const [blocked, setBlocked] = useState<ReadinessBlockedError | null>(null);
// 17 Sep 2026 -- real, deliberate split from `error` above: this is
  // never a failure state, and clearing on any new action (payment
  // resubmit, status change) keeps a stale success message from
  // lingering once the person has moved on to something else.
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const router = useRouter();

  // Payment-form state — kept separate from `updating` (used for
  // plain status transitions) since the two actions have genuinely
  // different in-flight UI (a form to fill in vs. a single button).
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("cash");
  const [paymentReference, setPaymentReference] = useState("");
  // 9 Oct 2026 — PPh 23 + PPh Final UMKM patch. Optional, only ever
  // shown/sent for an INSTITUTIONAL customer (see
  // showPph23WithheldField below) — a badan customer who withholds
  // PPh 23 directly at this payment and issues a Bukti Potong.
  const [pph23WithheldAmount, setPph23WithheldAmount] = useState("");
  const [submittingPayment, setSubmittingPayment] = useState(false);

  const load = () =>
    invoicesApi.get(invoiceId)
      .then((inv) => {
        setInvoice(inv);
        // Payment history is harmless to fetch regardless of status
        // (empty for DRAFT/a never-paid CANCELLED invoice) -- no
        // status check needed before calling this.
        return paymentsApi.list(inv.id)
          .then(setPayments)
          .catch(() => setPayments([]))
          .then(() => inv);
      })
      .finally(() => setLoading(false));
  useEffect(() => {
    if (invoiceId) load();
  }, [invoiceId]);
  useEffect(() => {
        organizationsApi.mine().then((res) => {
      if (res) { setOrgName(res.organization.name); setOrgAddress(res.organization.address); }
    });
  }, []);

  const changeStatus = async (status: InvoiceStatus) => {
    if (!invoice) return;
    setUpdating(true); setError(null); setBlocked(null);
    try {
      const updated = await invoicesApi.updateStatus(invoice.id, status);
      setInvoice(updated);
    } catch (err) {
      // 20 Sep 2026 — DRAFT -> ISSUED is a readiness-gated action (cancelling is
      // deliberately not). A gate 409 used to fall into the generic line below.
      const gate = readinessBlockFromError(err, "Invoice belum dapat diterbitkan.");
      if (gate) setBlocked(gate);
      else setError("Gagal mengubah status invoice.");
    } finally {
      setUpdating(false);
    }
  };

  // Defaults the amount field to the full remaining balance — one
  // click through this form (open, then Simpan with no changes)
  // reproduces the old one-click "Tandai Lunas" behavior for the
  // common full-payment case, while still allowing a real partial
  // amount when that's what actually happened.
  const openPaymentForm = () => {
    if (!invoice) return;
    setPaymentAmount(invoice.balance_due);
    setPaymentMethod("cash");
    setPaymentReference("");
    setPph23WithheldAmount("");
    setError(null);
    setBlocked(null);
    setShowPaymentForm(true);
  };

  // 9 Oct 2026 — PPh 23 + PPh Final UMKM patch, Decision #1: only
  // ever meaningful for a badan/INSTITUTIONAL customer who
  // withholds directly at payment and issues a Bukti Potong — an
  // INDIVIDUAL/OP customer never withholds at all (that case is
  // instead handled monthly, via the separate Setoran Pajak
  // Bulanan page's own self-remit gross-up).
  const showPph23WithheldField = invoice?.customer_type === "INSTITUTIONAL";

  const submitPayment = async () => {
    if (!invoice) return;
    setSubmittingPayment(true); setError(null); setSuccessMessage(null); setBlocked(null);
    try {
      // Captured before load() below overwrites paymentAmount's own
      // meaning-in-context -- this is "what was just paid," not
      // "what's currently typed in the form" (the form resets right
      // after).
      const amountJustPaid = paymentAmount;
      await paymentsApi.record(invoice.id, {
        amount: paymentAmount,
        method: paymentMethod,
        reference: paymentReference || undefined,
        // 9 Oct 2026 — PPh 23 + PPh Final UMKM patch. Only ever sent
        // when the field is actually shown and filled in — Payment.
        // record() itself treats an absent/zero value as "nothing
        // withheld," the correct default for every other customer.
        pph23_withheld_amount:
          showPph23WithheldField && pph23WithheldAmount ? pph23WithheldAmount : undefined,
      });
      setShowPaymentForm(false);
      const updated = await load(); // re-fetch -- status may now be PAID, and the new payment belongs in the history list

      // 17 Sep 2026 -- real, deliberate split, Chris's own confirmed
      // design: a partial payment keeps the person right here (still
      // real work to track on this same invoice -- Sisa Tagihan, more
      // installments to come), so it's just a message, inline. A
      // payment that brings the balance to zero is a genuinely
      // different, "this task is done" moment -- shown briefly, then
      // routed back to the invoice list, matching the list page's own
      // now-empty-of-this-task standing view. The short delay is
      // deliberate -- long enough to actually read the message before
      // the page moves out from under them, not a silent jump cut.
      if (Number(updated.balance_due) <= 0) {
        setSuccessMessage("Pembayaran lunas! Invoice telah diselesaikan.");
        setTimeout(() => router.push("/dashboard/invoices"), 1800);
      } else {
        setSuccessMessage(
          `Pembayaran sebesar ${money(amountJustPaid)} berhasil dicatat. Sisa tagihan: ${money(updated.balance_due)}.`
        );
      }
    } catch (err: any) {
      // Deliberate deviation from changeStatus()'s own generic
      // catch above -- Payment.record() returns real, specific,
      // actionable messages (overpayment amount, wrong invoice
      // status) that are genuinely more useful to show than a flat
      // "gagal" string here, unlike a plain status PATCH which never
      // had anything that specific to say.
      // 20 Sep 2026 — the gate's 409 carries only a generic summary sentence in
      // `message`; the specific reasons live in `blocks`. Show those, with any
      // real destination, instead of just the summary.
      const gate = readinessBlockFromError(err, "Pembayaran belum dapat dicatat.");
      if (gate) setBlocked(gate);
      else setError(err?.response?.data?.message ?? "Gagal mencatat pembayaran.");
    } finally {
      setSubmittingPayment(false);
    }
  };

  // Made's own ask, 31 Jul: a real PDF for LUNAS invoices so SA/
  // cashier can forward it themselves via WhatsApp. Backend hard-
  // gates to PAID only — this button is also only ever rendered when
  // invoice.status === "PAID" (see below), but the real enforcement
  // lives server-side, not here.
  const handleDownloadPdf = async () => {
    if (!invoice) return;
    setDownloadingPdf(true); setError(null);
    try {
      const blob = await invoicesApi.downloadPdf(invoice.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Invoice_${invoice.number.replace(/\//g, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Gagal mengunduh PDF.");
    } finally {
      setDownloadingPdf(false);
    }
  };

  if (!invoiceId) {
    return <div style={{ color: "var(--danger)" }}>Invoice tidak ditemukan — tidak ada ID yang diberikan.</div>;
  }
  if (loading || !invoice) {
    return <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>;
  }

  return (
    <div>
      {/* Print stylesheet, scoped inline since this page has no
          access to globals.css — hides everything outside the
          document itself (sidebar, back link, status controls) when
          actually printed/exported to PDF via the browser. */}
      <style>{`
        @media print {
          .no-print { display: none !important; }
          aside { display: none !important; }
          body, main { margin: 0 !important; padding: 0 !important; }
        }
      `}</style>

      <div className="no-print" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <Link href={`/dashboard/vehicle-detail?id=${invoice.vehicle_id}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13.5, color: "var(--steel)" }}>
          <ArrowLeft size={14} /> Kembali
        </Link>
        <div style={{ display: "flex", gap: 8 }}>
          {invoice.status === "PAID" && (
            <button className="btn-ghost" onClick={handleDownloadPdf} disabled={downloadingPdf}>
              {downloadingPdf ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={15} />}
              Download PDF
            </button>
          )}
          <button className="btn-rust" onClick={() => window.print()}>
            <Printer size={15} /> Cetak
          </button>
        </div>
      </div>

      {successMessage && <div className="no-print" style={{ background: "#e8f5ee", color: "#2e7d4f", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14, fontWeight: 600 }}>{successMessage}</div>}
      {blocked && <ReadinessBlockNotice blocked={blocked} />}
      {error && <div className="no-print" style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}

      <div className="card" style={{ maxWidth: 720, margin: "0 auto", padding: 40 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 28 }}>
          <div>
            <div className="display" style={{ fontSize: 22 }}>{orgName || "Arthasee"}</div>
            {orgAddress && (
              <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 2, maxWidth: 280, lineHeight: 1.4 }}>{orgAddress}</div>
            )}
            <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 6 }}>INVOICE</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{invoice.number}</div>
            <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 4 }}>
              {new Date(invoice.created_at).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" })}
            </div>
            <span style={{ display: "inline-block", marginTop: 8, fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: STATUS_COLOR[invoice.status] }}>
              {STATUS_LABEL[invoice.status]}
            </span>
            {/* 15 Sep 2026 -- is_overdue is a real, derived backend
                field (Invoice.is_overdue) -- only ever true when
                due_date is set, has passed, AND status is ISSUED or
                PARTIALLY_PAID. Rendered as its own, separate badge
                rather than folded into STATUS_COLOR/STATUS_LABEL --
                an invoice being overdue is a real, independent fact
                about it, not a competing status value; the two can
                and do co-occur (partially paid AND overdue at once). */}
            {invoice.is_overdue && (
              <span style={{ display: "inline-block", marginTop: 6, marginLeft: 6, fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: "#fff", background: "var(--danger)" }}>
                Telat Bayar
              </span>
            )}
            {invoice.due_date && (
              <div style={{ fontSize: 11.5, color: "var(--steel)", marginTop: 6 }}>
                Jatuh Tempo: {new Date(invoice.due_date).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" })}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 28, paddingBottom: 20, borderBottom: "1px solid var(--line)" }}>
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Pelanggan</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{invoice.customer_name_snapshot}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Nomor Plat</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 600 }}>{invoice.license_plate_snapshot}</div>
          </div>
          {/* Made's own explicit reason, 31 Jul: a specific mechanic
              must be identifiable on every invoice so he can go back
              and question that person directly if the same car has
              an issue again. Backend hard-blocks invoice creation
              without one, so this is never actually blank here on a
              real invoice. */}
          <div>
            <div style={{ fontSize: 11, color: "var(--steel)", textTransform: "uppercase" }}>Mekanik</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{invoice.mechanic_name_snapshot}</div>
          </div>
        </div>

        {/* 4 Sep 2026 — real fix: Invoice already had the exact same
            kind field ("part"/"labor") EstimateLineItem uses to split
            Parts/Jasa — this page just never read it, rendering every
            invoice as one flat list while its own source estimate
            showed the real, expected split. No backend change needed
            — invoicing/models.py's own InvoiceLineItem.kind was
            already there. */}
        {(() => {
          const partItems = invoice.line_items.filter((li) => li.kind === "part");
          const laborItems = invoice.line_items.filter((li) => li.kind === "labor");
          const partTotal = partItems.reduce((sum, li) => sum + Number(li.subtotal), 0);
          const laborTotal = laborItems.reduce((sum, li) => sum + Number(li.subtotal), 0);

          const renderTable = (items: typeof invoice.line_items) => (
            <table className="data-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Deskripsi</th>
                  <th style={{ textAlign: "right" }}>Jml</th>
                  <th style={{ textAlign: "right" }}>Harga Satuan</th>
                  <th style={{ textAlign: "right" }}>Subtotal</th>
                </tr>
              </thead>
              <tbody>
                {items.map((li) => (
                  <tr key={li.id}>
                    <td>{li.description}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{li.quantity}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{money(li.unit_price)}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{money(li.subtotal)}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={4} style={{ textAlign: "center", padding: 16, color: "var(--steel)" }}>Belum ada item.</td></tr>
                )}
              </tbody>
            </table>
          );

          return (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>Parts</div>
              {renderTable(partItems)}
              <div style={{ textAlign: "right", fontSize: 13, color: "var(--steel)", padding: "8px 0 20px" }}>
                Total Parts&nbsp;&nbsp;<span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>{money(partTotal)}</span>
              </div>

              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--steel)", textTransform: "uppercase", marginBottom: 8 }}>Jasa</div>
              {renderTable(laborItems)}
              <div style={{ textAlign: "right", fontSize: 13, color: "var(--steel)", padding: "8px 0" }}>
                Total Jasa&nbsp;&nbsp;<span className="mono" style={{ fontWeight: 700, color: "var(--ink)" }}>{money(laborTotal)}</span>
              </div>
            </div>
          );
        })()}

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <div style={{ width: 260 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 6 }}>
              <span style={{ color: "var(--steel)" }}>Subtotal</span>
              <span className="mono">{money(invoice.subtotal)}</span>
            </div>
            {Number(invoice.deposit_amount) > 0 && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 6 }}>
                <span style={{ color: "var(--steel)" }}>Deposit</span>
                <span className="mono">− {money(invoice.deposit_amount)}</span>
              </div>
            )}
            {/* New — mirrors the Deposit row above exactly, same
                reasoning: balance_due now also nets out real Payment
                rows, not just deposit_amount, so the total actually
                paid so far deserves the same visible line item. */}
            {payments.length > 0 && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 6 }}>
                <span style={{ color: "var(--steel)" }}>Sudah Dibayar</span>
                <span className="mono">− {money(payments.reduce((sum, p) => sum + Number(p.amount), 0))}</span>
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 17, fontWeight: 700, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
              <span>{Number(invoice.deposit_amount) > 0 || payments.length > 0 ? "Sisa Tagihan" : "Total"}</span>
              <span className="mono">{money(invoice.balance_due)}</span>
            </div>
            {/* Terbilang describes the SAME figure the row above
                shows — balance_due, not the pre-deposit subtotal.
                Spelling out a different number than what's printed
                as the bottom-line total would be a real, confusing
                inconsistency on a financial document. */}
            <div style={{ fontSize: 11.5, fontStyle: "italic", color: "var(--steel)", marginTop: 6, textAlign: "right" }}>
              Terbilang: {terbilangRupiah(invoice.balance_due)}
            </div>
          </div>
        </div>

        {/* Made's own handwritten note, 4 Aug meeting: "WO & Invoice:
            terbilang, diterima oleh" — Invoice needs the same
            sign-off block the WO's own paper form already has, for a
            real, physical customer signature. */}
        <div style={{ display: "flex", marginTop: 56 }}>
          <div style={{ width: 220 }}>
            <div style={{ height: 50 }} />
            <div style={{ borderTop: "1px solid var(--ink)", paddingTop: 4, fontSize: 12.5, color: "var(--steel)" }}>
              Diterima oleh
            </div>
          </div>
        </div>

        {invoice.created_by_name && (
          <p style={{ fontSize: 12, color: "var(--steel)", marginTop: 16, textAlign: "right" }}>
            Dibuat oleh {invoice.created_by_name}
          </p>
        )}
      </div>

      {/* Payment history — internal/staff-facing only (no-print), same
          reasoning as the status controls below: a customer's printed
          invoice stays exactly as clean as it already was, this is
          for Made/SA's own reference (e.g. "why does this say partially
          paid") right on the same screen they're already looking at. */}
      {payments.length > 0 && (
        <div className="no-print card" style={{ maxWidth: 720, margin: "18px auto 0", padding: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--steel)", textTransform: "uppercase" }}>
            Riwayat Pembayaran
          </div>
          {payments.map((p) => {
            // 10 Oct 2026 — PPh 23 + PPh Final UMKM patch, follow-up.
            // Pak Holan's own real ask, confirmed via WhatsApp: the
            // withheld amount needs to be visible on the payment
            // record itself, not just buried in the GL — so a
            // customer's finance team can reconcile it against the
            // physical Bukti Potong they hold. Only rendered when
            // actually > 0 — most payments never touch this at all.
            const withheld = Number(p.pph23_withheld_amount || 0);
            return (
              <div key={p.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 12, alignItems: "center", fontSize: 13 }}>
                  <span>
                    {PAYMENT_METHOD_LABEL[p.method]}
                    {p.reference && <span style={{ color: "var(--steel)" }}> — {p.reference}</span>}
                  </span>
                  <span className="mono" style={{ fontWeight: 600 }}>{money(p.amount)}</span>
                  <span style={{ color: "var(--steel)", fontSize: 11.5 }}>
                    {new Date(p.received_at).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}
                  </span>
                </div>
                {withheld > 0 && (
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--steel)", marginTop: 4 }}>
                    <span>PPh 23 Dipotong (Bukti Potong)</span>
                    <span className="mono">− {money(p.pph23_withheld_amount)}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Payment-recording form — replaces the old one-click "Tandai
          Lunas" PATCH, which the backend no longer accepts. Amount
          defaults to the full remaining balance (see openPaymentForm)
          so the common "pay it all off" case is still a two-click
          action (open, then Simpan), not a burdensome form fill. */}
      {showPaymentForm && (invoice.status === "ISSUED" || invoice.status === "PARTIALLY_PAID") && (
        <div className="no-print card" style={{ maxWidth: 720, margin: "18px auto 0", padding: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Catat Pembayaran</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Jumlah</label>
              <input
                type="number" className="mono" value={paymentAmount}
                onChange={(e) => setPaymentAmount(e.target.value)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 5, marginTop: 4, boxSizing: "border-box" }}
              />
              <div style={{ fontSize: 11, color: "var(--steel)", marginTop: 4 }}>
                Sisa tagihan saat ini: {money(invoice.balance_due)}
              </div>
            </div>
            <div>
              <label style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Metode</label>
              <select
                value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value as PaymentMethod)}
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 5, marginTop: 4, boxSizing: "border-box" }}
              >
                {Object.entries(PAYMENT_METHOD_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>Referensi (opsional)</label>
            <input
              type="text" value={paymentReference} onChange={(e) => setPaymentReference(e.target.value)}
              placeholder="No. transfer, ID transaksi QRIS, dll."
              style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 5, marginTop: 4, boxSizing: "border-box" }}
            />
          </div>
          {/* 9 Oct 2026 — PPh 23 + PPh Final UMKM patch, Decision #1: only
              ever shown for a badan/INSTITUTIONAL customer who withholds
              directly at this payment and issues a Bukti Potong. */}
          {showPph23WithheldField && (
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 11.5, color: "var(--steel)", textTransform: "uppercase" }}>
                PPh 23 Dipotong (opsional)
              </label>
              <input
                type="number" min={0} step="0.01" value={pph23WithheldAmount}
                onChange={(e) => setPph23WithheldAmount(e.target.value)}
                placeholder="0"
                style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 5, marginTop: 4, boxSizing: "border-box" }}
              />
              <div style={{ fontSize: 11, color: "var(--steel)", marginTop: 4 }}>
                Isi hanya jika pelanggan institusi memotong PPh 23 langsung dan menerbitkan Bukti Potong.
              </div>
            </div>
          )}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button className="btn-ghost" disabled={submittingPayment} onClick={() => setShowPaymentForm(false)}>Batal</button>
            <button
              className="btn-rust" disabled={submittingPayment || !paymentAmount || Number(paymentAmount) <= 0}
              onClick={submitPayment}
            >
              {submittingPayment && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
              Simpan Pembayaran
            </button>
          </div>
        </div>
      )}

      {invoice.status === "DRAFT" && <DraftJasaEditor invoice={invoice} onUpdated={load} />}
      {invoice.status === "DRAFT" && <DraftPartEditor invoice={invoice} onUpdated={load} />}

      <div className="no-print" style={{ maxWidth: 720, margin: "18px auto 0", display: "flex", gap: 10, justifyContent: "center" }}>
        {invoice.status === "DRAFT" && (
          <button className="btn-rust" disabled={updating} onClick={() => changeStatus("ISSUED")}>Terbitkan Invoice</button>
        )}
        {(invoice.status === "ISSUED" || invoice.status === "PARTIALLY_PAID") && !showPaymentForm && (
          <button className="btn-rust" disabled={updating} onClick={openPaymentForm}>Catat Pembayaran</button>
        )}
        {/* 15 Sep 2026 -- PARTIALLY_PAID joins this gate too, but a
            partially-paid invoice always has payments.length > 0 by
            definition (that's how it got there), so this button will
            always render disabled for it -- surfacing the real,
            known gap flagged during the backend design: a
            PARTIALLY_PAID invoice with payments can currently be
            cancelled through no real path (Refund.record() requires
            status=="PAID" exactly; this endpoint's own backend guard
            blocks CANCELLED whenever payments exist). Showing the
            disabled button with its own real, accurate title is more
            honest than hiding the whole capability -- it tells Made
            why, rather than making it look like cancellation was
            never a consideration for this status at all. */}
        {(invoice.status === "DRAFT" || invoice.status === "ISSUED" || invoice.status === "PARTIALLY_PAID") && (
          <button
            className="btn-ghost" disabled={updating || payments.length > 0}
            onClick={() => changeStatus("CANCELLED")}
            // Proactive disable, mirroring the same "backend is the
            // real enforcement, frontend just disables proactively"
            // split already established elsewhere in this app (see
            // WorkOrderJobTicketPdfView's own docstring) -- the
            // backend's own 409 guard on InvoiceStatusUpdateView is
            // what actually stops this, this is just the UI signal.
            title={payments.length > 0 ? "Invoice ini sudah memiliki pembayaran tercatat — tidak bisa dibatalkan langsung." : undefined}
          >
            Batalkan
          </button>
        )}
      </div>
    </div>
  );
}

export default function InvoiceDetailPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}>
        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…
      </div>
    }>
      <InvoiceDetailContent />
    </Suspense>
  );
}
