# =============================================================================
# === backend/apps/workorders/pdf.py ===
# =============================================================================
"""
Arthasee — Work Order Job Ticket PDF

Made's own real paper form (Arya Motor's existing "WO" ticket,
WO NO 1452 photographed 1 Aug) — an internal shop-floor job ticket
for the mechanic, not a customer-facing document. Three things
confirmed directly with Made before writing any of this, each of
which shapes the layout below:

  1. Purpose: internal, mechanic-facing — never shown to a customer.
  2. Pricing: NONE anywhere on this document, not just "no grand
     total" — no unit prices, no subtotals, nothing Rp at all,
     anywhere. This matters concretely: EstimateLineItem labor lines
     approved into a WorkOrderJobLine have their price folded
     straight into the description text itself (see
     Estimate.approve() in apps.estimates.models — e.g. "Setel Rem
     (estimasi Rp 200.000)"). That suffix is stripped here before
     printing — see _strip_price_suffix() below — or it would leak
     straight onto the one document Made explicitly said must have
     none.
  3. Timing: created/printed the moment "Mulai Dikerjakan" is
     clicked — i.e. only once work_started_at is actually set. The
     view enforces this as a real 409, not just a frontend-hidden
     button; this module itself doesn't care and will happily render
     a ticket with no date if handed a WorkOrder with no
     work_started_at, since gating access is the view's job, not
     this one's.

Reuses xhtml2pdf, matching apps.estimates.pdf's own explicit choice
(pure Python, no system-level Cairo/Pango dependency) — same
plain-HTML-table-only layout discipline for the same reason: no
flexbox/grid support in xhtml2pdf's CSS 2.1-ish subset.

One real, flagged judgment call — the physical paper form has a
single "Satuan" column for materials, not separate Qty + Satuan
columns. A bare unit ("Liter") with no quantity tells a mechanic
nothing useful, so quantity and unit are combined into that one
column here (e.g. "4 Liter") — the natural way a person would fill
that same blank cell by hand. This is an interpretation, not
something Made stated in exactly these words; easy to change in one
place (_material_rows below) if it's wrong.

Nama/Fungsi/Alamat: v1 deliberately ships with Nama only (from
vehicle.customer.name, already available everywhere else in this
codebase) — Fungsi and Alamat don't exist as real fields on Customer
or Vehicle yet, and Chris's own explicit call was not to add them
now. Known v1 gap, not an oversight — see the roadmap.

IMPORTANT — same honest caveat as estimates/pdf.py: could not be
rendered end-to-end in the environment this was written in (no
network access to install xhtml2pdf). Stays inside the same
well-documented safe subset already proven for the quotation PDF,
but still genuinely needs one real local render-and-open check.
"""
import re
from io import BytesIO

from xhtml2pdf import pisa

INDONESIAN_MONTHS = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

STATUS_LABEL = {
    "OPEN": "Terbuka", "IN_PROGRESS": "Dikerjakan", "QC": "Pemeriksaan Kualitas",
    "DONE": "Selesai", "CANCELLED": "Dibatalkan",
}
STATUS_COLOR = {
    "OPEN": "#4a6d94", "IN_PROGRESS": "#b5502f", "QC": "#b5860b",
    "DONE": "#2e7d4f", "CANCELLED": "#c0392b",
}

# Matches the exact suffix Estimate.approve() appends to a labor
# line's description — "(estimasi Rp 200.000)", "(estimasi Rp
# 1.500.000)", etc. Matched loosely on the "(estimasi Rp ...)" shape
# rather than hardcoding a specific number format, so it still
# strips correctly even if that formatting ever changes slightly.
_PRICE_SUFFIX_RE = re.compile(r"\s*\(estimasi\s+Rp[^)]*\)\s*$", re.IGNORECASE)


def _strip_price_suffix(description):
    return _PRICE_SUFFIX_RE.sub("", description).strip()


def _format_date_id(dt):
    """Same dependency-free lookup already proven in
    apps.estimates.pdf._format_date_id and apps.contracts.exports —
    never strftime("%B"), which depends on server locale."""
    return f"{dt.day} {INDONESIAN_MONTHS[dt.month - 1]} {dt.year}"


def _job_description_rows(job_lines):
    """
    Numbered 1..N, matching the paper form's own "NO." column
    exactly. Deliberately no is_done/checkbox rendering — that state
    is genuinely still in flux while a job is IN_PROGRESS (the whole
    point of printing this at the moment work starts, not after), so
    baking today's checkbox state into a printed page would just go
    stale within the hour.
    """
    if not job_lines:
        return '<tr><td class="num">1</td><td class="empty">Belum ada item.</td></tr>'
    rows = ""
    for i, line in enumerate(job_lines, start=1):
        rows += f"""
        <tr>
            <td class="num">{i}</td>
            <td>{_strip_price_suffix(line.description)}</td>
        </tr>"""
    return rows


def _material_rows(material_lines):
    """
    See this module's own docstring for the "single Satuan column,
    quantity folded in" judgment call. Deliberately renders NEITHER
    unit_price_at_time NOR subtotal, even though both exist on the
    model and are exposed by WorkOrderMaterialLineSerializer — Made's
    own explicit rule ("no prices anywhere on this document") applies
    here specifically, not just to the job-description side.
    """
    if not material_lines:
        return '<tr><td class="num">1</td><td class="empty" colspan="2">Belum ada material.</td></tr>'
    rows = ""
    for i, line in enumerate(material_lines, start=1):
        # quantity is a Decimal on the model — trimmed to a plain
        # integer display when it has no real fractional part (e.g.
        # "4" not "4.00"), matching how a person would actually
        # write this by hand on the paper form.
        #
        # Caught while writing this module's own tests: Decimal's
        # :g format spec does NOT strip trailing zeros the way
        # float's does (f"{Decimal('2.00'):g}" renders "2.00", not
        # "2") — int() is the actual correct conversion here, not a
        # format spec.
        qty = line.quantity
        qty_display = str(int(qty)) if qty == qty.to_integral_value() else str(qty)
        rows += f"""
        <tr>
            <td class="num">{i}</td>
            <td>{line.part.name}</td>
            <td>{qty_display} {line.part.unit}</td>
        </tr>"""
    return rows


def build_job_ticket_pdf(work_order, org_name):
    """
    Returns raw PDF bytes — pure function, same discipline as
    build_quotation_pdf, kept independently testable without needing
    the full request/response cycle.
    """
    job_lines = list(work_order.job_lines.all())
    material_lines = list(work_order.material_lines.select_related("part").all())

    date_block = ""
    # work_started_at is Estimate-only (see WorkOrder.mark_started's
    # own docstring) — null forever for a direct-entry WorkOrder even
    # after it's genuinely IN_PROGRESS. created_at is an imperfect
    # stand-in (it's "when the record was made," not "when Mulai
    # Dikerjakan was clicked"), but printing no date at all on most
    # real tickets is worse. Worth a real conversation with Made
    # about whether a proper Estimate-independent start timestamp is
    # worth adding — not silently redesigned here.
    print_date = work_order.work_started_at or work_order.created_at
    if print_date:
        date_block = f'<div class="wo-date">{_format_date_id(print_date)}</div>'

    # Caught by an actual render, not just reading the HTML: when
    # there's no assigned mechanic, a bare "<tr>{mechanic_block}</tr>"
    # produces an empty <tr></tr> — zero cells in a table whose first
    # row has two columns. reportlab genuinely chokes on that
    # ("2 rows in data but 1 row heights") rather than just rendering
    # an empty row, so the row itself must be conditional, not just
    # its content.
    mechanic_row = ""
    if work_order.assigned_to_id and work_order.assigned_to.name:
        mechanic_row = f"""
        <tr>
            <td colspan="2">
                <div class="label">Mekanik</div>
                <div class="value">{work_order.assigned_to.name}</div>
            </td>
        </tr>"""

    notes_block = ""
    if work_order.notes:
        notes_block = f"""
        <div class="label">Catatan</div>
        <p class="notes">{work_order.notes}</p>
        """

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
        .wo-number {{ font-size: 12pt; font-weight: bold; text-align: right; }}
        .wo-date {{ font-size: 9.5pt; color: #6b6b6b; text-align: right; margin-top: 2px; }}
        .status-badge {{ font-size: 8.5pt; font-weight: bold; color: #ffffff;
                         background-color: {STATUS_COLOR.get(work_order.status, "#6b6b6b")};
                         padding: 3px 10px; text-align: center; }}
        .info-table {{ width: 100%; margin-bottom: 20px; border-bottom: 1px solid #d8d8d8; padding-bottom: 14px; }}
        .label {{ font-size: 8.5pt; color: #6b6b6b; text-transform: uppercase; }}
        .value {{ font-size: 12pt; font-weight: bold; margin-top: 2px; }}
        .notes {{ font-size: 10pt; margin: 4px 0 18px 0; }}
        .section-title {{ font-size: 9.5pt; font-weight: bold; text-transform: uppercase;
                          color: #6b6b6b; margin: 14px 0 8px 0; }}
        .line-table {{ width: 100%; border-collapse: collapse; }}
        .line-table th {{ text-align: left; font-size: 8.5pt; text-transform: uppercase;
                          color: #6b6b6b; border-bottom: 1px solid #d8d8d8; padding: 4px 0; }}
        .line-table td {{ font-size: 10pt; padding: 5px 0; border-bottom: 1px solid #eeeeee; }}
        .num {{ text-align: right; width: 26px; }}
        .empty {{ text-align: center; color: #6b6b6b; padding: 10px 0; }}
    </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td style="width: 55%;">
                    <div class="org-name">{org_name}</div>
                    <div class="doc-title">JOB TICKET</div>
                </td>
                <td style="width: 45%;">
                    <div class="wo-number">WO #{work_order.number}</div>
                    {date_block}
                    <table style="width: 100%; margin-top: 6px;"><tr><td>
                        <span class="status-badge">{STATUS_LABEL.get(work_order.status, work_order.status)}</span>
                    </td></tr></table>
                </td>
            </tr>
        </table>

        <table class="info-table">
            <tr>
                <td style="width: 50%;">
                    <div class="label">Nama</div>
                    <div class="value">{work_order.vehicle.customer.name}</div>
                </td>
                <td style="width: 50%;">
                    <div class="label">Kendaraan</div>
                    <div class="value">{work_order.vehicle.model} — {work_order.vehicle.plate_number}</div>
                </td>
            </tr>
            {mechanic_row}
        </table>

        {notes_block}

        <div class="section-title">Job Description</div>
        <table class="line-table">
            <thead><tr><th class="num">No.</th><th>Deskripsi</th></tr></thead>
            <tbody>{_job_description_rows(job_lines)}</tbody>
        </table>

        <div class="section-title">Material / Item</div>
        <table class="line-table">
            <thead><tr><th class="num">No.</th><th>Material / Item</th><th>Satuan</th></tr></thead>
            <tbody>{_material_rows(material_lines)}</tbody>
        </table>
    </body>
    </html>
    """

    buffer = BytesIO()
    pisa.CreatePDF(html, dest=buffer)
    return buffer.getvalue()
