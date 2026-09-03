# =============================================================================
# === backend/apps/estimates/pdf.py ===
# =============================================================================
"""
Arthasee — Estimate Quotation PDF

Made's own urgent ask, 30 Jul follow-up: SA/cashier need a real,
downloadable PDF of the quotation so they can forward it themselves
via their own WhatsApp — deliberately NOT the same thing as the
still-on-hold automated WhatsApp integration (B3 in the sprint
review). This is a plain file download; nothing here sends anything
anywhere automatically.

Own module, not stuffed into models.py or views.py — mirrors
apps.contracts.exports's own precedent directly: a document-building
function lives separately from the models it renders, and stays
independently testable (build the PDF, verify real bytes came back,
without needing the full request/response cycle).

xhtml2pdf chosen deliberately over WeasyPrint, per Chris's explicit
call: pure Python, no system-level dependencies (no Cairo/Pango
needed), matching the same "no new deployment risk" reasoning that
already drove picking openpyxl for the termin export. The real
tradeoff: xhtml2pdf only supports a CSS 2.1-ish subset — no flexbox,
no CSS grid. Every layout below uses plain HTML tables instead of
flex, on purpose, not as an oversight — this was verified against
xhtml2pdf's own documented constraints, not assumed to "just work"
the way the frontend's own flexbox-based print view does.

IMPORTANT — could not be tested end-to-end in the environment this
was written in (no network access to install xhtml2pdf and render a
real PDF). The HTML/CSS below deliberately stays inside xhtml2pdf's
well-documented, safe subset, but this genuinely needs a real local
render-and-open check before being trusted blind.

3 Sep 2026 — KM Saat Masuk added to the info table, matching the
frontend's own on-screen PrintableQuotation fix: estimate.
odometer_km_intake was already captured at intake (Chris's own
framing, 31 Jul: "estimasi is like a gate"), it just never made it
onto either rendering of the actual document a customer sees.
"""
from decimal import Decimal
from io import BytesIO

from xhtml2pdf import pisa

INDONESIAN_MONTHS = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

STATUS_LABEL = {
    "PENDING":  "Menunggu Persetujuan",
    "APPROVED": "Disetujui",
    "REJECTED": "Ditolak",
}
STATUS_COLOR = {
    "PENDING":  "#b5502f",
    "APPROVED": "#2e7d4f",
    "REJECTED": "#c0392b",
}


def _format_date_id(dt):
    """
    Same dependency-free approach already proven in
    apps.contracts.exports._format_date_id — deliberately not
    strftime("%B"), which depends on the server's OS-level locale
    actually having "id_ID" installed. A static lookup table can
    never silently produce the wrong language.
    """
    return f"{dt.day} {INDONESIAN_MONTHS[dt.month - 1]} {dt.year}"


def _format_rupiah(value):
    """Mirrors the frontend's own money() formatting exactly — Rp
    with period thousands-separators, no decimals shown."""
    whole = int(Decimal(value).to_integral_value())
    return f"Rp {whole:,}".replace(",", ".")


def _format_km(value):
    """
    Mirrors OdometerCard's own read-only display exactly — period
    thousands-separator, "km" suffix, and the same "—" fallback for
    an estimate whose intake reading was never recorded (e.g. one
    created before this field existed). value may be None, an int,
    or a Decimal depending on the caller — never assumed to be a
    specific numeric type.
    """
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", ".") + " km"


def _line_rows(items):
    if not items:
        return '<tr><td colspan="4" class="empty">Belum ada item.</td></tr>'
    rows = ""
    for li in items:
        rows += f"""
        <tr>
            <td>{li.description}</td>
            <td class="num">{li.quantity}</td>
            <td class="num">{_format_rupiah(li.unit_price)}</td>
            <td class="num">{_format_rupiah(li.subtotal)}</td>
        </tr>"""
    return rows


def _section_table(title, items):
    total = sum((li.subtotal for li in items), Decimal("0"))
    return f"""
    <div class="section-title">{title}</div>
    <table class="line-table">
        <thead>
            <tr><th>Deskripsi</th><th class="num">Jml</th><th class="num">Harga Satuan</th><th class="num">Subtotal</th></tr>
        </thead>
        <tbody>{_line_rows(items)}</tbody>
    </table>
    <table class="subtotal-table">
        <tr><td class="num">Total {title}</td><td class="num total-value">{_format_rupiah(total)}</td></tr>
    </table>
    """


def build_quotation_pdf(estimate, org_name):
    """
    Returns raw PDF bytes. The caller (the view) is responsible for
    wrapping this in an HttpResponse — kept a pure function so it
    stays testable on its own, same discipline as
    build_termin_report_workbook in apps.contracts.exports.
    """
    part_items = [li for li in estimate.line_items.all() if li.kind == "part"]
    labor_items = [li for li in estimate.line_items.all() if li.kind == "labor"]

    # Computed directly, not read from estimate.total — that field
    # doesn't exist on the model itself (checked precisely against
    # the real models.py, not assumed). Whatever the API's own
    # SerializerMethodField does to produce "total" for the frontend,
    # it isn't available on a raw model instance here — this mirrors
    # the same sum-of-subtotals logic EstimateLineItem.subtotal
    # already uses per line.
    grand_total = sum((li.subtotal for li in part_items + labor_items), Decimal("0"))

    diagnosis_block = ""
    if estimate.diagnosis_notes:
        diagnosis_block = f"""
        <div class="label">Catatan Diagnosa</div>
        <p class="diagnosis">{estimate.diagnosis_notes}</p>
        """

    created_by_block = ""
    if estimate.created_by_id and estimate.created_by.full_name:
        created_by_block = f'<p class="created-by">Dibuat oleh {estimate.created_by.full_name}</p>'

    html = f"""
    <html>
    <head>
    <style>
        @page {{ size: A4; margin: 2.2cm; }}
        body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #17181a; }}
        .header-table {{ width: 100%; margin-bottom: 20px; }}
        .header-table td {{ vertical-align: top; }}
        .org-name {{ font-size: 16pt; font-weight: bold; }}
        .doc-title {{ font-size: 10pt; color: #6b6b6b; margin-top: 2px; }}
        .est-number {{ font-size: 12pt; font-weight: bold; text-align: right; }}
        .est-date {{ font-size: 9.5pt; color: #6b6b6b; text-align: right; margin-top: 2px; }}
        .status-badge {{ font-size: 8.5pt; font-weight: bold; color: #ffffff;
                         background-color: {STATUS_COLOR.get(estimate.status, "#6b6b6b")};
                         padding: 3px 10px; text-align: center; }}
        .info-table {{ width: 100%; margin-bottom: 20px; border-bottom: 1px solid #d8d8d8; padding-bottom: 14px; }}
        .label {{ font-size: 8.5pt; color: #6b6b6b; text-transform: uppercase; }}
        .value {{ font-size: 12pt; font-weight: bold; margin-top: 2px; }}
        .diagnosis {{ font-size: 10pt; margin: 4px 0 18px 0; }}
        .section-title {{ font-size: 9.5pt; font-weight: bold; text-transform: uppercase;
                          color: #6b6b6b; margin: 14px 0 8px 0; }}
        .line-table {{ width: 100%; border-collapse: collapse; }}
        .line-table th {{ text-align: left; font-size: 8.5pt; text-transform: uppercase;
                          color: #6b6b6b; border-bottom: 1px solid #d8d8d8; padding: 4px 0; }}
        .line-table td {{ font-size: 10pt; padding: 5px 0; border-bottom: 1px solid #eeeeee; }}
        .num {{ text-align: right; }}
        .empty {{ text-align: center; color: #6b6b6b; padding: 10px 0; }}
        .subtotal-table {{ width: 100%; margin-bottom: 4px; }}
        .subtotal-table td {{ font-size: 10pt; padding: 4px 0; }}
        .total-value {{ font-weight: bold; }}
        .grand-total-table {{ width: 100%; margin-top: 16px; border-top: 1px solid #17181a; padding-top: 10px; }}
        .grand-total-table td {{ font-size: 13pt; font-weight: bold; }}
        .created-by {{ font-size: 8.5pt; color: #6b6b6b; text-align: right; margin-top: 26px; }}
    </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td style="width: 55%;">
                    <div class="org-name">{org_name}</div>
                    <div class="doc-title">QUOTATION / ESTIMASI</div>
                </td>
                <td style="width: 45%;">
                    <div class="est-number">EST #{estimate.number}</div>
                    <div class="est-date">{_format_date_id(estimate.created_at)}</div>
                    <table style="width: 100%; margin-top: 6px;"><tr><td>
                        <span class="status-badge">{STATUS_LABEL.get(estimate.status, estimate.status)}</span>
                    </td></tr></table>
                </td>
            </tr>
        </table>

        <table class="info-table">
            <tr>
                <td style="width: 34%;">
                    <div class="label">Pelanggan</div>
                    <div class="value">{estimate.vehicle.customer.name}</div>
                </td>
                <td style="width: 33%;">
                    <div class="label">Nomor Plat</div>
                    <div class="value">{estimate.vehicle.plate_number}</div>
                </td>
                <td style="width: 33%;">
                    <div class="label">KM Saat Masuk</div>
                    <div class="value">{_format_km(estimate.odometer_km_intake)}</div>
                </td>
            </tr>
        </table>

        {diagnosis_block}

        {_section_table("Parts", part_items)}
        {_section_table("Jasa", labor_items)}

        <table class="grand-total-table">
            <tr><td>Total</td><td class="num">{_format_rupiah(grand_total)}</td></tr>
        </table>

        {created_by_block}
    </body>
    </html>
    """

    buffer = BytesIO()
    pisa.CreatePDF(html, dest=buffer)
    return buffer.getvalue()
