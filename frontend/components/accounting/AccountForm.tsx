"use client";
// =============================================================================
// === frontend/components/accounting/AccountForm.tsx ===
// =============================================================================
// 25 Sep 2026 — extracted from accounts/page.tsx (Roadmap: onboarding's
// new Langkah 1, "Sesuaikan / Tambah Akun") so OnboardingOverlay's own
// FoundationStep can reuse the exact same create form Daftar Akun already
// uses, instead of a second, parallel implementation that could drift from
// it. Genuinely the one real form, shared between create and edit, now
// shared between two pages too.
import {
  ACCOUNT_SUBTYPE_GROUPS, ACCOUNT_SUBTYPE_LABELS, AccountRow, accountsApi, AccountSubtype,
} from "@/lib/api/accounting";
import { useState } from "react";

// The real, merged row every caller of AccountForm needs — every field
// AccountRow already has, plus balance (from trialBalance() on Daftar
// Akun, matched by code; always null on onboarding's FoundationStep,
// since a brand-new shop genuinely has no trial-balance row yet for any
// account — both are honest, not a workaround).
export interface MergedAccountRow extends AccountRow {
  balance: string | number | null;
}

// Shared between the create panel and every edit panel so the fields/
// markup are never written twice. `code` is only ever shown/editable in
// create mode — see Account.apply_edit()'s own docstring (backend
// models.py) for why it's immutable after creation.
export interface AccountFormValues {
  code: string;
  name: string;
  description: string;
  is_active: boolean;
  account_subtype: AccountSubtype | "";
  is_contra: boolean;
  is_control_account: boolean;
  parent: string; // "" means top-level (null)
}

export function emptyFormValues(): AccountFormValues {
  return {
    code: "", name: "", description: "", is_active: true,
    account_subtype: "", is_contra: false, is_control_account: false, parent: "",
  };
}

export function formValuesFromAccount(a: AccountRow): AccountFormValues {
  return {
    code: a.code, name: a.name, description: a.description, is_active: a.is_active,
    account_subtype: a.account_subtype, is_contra: a.is_contra,
    is_control_account: a.is_control_account, parent: a.parent ?? "",
  };
}

// =============================================================================
// AccountForm — the one real form, shared between create and edit.
// =============================================================================
export default function AccountForm({
  mode, accountId, initial, lockClassification, allAccounts, excludeIdFromParentOptions,
  onCancel, onSaved,
}: {
  mode: "create" | "edit";
  accountId?: string;
  initial: AccountFormValues;
  lockClassification: boolean;
  allAccounts: MergedAccountRow[];
  excludeIdFromParentOptions: string | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<AccountFormValues>(initial);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parentOptions = allAccounts
    .filter((a) => a.id !== excludeIdFromParentOptions)
    .sort((a, b) => a.code.localeCompare(b.code));

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);

    if (mode === "create") {
      if (!values.account_subtype) {
        setError("Pilih Sub-Tipe Akun terlebih dahulu.");
        setSubmitting(false);
        return;
      }
      const result = await accountsApi.create({
        code: values.code,
        name: values.name,
        account_subtype: values.account_subtype,
        is_contra: values.is_contra,
        description: values.description,
        parent: values.parent || null,
      });
      setSubmitting(false);
      if (!result.success) {
        setError(result.message ?? "Gagal membuat akun.");
        return;
      }
      onSaved();
    } else {
      // Edit — genuinely partial. Only include account_subtype/
      // is_contra if NOT locked (has_posted_history); `parent` is
      // always included as either a real id or null (never
      // "untouched" from this form — the user always sees and can
      // change it, so there's no real "leave it alone" case here to
      // preserve, unlike a hypothetical bulk-edit tool).
      const payload: Parameters<typeof accountsApi.edit>[1] = {
        name: values.name,
        description: values.description,
        is_active: values.is_active,
        parent: values.parent || null,
      };
      if (!lockClassification) {
        if (values.account_subtype) payload.account_subtype = values.account_subtype;
        payload.is_contra = values.is_contra;
      }
      const result = await accountsApi.edit(accountId as string, payload);
      setSubmitting(false);
      if (!result.success) {
        setError(result.message ?? "Gagal mengubah akun.");
        return;
      }
      onSaved();
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 640 }}>
      {mode === "create" && (
        <div style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div className="label">Kode Akun</div>
            <input
              className="input" value={values.code}
              onChange={(e) => setValues({ ...values, code: e.target.value })}
              placeholder="mis. 1-10015"
            />
          </div>
          <div style={{ flex: 2 }}>
            <div className="label">Nama Akun</div>
            <input
              className="input" value={values.name}
              onChange={(e) => setValues({ ...values, name: e.target.value })}
              placeholder="mis. Kas Kecil Pluit"
            />
          </div>
        </div>
      )}

      {mode === "edit" && (
        <div>
          <div className="label">Nama Akun</div>
          <input
            className="input" value={values.name}
            onChange={(e) => setValues({ ...values, name: e.target.value })}
          />
        </div>
      )}

      <div>
        <div className="label">Sub-Tipe Akun</div>
        <select
          className="input" value={values.account_subtype} disabled={lockClassification}
          onChange={(e) => setValues({ ...values, account_subtype: e.target.value as AccountSubtype })}
        >
          <option value="">— Pilih sub-tipe —</option>
          {ACCOUNT_SUBTYPE_GROUPS.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.subtypes.map((st) => (
                <option key={st} value={st}>{ACCOUNT_SUBTYPE_LABELS[st]}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4 }}>
          Tipe Akun & Saldo Normal ditentukan otomatis dari sub-tipe ini.
        </div>
      </div>

      <div>
        <div className="label">Sub-Akun Dari (opsional)</div>
        <select
          className="input" value={values.parent}
          onChange={(e) => setValues({ ...values, parent: e.target.value })}
        >
          <option value="">— Tidak ada, akun utama —</option>
          {parentOptions.map((a) => (
            <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
          ))}
        </select>
      </div>

      <div>
        <div className="label">Deskripsi (opsional)</div>
        <input
          className="input" value={values.description}
          onChange={(e) => setValues({ ...values, description: e.target.value })}
        />
      </div>

      <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, opacity: lockClassification ? 0.5 : 1 }}>
          <input
            type="checkbox" checked={values.is_contra} disabled={lockClassification}
            onChange={(e) => setValues({ ...values, is_contra: e.target.checked })}
          />
          Akun Kontra
        </label>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            display: "inline-flex", alignItems: "center", padding: "2px 8px",
            borderRadius: 4, fontSize: 12, fontWeight: 600,
            background: values.is_control_account ? "var(--workshop-lt)" : "var(--paper-3)",
            color: values.is_control_account ? "var(--workshop)" : "var(--steel)",
          }}>
            {values.is_control_account ? "Akun Kontrol" : "Bukan Akun Kontrol"}
          </span>
          <span style={{ fontSize: 12, color: "var(--steel)" }}>
            — ditentukan otomatis dari Sub-Tipe Akun
          </span>
        </div>
        {mode === "edit" && (
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14 }}>
            <input
              type="checkbox" checked={values.is_active}
              onChange={(e) => setValues({ ...values, is_active: e.target.checked })}
            />
            Aktif
          </label>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--steel)" }}>
        Akun kontrol tidak bisa menerima entri jurnal manual — saldonya harus selalu sama
        dengan total sub-ledger terkait (mis. Piutang Usaha harus sama dengan total tagihan
        pelanggan yang belum lunas).
      </div>

      {error && (
        <div style={{ fontSize: 13, color: "var(--danger)" }}>{error}</div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={handleSubmit} disabled={submitting} className="btn-rust">
          {submitting ? "Menyimpan..." : mode === "create" ? "Buat Akun" : "Simpan Perubahan"}
        </button>
        <button onClick={onCancel} disabled={submitting} className="btn-ghost">
          Batal
        </button>
      </div>
    </div>
  );
}
