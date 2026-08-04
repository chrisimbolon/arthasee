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


def _three_state_status(entity):
    """
    Selesai / Sedang Berjalan / Menunggu — the same three-state rule
    already used for WorkOrderStage, now shared with job lines too
    (Made's own confirmed note, 4 Aug: per-step start/end timing, not
    just a done/not-done flag). Works identically for either a Stage
    or a JobLine instance — both carry the same started_at/
    completed_at shape. One place computes this so a future change to
    the 3-state rule only has to happen once, not separately for
    stages and job lines.
    """
    if entity.completed_at:
        return "Selesai"
    if entity.started_at:
        return "Sedang Berjalan"
    return "Menunggu"


def _serialize_job_line(line):
    return {
        "description": line.description,
        "status": _three_state_status(line),
        "started_at": line.started_at,
        "completed_at": line.completed_at,
    }


def build_work_order_tracking_payload(work_order):
    """
    Returns a plain dict, deliberately whitelist-only — never derived
    from serializing WorkOrder/Vehicle/Invoice wholesale, so a field
    added to those models later can never silently leak onto a
    customer-facing screen just by existing. Caller is responsible
    for passing the result through PublicTrackingSerializer (or
    equivalent) before returning it in a Response.

    Chris's own explicit scope call, 4 Aug: job-line-level detail is
    now included, nested under each stage — a real, deliberate
    widening of Fase 2 v1's original "stage-level only, no job-line
    detail" scope (see git history / the roadmap for that earlier
    decision). Made's own confirmed note ("jam mulai – jam selesai")
    only settled the SCHEMA question; showing this to the customer at
    all was Chris's own separate call, made explicitly, not inferred
    from the note.
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

    stages_payload = []
    for stage in work_order.stages.order_by("sequence").all():
        stages_payload.append({
            "name": stage.name,
            "status": _three_state_status(stage),
            "started_at": stage.started_at,
            "completed_at": stage.completed_at,
            "job_lines": [_serialize_job_line(line) for line in stage.job_lines.all()],
        })

    # Mirrors the internal page's own "Pekerjaan Lain (Tanpa Tahap)"
    # section — routine work that was never grouped under a stage
    # (a standalone oil change, not part of a multi-step overhaul)
    # still gets its own real timing, shown the same honest way.
    unstaged_job_lines = [
        _serialize_job_line(line) for line in work_order.job_lines.filter(stage__isnull=True)
    ]

    return {
        "work_order_number": work_order.number,
        "status": STATUS_LABEL.get(work_order.status, work_order.status),
        "vehicle_plate": vehicle.plate_number,
        "vehicle_model": vehicle.model,
        "mechanic_name": work_order.assigned_to.name if work_order.assigned_to_id else None,
        "stages": stages_payload,
        "unstaged_job_lines": unstaged_job_lines,
        "invoice": invoice_payload,
    }
