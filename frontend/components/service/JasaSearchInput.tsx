"use client";
// =============================================================================
// === frontend/components/service/JasaSearchInput.tsx ===
// =============================================================================
// 21 Oct 2026 (Phase 21, Task 21.4) — a text box that suggests Daftar Jasa
// items as you type (Chris, 21 Oct: typing "Ganti Oli" shows only the
// matching jasa). Matches anywhere in the name, ignoring capitals; ↑/↓ to
// move, Enter to pick, Esc to close. Not picking anything is fine: the typed
// text stays as a free-text jasa (agreed 21 Oct — one-off work is allowed).
//
// showPrices=false on the Work Order (Made, 12 Sep: "Di WO tidak boleh muncul
// harga!"), true on the Estimate, where each suggestion shows its price for
// this vehicle's class.
import type { ServiceItem } from "@/lib/api/service";
import { useMemo, useState } from "react";

const MAX_SUGGESTIONS = 8;

function formatRupiah(value: string | number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency", currency: "IDR", minimumFractionDigits: 0, maximumFractionDigits: 0,
  }).format(Number(value));
}

export function priceLabel(item: ServiceItem, vehicleClass: string): string {
  const price = item.price_for_vehicle ?? item.default_price;
  const source = item.price_source === "class" && vehicleClass ? vehicleClass : "default";
  return `${formatRupiah(price)} (${source})`;
}

export default function JasaSearchInput({
  value, onChange, onPick, onEnter, items, showPrices, vehicleClass = "", placeholder, style,
}: {
  value: string;
  onChange: (text: string) => void;
  onPick: (item: ServiceItem) => void;
  onEnter?: () => void;
  items: ServiceItem[];
  showPrices: boolean;
  vehicleClass?: string;
  placeholder?: string;
  style?: React.CSSProperties;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const query = value.trim().toLowerCase();

  const matches = useMemo(
    () => (query ? items.filter((i) => i.name.toLowerCase().includes(query)) : items).slice(0, MAX_SUGGESTIONS),
    [items, query],
  );

  const pick = (item: ServiceItem) => {
    onPick(item);
    setOpen(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && matches.length > 0) {
      e.preventDefault(); setOpen(true); setActive((a) => (a + 1) % matches.length);
    } else if (e.key === "ArrowUp" && matches.length > 0) {
      e.preventDefault(); setOpen(true); setActive((a) => (a - 1 + matches.length) % matches.length);
    } else if (e.key === "Enter") {
      if (open && matches[active]) {
        e.preventDefault(); pick(matches[active]);
      } else {
        onEnter?.();
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showList = open && items.length > 0 && (matches.length > 0 || query !== "");

  return (
    <div style={{ position: "relative", ...style }}>
      <input
        className="input" style={{ width: "100%" }} placeholder={placeholder} value={value}
        autoComplete="off" role="combobox" aria-expanded={showList} aria-autocomplete="list"
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={handleKeyDown}
      />
      {showList && (
        <div role="listbox" style={{
          position: "absolute", top: "100%", left: 0, right: 0, marginTop: 4, zIndex: 30,
          background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 6,
          boxShadow: "0 6px 18px rgba(23,24,26,0.12)", maxHeight: 280, overflowY: "auto",
        }}>
          {matches.length === 0 ? (
            <div style={{ padding: "8px 12px", fontSize: 12.5, color: "var(--steel)" }}>
              {showPrices
                ? "Tidak ada di Daftar Jasa — isi harga manual."
                : "Tidak ada di Daftar Jasa — tetap bisa ditambahkan."}
            </div>
          ) : matches.map((item, i) => (
            <div
              key={item.id} role="option" aria-selected={i === active}
              // mousedown, not click: fires before the input's blur closes the list.
              onMouseDown={(e) => { e.preventDefault(); pick(item); }}
              onMouseEnter={() => setActive(i)}
              style={{
                padding: "8px 12px", fontSize: 13, cursor: "pointer",
                display: "flex", justifyContent: "space-between", gap: 12,
                background: i === active ? "var(--paper-3)" : "transparent",
              }}
            >
              <span>{item.name}</span>
              {showPrices && (
                <span className="mono" style={{ color: "var(--steel)", whiteSpace: "nowrap" }}>
                  {priceLabel(item, vehicleClass)}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
