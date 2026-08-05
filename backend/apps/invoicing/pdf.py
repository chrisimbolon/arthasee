# =============================================================================
# === backend/apps/invoicing/pdf.py ===
# =============================================================================
"""
Arthasee — Invoice PDF

Made's own ask, 31 Jul: a real, downloadable PDF for LUNAS invoices,
matching the same manual-forward-via-WhatsApp pattern already built
for Estimate quotations — deliberately not automated sending, just a
file download. Confirmed with Chris: gated to PAID only, not
available for any other status.

Own module, mirrors apps.estimates.pdf's own structure and
constraints exactly — reused deliberately, not reinvented: xhtml2pdf
was already added as a dependency for the estimate PDF feature, so
this needed zero new installs. Same CSS 2.1-ish subset constraint
applies here too — table-based layout throughout, no flexbox, no CSS
grid, verified against xhtml2pdf's own documented limitations, not
assumed to "just work" the way a browser's print view does.

The Indonesian month lookup and Rupiah formatter are deliberately
duplicated here rather than imported from apps.estimates.pdf — same
reasoning already established when apps.estimates.pdf was built
separately from apps.contracts.exports: these are small, self-
contained utilities, and creating a cross-app import for something
this small isn't worth the coupling.

Terbilang + signature block added 5 Aug — Made's own handwritten
meeting note, confirmed with Chris to apply to Invoice ONLY (not the
Job Ticket, which deliberately shows zero prices anywhere): a spelled
-out Indonesian amount, and a "Diterima oleh" sign-off line for a
real, physical customer signature.
"""
from decimal import Decimal
from io import BytesIO

from xhtml2pdf import pisa

INDONESIAN_MONTHS = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

STATUS_LABEL = {
    "DRAFT": "Draf", "ISSUED": "Diterbitkan", "PAID": "Lunas", "CANCELLED": "Dibatalkan",
}
STATUS_COLOR = {
    "DRAFT": "#6b6b6b", "ISSUED": "#b5502f", "PAID": "#2e7d4f", "CANCELLED": "#c0392b",
}

# Chris's own reasoning, 5 Aug: a real recursive number-to-words
# converter, not a lookup table — an Indonesian invoice total can
# genuinely be anything, and a partial/approximate implementation
# would be worse than not having terbilang at all (a wrong spelled-
# out amount on a financial document is a real trust problem, not a
# cosmetic bug). Verified against real values, including this exact
# app's own Rp 740.000 example: "Tujuh Ratus Empat Puluh Ribu
# Rupiah" — matches standard Indonesian terbilang convention exactly
# (seribu not satu ribu, seratus not satu ratus, no trailing "nol"
# when a remainder is genuinely zero).
_ONES = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan",
         "sepuluh", "sebelas"]


def _terbilang_words(n):
    if n < 12:
        return _ONES[n]
    if n < 20:
        return _terbilang_words(n - 10) + " belas"
    if n < 100:
        tens, rest = divmod(n, 10)
        result = _terbilang_words(tens) + " puluh"
        if rest:
            result += " " + _terbilang_words(rest)
        return result
    if n < 200:
        rest = n - 100
        return "seratus" + (" " + _terbilang_words(rest) if rest else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        result = _terbilang_words(hundreds) + " ratus"
        if rest:
            result += " " + _terbilang_words(rest)
        return result
    if n < 2000:
        rest = n - 1000
        return "seribu" + (" " + _terbilang_words(rest) if rest else "")
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        result = _terbilang_words(thousands) + " ribu"
        if rest:
            result += " " + _terbilang_words(rest)
        return result
    if n < 1_000_000_000:
        millions, rest = divmod(n, 1_000_000)
        result = _terbilang_words(millions) + " juta"
        if rest:
            result += " " + _terbilang_words(rest)
        return result
    if n < 1_000_000_000_000:
        billions, rest = divmod(n, 1_000_000_000)
        result = _terbilang_words(billions) + " miliar"
        if rest:
            result += " " + _terbilang_words(rest)
        return result
    trillions, rest = divmod(n, 1_000_000_000_000)
    result = _terbilang_words(trillions) + " triliun"
    if rest:
        result += " " + _terbilang_words(rest)
    return result


def terbilang_rupiah(value):
    """
    Public entry point. Whole rupiah only — every amount in this app
    is already a whole number (see _format_rupiah's own int()
    conversion below), so no fractional/sen handling is needed.
    Capitalized per-word, matching the formal style used on real
    Indonesian financial documents ("Lima Ratus Empat Puluh Ribu
    Rupiah"), not lowercase running prose.
    """
    n = int(Decimal(value).to_integral_value())
    if n == 0:
        return "Nol Rupiah"
    words = " ".join(w.capitalize() for w in _terbilang_words(n).split())
    return f"{words} Rupiah"


def _format_date_id(dt):
    """Same dependency-free approach already proven in
    apps.estimates.pdf and apps.contracts.exports — deliberately not
    strftime("%B"), which depends on the server's OS-level locale
    actually having "id_ID" installed."""
    return f"{dt.day} {INDONESIAN_MONTHS[dt.month - 1]} {dt.year}"


def _format_rupiah(value):
    """Mirrors the frontend's own money() formatting exactly — Rp
    with period thousands-separators, no decimals shown."""
    whole = int(Decimal(value).to_integral_value())
    return f"Rp {whole:,}".replace(",", ".")


def build_invoice_pdf(invoice, org_name):
    """
    Returns raw PDF bytes. The caller (the view) is responsible for
    gating this to PAID invoices only and wrapping the result in an
    HttpResponse — this function itself stays a pure, independently
    testable builder, same discipline as build_quotation_pdf in
    apps.estimates.pdf.

    Deliberately ONE flat line-items table, not split into sections —
    matches how invoice-detail's own existing print/screen view
    already renders it (a single ordered list of charges), not the
    Parts/Jasa split used on the Estimate quotation. Introducing a
    split here that doesn't exist on the page this PDF is meant to
    mirror would be a real, avoidable inconsistency.
    """
    items = list(invoice.line_items.all())

    rows_html = ""
    if not items:
        rows_html = '<tr><td colspan="4" class="empty">Belum ada item.</td></tr>'
    else:
        for li in items:
            rows_html += f"""
            <tr>
                <td>{li.description}</td>
                <td class="num">{li.quantity}</td>
                <td class="num">{_format_rupiah(li.unit_price)}</td>
                <td class="num">{_format_rupiah(li.subtotal)}</td>
            </tr>"""

    # deposit_amount defaults to 0, never None — a plain ">" check is
    # enough, no need to also guard against a null value.
    deposit_row = ""
    if invoice.deposit_amount > 0:
        deposit_row = f"""
        <tr><td class="num">Deposit</td><td class="num">− {_format_rupiah(invoice.deposit_amount)}</td></tr>"""

    total_label = "Sisa Tagihan" if invoice.deposit_amount > 0 else "Total"
    # Terbilang describes the SAME figure total_label/the grand-total
    # row actually shows — balance_due, not the pre-deposit subtotal.
    # Spelling out a different number than what's printed as the
    # bottom-line total would be a real, confusing inconsistency on a
    # financial document, not a cosmetic mismatch.
    terbilang_text = terbilang_rupiah(invoice.balance_due)

    created_by_block = ""
    if invoice.created_by_id and invoice.created_by.full_name:
        created_by_block = f'<p class="created-by">Dibuat oleh {invoice.created_by.full_name}</p>'

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
                         background-color: {STATUS_COLOR.get(invoice.status, "#6b6b6b")};
                         padding: 3px 10px; text-align: center; }}
        .info-table {{ width: 100%; margin-bottom: 20px; border-bottom: 1px solid #d8d8d8; padding-bottom: 14px; }}
        .label {{ font-size: 8.5pt; color: #6b6b6b; text-transform: uppercase; }}
        .value {{ font-size: 11pt; font-weight: bold; margin-top: 2px; }}
        .line-table {{ width: 100%; border-collapse: collapse; margin-bottom: 4px; }}
        .line-table th {{ text-align: left; font-size: 8.5pt; text-transform: uppercase;
                          color: #6b6b6b; border-bottom: 1px solid #d8d8d8; padding: 4px 0; }}
        .line-table td {{ font-size: 10pt; padding: 5px 0; border-bottom: 1px solid #eeeeee; }}
        .num {{ text-align: right; }}
        .empty {{ text-align: center; color: #6b6b6b; padding: 10px 0; }}
        .subtotal-table {{ width: 100%; }}
        .subtotal-table td {{ font-size: 10pt; padding: 4px 0; }}
        .total-value {{ font-weight: bold; }}
        .grand-total-table {{ width: 100%; margin-top: 12px; border-top: 1px solid #17181a; padding-top: 10px; }}
        .grand-total-table td {{ font-size: 13pt; font-weight: bold; }}
        .terbilang {{ font-size: 9pt; font-style: italic; color: #52514e; margin-top: 6px; }}
        .signoff-table {{ width: 100%; margin-top: 44px; }}
        .signature-space {{ height: 50px; }}
        .signature-line {{ border-top: 1px solid #17181a; width: 200px; padding-top: 4px; }}
        .signature-label {{ font-size: 9pt; color: #52514e; }}
        .created-by {{ font-size: 8.5pt; color: #6b6b6b; text-align: right; margin-top: 10px; }}
    </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td style="width: 55%;">
                    <div class="org-name">{org_name}</div>
                    <div class="doc-title">INVOICE</div>
                </td>
                <td style="width: 45%;">
                    <div class="est-number">{invoice.number}</div>
                    <div class="est-date">{_format_date_id(invoice.created_at)}</div>
                    <table style="width: 100%; margin-top: 6px;"><tr><td>
                        <span class="status-badge">{STATUS_LABEL.get(invoice.status, invoice.status)}</span>
                    </td></tr></table>
                </td>
            </tr>
        </table>

        <table class="info-table">
            <tr>
                <td style="width: 34%;">
                    <div class="label">Pelanggan</div>
                    <div class="value">{invoice.customer_name_snapshot}</div>
                </td>
                <td style="width: 33%;">
                    <div class="label">Nomor Plat</div>
                    <div class="value">{invoice.license_plate_snapshot}</div>
                </td>
                <td style="width: 33%;">
                    <div class="label">Mekanik</div>
                    <div class="value">{invoice.mechanic_name_snapshot}</div>
                </td>
            </tr>
        </table>

        <table class="line-table">
            <thead>
                <tr><th>Deskripsi</th><th class="num">Jml</th><th class="num">Harga Satuan</th><th class="num">Subtotal</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>

        <table class="subtotal-table">
            <tr><td class="num">Subtotal</td><td class="num total-value">{_format_rupiah(invoice.subtotal)}</td></tr>
            {deposit_row}
        </table>

        <table class="grand-total-table">
            <tr><td>{total_label}</td><td class="num">{_format_rupiah(invoice.balance_due)}</td></tr>
        </table>
        <div class="terbilang">Terbilang: {terbilang_text}</div>

        <table class="signoff-table">
            <tr>
                <td style="width: 50%;">
                    <div class="signature-space"></div>
                    <div class="signature-line">Diterima oleh</div>
                </td>
                <td style="width: 50%;"></td>
            </tr>
        </table>

        {created_by_block}
    </body>
    </html>
    """

    buffer = BytesIO()
    pisa.CreatePDF(html, dest=buffer)
    return buffer.getvalue()
