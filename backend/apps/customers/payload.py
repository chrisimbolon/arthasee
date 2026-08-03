# =============================================================================
# === backend/apps/customers/payload.py ===
# =============================================================================
"""
Shared, whitelist-only payload builder — extracted from
PublicTrackingView (Fase 2 v1) when Fase 2.5 needed the exact same
stage/invoice breakdown for a JWT-authenticated customer's own
dashboard, not just a one-off token link. One function, two callers
(PublicTrackingView and CustomerWorkOrderDetailView), rather than
copy-pasting the same whitelist logic twice — a field added here
protects both access paths at once, and a mistake only has to be
caught once.
"""
STATUS_LABEL = {
    "OPEN": "Terbuka", "IN_PROGRESS": "Dikerjakan", "QC": "Pemeriksaan Kualitas",
    "DONE": "Selesai", "CANCELLED": "Dibatalkan",
}


def build_work_order_tracking_payload(work_order):
    """
    Returns a plain dict, deliberately whitelist-only — never derived
    from serializing WorkOrder/Vehicle/Invoice wholesale, so a field
    added to those models later can never silently leak onto a
    customer-facing screen just by existing. Caller is responsible
    for passing the result through PublicTrackingSerializer (or
    equivalent) before returning it in a Response.
    """
    vehicle = work_order.vehicle

    # getattr probe, same pattern already proven throughout this
    # codebase (WorkOrder.mark_started(), Invoice.save()'s own
    # mechanic lookup) — a reverse OneToOneField raises
    # RelatedObjectDoesNotExist rather than returning None when
    # nothing points back to it.
    service_record = getattr(work_order, "service_record", None)
    invoice = getattr(service_record, "invoice", None) if service_record else None

    invoice_payload = None
    # Chris's own explicit scope call, 2 Aug: only shown once the job
    # is genuinely DONE and a real invoice exists — never a mid-repair
    # estimate, and never any contract/termin financials (institutional
    # clients pay via TerminPeriod schedules, not a flat invoice —
    # showing this here would be confusing or simply wrong against
    # their real payment plan). Applies identically whether the
    # customer arrived via a token link or a real logged-in session —
    # the rule is about the DATA, not the access path.
    if work_order.status == "DONE" and invoice is not None:
        invoice_payload = {
            "number": invoice.number,
            "mechanic_name_snapshot": invoice.mechanic_name_snapshot,
            "total": invoice.total,
            "status": invoice.get_status_display(),
        }

    return {
        "work_order_number": work_order.number,
        "status": STATUS_LABEL.get(work_order.status, work_order.status),
        "vehicle_plate": vehicle.plate_number,
        "vehicle_model": vehicle.model,
        "mechanic_name": work_order.assigned_to.name if work_order.assigned_to_id else None,
        "stages": list(work_order.stages.order_by("sequence").all()),
        "invoice": invoice_payload,
    }
