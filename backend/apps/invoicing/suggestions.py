"""
Arthasee — Invoice jasa suggestions (Phase 21, Task 21.2, 19 Oct 2026)

Since Task 21.1 a Work Order carries no price at all (Made, 12 Sep note:
"Di WO tidak boleh muncul harga!"). The price of each jasa therefore has
to come from somewhere else when the invoice is made. Agreed rule
(Chris/Made, 16 Oct): use the price on the APPROVED ESTIMATE -- that is
what the customer agreed to. A jasa added on the WO later has no agreed
price yet; it is suggested with no price, and staff fill it in. (Daftar
Jasa, Task 21.3+, will later fill that gap from the price list.)

Read-only. Never writes. The "Buat Invoice" form shows these lines
editable; InvoiceCreateView's POST is still the only thing that creates
an Invoice.

One suggestion per WorkOrderJobLine, in WO order. How a job line is
matched to its estimate line, first match wins:
  1. WorkOrderJobLine.estimate_line_item -- the link Estimate.approve()
     records from 19 Oct 2026.
  2. Older WOs: the "(estimasi Rp 350.000)" text Estimate.approve()
     wrote into the description before 16 Oct 2026. Price read from that
     text; quantity from the estimate line with the same description and
     price, if there is one, otherwise 1.
  3. WOs approved between 16 and 19 Oct 2026 (no text, no link yet): an
     unused estimate labor line with exactly the same description.
  4. Otherwise: a jasa added on the WO -- no price.
Each estimate line is used at most once. An estimate labor line whose
job line was deleted on the WO is not suggested: that work was not done.
"""
import re
from decimal import Decimal, InvalidOperation

from apps.workorders.text import strip_price_suffix

_LEGACY_PRICE_RE = re.compile(r"\(estimasi\s+Rp\s*([\d.]+)\)\s*$", re.IGNORECASE)


def _legacy_price(description):
    """Rp amount from an old "(estimasi Rp 1.500.000)" suffix, or None."""
    match = _LEGACY_PRICE_RE.search(description or "")
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(".", ""))
    except InvalidOperation:
        return None


def suggested_labor_lines(service_record):
    """
    Returns a list of dicts:
      {"description": str, "quantity": Decimal, "unit_price": Decimal | None,
       "source": "estimate" | "work_order"}
    Empty list when the ServiceRecord has no WorkOrder behind it.
    """
    work_order = getattr(service_record, "work_order", None)
    if work_order is None:
        return []

    estimate = getattr(work_order, "estimate", None)
    estimate_labor = list(estimate.line_items.filter(kind="labor").order_by("created_at")) if estimate else []
    by_id = {li.id: li for li in estimate_labor}
    used = set()

    def unused_match(description, unit_price=None):
        for li in estimate_labor:
            if li.id in used or li.description.strip() != description:
                continue
            if unit_price is not None and li.unit_price != unit_price:
                continue
            return li
        return None

    suggestions = []
    for line in work_order.job_lines.order_by("created_at"):
        description = strip_price_suffix(line.description)

        # 1. The recorded link.
        est = by_id.get(line.estimate_line_item_id) if line.estimate_line_item_id else None
        if est is not None and est.id in used:
            est = None

        # 2. Old "(estimasi Rp ...)" text.
        if est is None and not line.estimate_line_item_id:
            legacy = _legacy_price(line.description)
            if legacy is not None:
                est = unused_match(description, legacy)
                if est is None:
                    suggestions.append({
                        "description": description, "quantity": Decimal("1"),
                        "unit_price": legacy, "source": "estimate",
                    })
                    continue

        # 3. Same description, no link (approved 16-19 Oct 2026).
        if est is None and not line.estimate_line_item_id:
            est = unused_match(description)

        if est is not None:
            used.add(est.id)
            suggestions.append({
                "description": description, "quantity": est.quantity,
                "unit_price": est.unit_price, "source": "estimate",
            })
        else:
            # 4. Added on the WO -- no agreed price.
            suggestions.append({
                "description": description, "quantity": Decimal("1"),
                "unit_price": None, "source": "work_order",
            })
    return suggestions
