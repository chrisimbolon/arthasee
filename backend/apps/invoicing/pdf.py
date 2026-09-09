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

8 Sep 2026 — real, three-part fix, found live against a printed PDF
compared directly to the real invoice-detail web page:
  1. org_address was never a parameter at all — the header showed
     only the shop name, never its address, even though the web page
     has always shown both.
  2. This module's own prior docstring claimed a single flat line-
     items table "matches invoice-detail's own existing print/screen
     view" — that claim was stale; the real page splits Parts and
     Jasa into their own sections with their own subtotals
     (InvoiceLineItem.kind already carries exactly this distinction,
     it just was never used here). Now mirrors that real split.
  3. The grand-total row only ever checked deposit_amount > 0 to
     decide between "Total" and "Sisa Tagihan" — completely blind to
     Invoice.total_paid (real Payment rows), the far more common real
     completion path (a customer paying cash on pickup, not a
     pre-service deposit). An invoice paid this way rendered as
     "Total Rp 0" — as if the whole job were worth nothing — instead
     of "Sisa Tagihan Rp 0" with a real "Sudah Dibayar" row, exactly
     what the web page has always shown. Now sums deposit_amount +
     total_paid into one real "Sudah Dibayar" figure, matching the
     web page's own presentation exactly, and picks "Sisa Tagihan"
     whenever any real amount has been paid, regardless of which
     mechanism paid it.

9 Sep 2026 — real, second-round fix, found against an actually
opened/printed PDF (not just its extracted text) compared directly
to the real invoice-detail page:
  4. Terbilang used to spell out invoice.balance_due — but this
     builder is ONLY ever invoked for a PAID invoice (see the view's
     own hard PAID-only gate), and Invoice.PAID is itself only ever
     reached via Payment.record() the moment balance_due reaches
     zero. That made terbilang read "Nol Rupiah" — Zero Rupiah — on
     every single real invoice this system will ever produce, not an
     edge case. Now spells out invoice.total instead, the real
     transacted amount, matching what a real Indonesian kwitansi
     actually shows (the amount received), and matching this
     module's own original, correct behavior before real payment
     tracking existed (back when balance_due and total were always
     the same figure for an unpaid invoice).
  5. The status badge (.status-badge, a <span> with background-color
     and padding) rendered visibly cramped in the real, opened PDF —
     text touching its own edges, no visible padding — while the
     identical markup renders as a clean pill on the web page. A
     genuine, documented xhtml2pdf limitation, not unique to this
     module: apps.estimates.pdf's own status badge uses the exact
     same <span>-in-<td> pattern with identical CSS, so this same
     rendering gap exists there too (flagged, not fixed here — out of
     this module's own scope). The first attempted fix (a table-cell-
     based badge) is itself superseded below by round three — see
     that entry for why.

9 Sep 2026 — real, third-round fix, found against an actually
printed PDF of the second-round fix itself:
  6. The table-based status badge (fix #5's own first attempt)
     rendered as a wide, solid block ("too brutal") rather than a
     compact pill — the table did not shrink to fit its own text
     content in xhtml2pdf the way a normal table would in a browser.
     Replaced entirely with the simplest, safest primitive already
     proven correct everywhere else in this exact file: a plain
     <div>, bold and colored, no background, no padding, no table. A
     printed document conveying status via bold colored text is a
     completely ordinary, real convention — not a downgrade from the
     web page's own pill badge, which has no such rendering
     constraint to work around.
  7. Real, excess vertical whitespace between org-name and org-
     address, and separately between the Pelanggan label and a long
     customer name — the same visual signature in two unrelated
     places, meaning a systemic gap rather than something local to
     any one element: nothing in this file's CSS ever explicitly
     zeroed default margin/padding on these divs, and xhtml2pdf does
     not reliably collapse margins the way a browser does. Every
     header/label/value element now sets margin and padding
     explicitly rather than relying on an assumed default — the same
     "verified, not assumed" discipline this module's own docstring
     has always claimed for its CSS.
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


def _line_item_rows(items):
    """
    Renders one <tr> per line item, or a single empty-state row when
    the list is genuinely empty — shared by both the Parts and Jasa
    sections below so neither one duplicates this markup.
    """
    if not items:
        return '<tr><td colspan="4" class="empty">Belum ada item.</td></tr>'
    rows_html = ""
    for li in items:
        rows_html += f"""
        <tr>
            <td>{li.description}</td>
            <td class="num">{li.quantity}</td>
            <td class="num">{_format_rupiah(li.unit_price)}</td>
            <td class="num">{_format_rupiah(li.subtotal)}</td>
        </tr>"""
    return rows_html


def _line_item_section(title, items):
    """
    One real section (Parts or Jasa) — its own header, its own line-
    item rows, its own subtotal, matching the real invoice-detail
    web page exactly (see this module's own updated docstring above
    for why this replaced the prior single flat table). Omitted
    entirely by the caller when a category has zero items — see
    build_invoice_pdf() below — rather than rendering an empty
    section with nothing under it.
    """
    section_total = sum((li.subtotal for li in items), Decimal("0"))
    return f"""
    <div class="section-title">{title}</div>
    <table class="line-table">
        <thead>
            <tr><th>Deskripsi</th><th class="num">Jml</th><th class="num">Harga Satuan</th><th class="num">Subtotal</th></tr>
        </thead>
        <tbody>{_line_item_rows(items)}</tbody>
    </table>
    <table class="section-subtotal-table">
        <tr><td class="num">Total {title}</td><td class="num total-value">{_format_rupiah(section_total)}</td></tr>
    </table>
    """


def build_invoice_pdf(invoice, org_name, org_address=""):
    """
    Returns raw PDF bytes. The caller (the view) is responsible for
    gating this to PAID invoices only and wrapping the result in an
    HttpResponse — this function itself stays a pure, independently
    testable builder, same discipline as build_quotation_pdf in
    apps.estimates.pdf.

    org_address is optional and blank-safe — an organization that
    hasn't filled in an address yet (still possible pre-onboarding-
    completion in principle) simply renders with no address line,
    rather than the caller needing to guard against None itself.

    Line items are now split into real Parts/Jasa sections (kind=
    "part"/"labor" on InvoiceLineItem), each with its own subtotal —
    matching the real invoice-detail web page exactly, not the flat
    single-table shape this module used before. A category with zero
    items is omitted entirely, not rendered as an empty section.
    """
    all_items = list(invoice.line_items.all())
    part_items = [li for li in all_items if li.kind == "part"]
    labor_items = [li for li in all_items if li.kind == "labor"]

    if not all_items:
        sections_html = '<table class="line-table"><tbody><tr><td colspan="4" class="empty">Belum ada item.</td></tr></tbody></table>'
    else:
        sections_html = ""
        if part_items:
            sections_html += _line_item_section("Parts", part_items)
        if labor_items:
            sections_html += _line_item_section("Jasa", labor_items)

    # 8 Sep 2026 — real fix: was `if invoice.deposit_amount > 0` only,
    # completely blind to invoice.total_paid (real Payment rows) —
    # see this module's own docstring above for the full reasoning.
    # paid_total is the ONE real figure the web page's own "Sudah
    # Dibayar" row shows — deposit and later cash/transfer payments
    # both count the same way toward "how much of this has actually
    # been paid," and are combined here exactly as the web page
    # already combines them.
    paid_total = invoice.deposit_amount + invoice.total_paid
    paid_row = ""
    if paid_total > 0:
        paid_row = f"""
        <tr><td class="num">Sudah Dibayar</td><td class="num">− {_format_rupiah(paid_total)}</td></tr>"""

    total_label = "Sisa Tagihan" if paid_total > 0 else "Total"
    # 9 Sep 2026 — real fix: was terbilang_rupiah(invoice.balance_due).
    # This builder only ever runs for a PAID invoice (balance_due is
    # therefore always 0 here — see this module's own updated
    # docstring above for the full reasoning), so that produced "Nol
    # Rupiah" on every real invoice this system ever generates. Spells
    # out the real transacted amount instead — what a real kwitansi
    # actually shows.
    terbilang_text = terbilang_rupiah(invoice.total)

    created_by_block = ""
    if invoice.created_by_id and invoice.created_by.full_name:
        created_by_block = f'<p class="created-by">Dibuat oleh {invoice.created_by.full_name}</p>'

    org_address_block = f'<div class="org-address">{org_address}</div>' if org_address else ""

    html = f"""
    <html>
    <head>
    <style>
        @page {{ size: A4; margin: 2.2cm; }}
        body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #17181a; }}
        .header-table {{ width: 100%; margin-bottom: 20px; }}
        .header-table td {{ vertical-align: top; }}
        .org-name {{ font-size: 16pt; font-weight: bold; margin: 0; padding: 0; }}
        .org-address {{ font-size: 9pt; color: #52514e; margin: 2px 0 0 0; padding: 0; }}
        .doc-title {{ font-size: 10pt; color: #6b6b6b; margin: 4px 0 0 0; padding: 0; }}
        .est-number {{ font-size: 12pt; font-weight: bold; text-align: right; }}
        .est-date {{ font-size: 9.5pt; color: #6b6b6b; text-align: right; margin-top: 2px; }}
        .status-badge {{ font-size: 11pt; font-weight: bold; text-align: right;
                         color: {STATUS_COLOR.get(invoice.status, "#6b6b6b")};
                         margin: 6px 0 0 0; padding: 0; }}
        .info-table {{ width: 100%; margin-bottom: 20px; border-bottom: 1px solid #d8d8d8; padding-bottom: 14px; }}
        .label {{ font-size: 8.5pt; color: #6b6b6b; text-transform: uppercase; margin: 0; padding: 0; }}
        .value {{ font-size: 11pt; font-weight: bold; margin: 2px 0 0 0; padding: 0; }}
        .section-title {{ font-size: 9pt; font-weight: bold; text-transform: uppercase;
                          color: #52514e; margin-top: 16px; margin-bottom: 6px; }}
        .line-table {{ width: 100%; border-collapse: collapse; margin-bottom: 4px; }}
        .line-table th {{ text-align: left; font-size: 8.5pt; text-transform: uppercase;
                          color: #6b6b6b; border-bottom: 1px solid #d8d8d8; padding: 4px 0; }}
        .line-table td {{ font-size: 10pt; padding: 5px 0; border-bottom: 1px solid #eeeeee; }}
        .num {{ text-align: right; }}
        .empty {{ text-align: center; color: #6b6b6b; padding: 10px 0; }}
        .section-subtotal-table {{ width: 100%; margin-bottom: 4px; }}
        .section-subtotal-table td {{ font-size: 9.5pt; padding: 3px 0; color: #52514e; }}
        .subtotal-table {{ width: 100%; margin-top: 10px; }}
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
                    {org_address_block}
                    <div class="doc-title">INVOICE</div>
                </td>
                <td style="width: 45%;">
                    <div class="est-number">{invoice.number}</div>
                    <div class="est-date">{_format_date_id(invoice.created_at)}</div>
                    <div class="status-badge">{STATUS_LABEL.get(invoice.status, invoice.status)}</div>
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

        {sections_html}

        <table class="subtotal-table">
            <tr><td class="num">Subtotal</td><td class="num total-value">{_format_rupiah(invoice.subtotal)}</td></tr>
            {paid_row}
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
