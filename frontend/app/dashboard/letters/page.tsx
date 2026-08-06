"use client";
// =============================================================================
// === frontend/app/dashboard/letters/page.tsx ===
// =============================================================================
// D1 — Surat Masuk/Keluar. Made's own confirmed answer, 4 Aug meeting
// + 6 Aug phone call: outgoing letters get a real, auto-generated
// number; incoming letters get scanned/uploaded with real metadata,
// not a blind file drop. This page is the real "buku agenda surat"
// — the full archive, both directions. Letters auto-generated from
// Estimate approval / Contract fund requests also appear here,
// mixed with standalone ones, since they share one real number
// sequence — same as a physical logbook doesn't separate entries by
// how they came to exist.
import { Customer, customersApi, Vehicle, vehiclesApi } from "@/lib/api/service";
import {
  IncomingLetter, LETTER_SOURCE_LABEL, lettersApi, OutgoingLetter,
} from "@/lib/api/letters";
import { formatDateID } from "@/lib/format";
import { FileDown, Inbox, Loader2, Plus, Send } from "lucide-react";
import { useEffect, useState } from "react";

type Tab = "outgoing" | "incoming";

function CreateOutgoingLetterModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject]     = useState("");
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      await lettersApi.createOutgoing({ recipient, subject });
      onCreated();
    } catch (err) {
      const apiMessage = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      setError(apiMessage || "Gagal membuat surat.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div className="card" style={{ width: 480, background: "var(--paper-3)" }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Buat Surat Keluar</h2>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          Untuk keperluan umum di luar Work Order — nomor surat dibuat otomatis.
        </p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Kepada</label>
            <input className="input" required value={recipient} onChange={(e) => setRecipient(e.target.value)} placeholder="mis. Dinas Perhubungan Kota Batam" />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">Perihal</label>
            <input className="input" required value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="mis. Permohonan Izin Operasional" />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-rust" type="submit" disabled={saving}>
              {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Buat Surat"}
            </button>
            <button type="button" className="btn-ghost" onClick={onClose}>Batal</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function CreateIncomingLetterModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [vehicles, setVehicles]   = useState<Vehicle[]>([]);
  const [form, setForm] = useState({
    sender: "", subject: "",
    letter_date: new Date().toISOString().slice(0, 10),
    received_date: new Date().toISOString().slice(0, 10),
    customer: "", vehicle: "",
  });
  const [file, setFile]     = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  useEffect(() => {
    customersApi.list().then(setCustomers);
    vehiclesApi.list().then(setVehicles);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) { setError("Pilih file PDF atau gambar surat terlebih dahulu."); return; }
    setSaving(true); setError(null);
    const fd = new FormData();
    fd.append("sender", form.sender);
    fd.append("subject", form.subject);
    fd.append("letter_date", form.letter_date);
    fd.append("received_date", form.received_date);
    if (form.customer) fd.append("customer", form.customer);
    if (form.vehicle) fd.append("vehicle", form.vehicle);
    fd.append("file", file);
    try {
      await lettersApi.createIncoming(fd);
      onCreated();
    } catch (err) {
      // Real, honest error surfacing — e.g. the backend's own
      // "kendaraan bukan milik pelanggan yang dipilih" validation.
      const apiData = (err as { response?: { data?: Record<string, string[] | string> } })?.response?.data;
      const message = apiData
        ? Object.values(apiData).flat().join(", ")
        : "Gagal mengunggah surat.";
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(23,24,26,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, overflowY: "auto", padding: "40px 0" }}>
      <div className="card" style={{ width: 520, background: "var(--paper-3)" }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Tambah Surat Masuk</h2>
        <p style={{ fontSize: 13, color: "var(--steel)", marginBottom: 18 }}>
          Made&apos;s own ask — bukan sekadar tempat file, tetap bisa dicari.
        </p>
        {error && <div style={{ background: "var(--danger-light)", color: "var(--danger)", padding: "9px 12px", borderRadius: 5, fontSize: 13, marginBottom: 14 }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Pengirim</label>
            <input className="input" required value={form.sender} onChange={(e) => setForm({ ...form, sender: e.target.value })} placeholder="mis. Vendor Sparepart / Dinas Perhubungan" />
          </div>
          <div style={{ marginBottom: 14 }}>
            <label className="label">Perihal / Ringkasan</label>
            <input className="input" required value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Tanggal Surat</label>
              <input className="input" type="date" required value={form.letter_date} onChange={(e) => setForm({ ...form, letter_date: e.target.value })} />
            </div>
            <div>
              <label className="label">Tanggal Diterima</label>
              <input className="input" type="date" required value={form.received_date} onChange={(e) => setForm({ ...form, received_date: e.target.value })} />
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="label">Pelanggan Terkait <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <select className="input" value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })}>
                <option value="">— Tidak ada —</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Kendaraan Terkait <span style={{ textTransform: "none", fontWeight: 400 }}>(opsional)</span></label>
              <select className="input" value={form.vehicle} onChange={(e) => setForm({ ...form, vehicle: e.target.value })}>
                <option value="">— Tidak ada —</option>
                {vehicles.map((v) => <option key={v.id} value={v.id}>{v.plate_number}</option>)}
              </select>
            </div>
          </div>
          <div style={{ marginBottom: 20 }}>
            <label className="label">File (PDF/Gambar)</label>
            <input className="input" type="file" accept="application/pdf,image/*" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-rust" type="submit" disabled={saving}>
              {saving ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : "Simpan"}
            </button>
            <button type="button" className="btn-ghost" onClick={onClose}>Batal</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function LettersPage() {
  const [tab, setTab] = useState<Tab>("outgoing");
  const [outgoing, setOutgoing] = useState<OutgoingLetter[]>([]);
  const [incoming, setIncoming] = useState<IncomingLetter[]>([]);
  const [loading, setLoading]   = useState(true);
  const [showOutgoingModal, setShowOutgoingModal] = useState(false);
  const [showIncomingModal, setShowIncomingModal] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([lettersApi.listOutgoing(), lettersApi.listIncoming()])
      .then(([out, inc]) => { setOutgoing(out); setIncoming(inc); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  return (
    <div>
      <h1 className="display" style={{ fontSize: 26, marginBottom: 4, textTransform: "none" }}>Surat Masuk / Keluar</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginBottom: 22 }}>Arsip resmi korespondensi bengkel.</p>

      <div style={{ display: "flex", gap: 4, marginBottom: 18 }}>
        <button className={tab === "outgoing" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6 }} onClick={() => setTab("outgoing")}>
          <Send size={14} /> Surat Keluar {outgoing.length > 0 && `(${outgoing.length})`}
        </button>
        <button className={tab === "incoming" ? "btn-rust" : "btn-ghost"} style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6 }} onClick={() => setTab("incoming")}>
          <Inbox size={14} /> Surat Masuk {incoming.length > 0 && `(${incoming.length})`}
        </button>
      </div>

      {loading ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--steel)" }}><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Memuat…</div>
      ) : tab === "outgoing" ? (
        <>
          <div style={{ marginBottom: 14 }}>
            <button className="btn-rust" onClick={() => setShowOutgoingModal(true)}>
              <Plus size={16} /> Buat Surat
            </button>
          </div>
          {outgoing.length === 0 ? (
            <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 32 }}>Belum ada surat keluar.</div>
          ) : (
            <table className="data-table" style={{ width: "100%" }}>
              <thead><tr><th>Nomor</th><th>Kepada</th><th>Perihal</th><th>Sumber</th><th>Tanggal</th></tr></thead>
              <tbody>
                {outgoing.map((l) => (
                  <tr key={l.id}>
                    <td className="mono" style={{ fontWeight: 600 }}>{l.number}</td>
                    <td>{l.recipient}</td>
                    <td>{l.subject}</td>
                    <td style={{ fontSize: 12.5, color: "var(--steel)" }}>{LETTER_SOURCE_LABEL[l.source]}</td>
                    <td className="mono" style={{ fontSize: 12.5, color: "var(--steel)" }}>{formatDateID(l.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      ) : (
        <>
          <div style={{ marginBottom: 14 }}>
            <button className="btn-rust" onClick={() => setShowIncomingModal(true)}>
              <Plus size={16} /> Tambah Surat Masuk
            </button>
          </div>
          {incoming.length === 0 ? (
            <div className="card" style={{ textAlign: "center", color: "var(--steel)", padding: 32 }}>Belum ada surat masuk.</div>
          ) : (
            <table className="data-table" style={{ width: "100%" }}>
              <thead><tr><th>Pengirim</th><th>Perihal</th><th>Terkait</th><th>Tanggal Terima</th><th></th></tr></thead>
              <tbody>
                {incoming.map((l) => (
                  <tr key={l.id}>
                    <td>{l.sender}</td>
                    <td>{l.subject}</td>
                    <td style={{ fontSize: 12.5, color: "var(--steel)" }}>
                      {l.vehicle_plate || l.customer_name || "—"}
                    </td>
                    <td className="mono" style={{ fontSize: 12.5, color: "var(--steel)" }}>{formatDateID(l.received_date)}</td>
                    <td>
                      <a href={l.file} target="_blank" rel="noopener noreferrer" className="btn-ghost" style={{ fontSize: 11.5, padding: "4px 8px", display: "inline-flex", alignItems: "center", gap: 4 }}>
                        <FileDown size={12} /> Lihat
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {showOutgoingModal && (
        <CreateOutgoingLetterModal onClose={() => setShowOutgoingModal(false)} onCreated={() => { setShowOutgoingModal(false); load(); }} />
      )}
      {showIncomingModal && (
        <CreateIncomingLetterModal onClose={() => setShowIncomingModal(false)} onCreated={() => { setShowIncomingModal(false); load(); }} />
      )}
    </div>
  );
}
