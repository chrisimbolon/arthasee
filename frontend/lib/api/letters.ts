// =============================================================================
// === frontend/lib/api/letters.ts ===
// =============================================================================
// D1 — Surat Masuk/Keluar. Made's own confirmed answer, 4 Aug meeting
// + 6 Aug phone call. OutgoingLetter numbers auto-generate on the
// backend (never client-provided) — see
// backend/apps/letters/models.py's own OutgoingLetter.save().
import api from "@/lib/api";

export type LetterSource = "ESTIMATE_APPROVAL" | "CONTRACT_FUNDS_REQUEST" | "STANDALONE";

export const LETTER_SOURCE_LABEL: Record<LetterSource, string> = {
  ESTIMATE_APPROVAL: "Persetujuan Estimasi",
  CONTRACT_FUNDS_REQUEST: "Permohonan Dana Kontrak",
  STANDALONE: "Surat Mandiri",
};

export interface OutgoingLetter {
  id:         string;
  number:     string;
  recipient:  string;
  subject:    string;
  source:     LetterSource;
  created_at: string;
}

export interface IncomingLetter {
  id:            string;
  sender:        string;
  subject:       string;
  letter_date:   string;
  received_date: string;
  file:          string;
  customer:      string | null;
  customer_name: string | null;
  vehicle:       string | null;
  vehicle_plate: string | null;
  created_at:    string;
}

export const lettersApi = {
  async listOutgoing(): Promise<OutgoingLetter[]> {
    const { data } = await api.get("/api/letters/outgoing/");
    return data.letters;
  },
  // recipient/subject only — number/source are always server-side,
  // matching backend/apps/letters/serializers.py's own
  // OutgoingLetterCreateSerializer (deliberately narrower than the
  // read serializer).
  async createOutgoing(payload: { recipient: string; subject: string }): Promise<OutgoingLetter> {
    const { data } = await api.post("/api/letters/outgoing/", payload);
    return data.letter;
  },
  // Optional vehicleId — vehicle-detail uses this to fetch only its
  // own linked letters, not the whole org's incoming mail filtered
  // client-side (see the backend's own ?vehicle= query param).
  async listIncoming(vehicleId?: string): Promise<IncomingLetter[]> {
    const { data } = await api.get("/api/letters/incoming/", {
      params: vehicleId ? { vehicle: vehicleId } : undefined,
    });
    return data.letters;
  },
  // multipart/form-data — a real file upload, not JSON. Caller
  // builds the FormData itself (file + sender/subject/dates +
  // optional customer/vehicle), matching how file-upload endpoints
  // are already handled elsewhere in this app (e.g. contract import).
  async createIncoming(formData: FormData): Promise<IncomingLetter> {
    const { data } = await api.post("/api/letters/incoming/", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data.letter;
  },
};
