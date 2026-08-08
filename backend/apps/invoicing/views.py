# =============================================================================
# === backend/apps/invoicing/views.py ===
# =============================================================================
from decimal import Decimal

from apps.core.views import TenantScopedAPIView
from apps.service.models import ServiceRecord
from django.db import transaction
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response

from .models import Invoice, InvoiceLineItem
from .pdf import build_invoice_pdf
from .serializers import InvoiceSerializer


class InvoiceCreateView(TenantScopedAPIView):
    """
    POST /api/service-records/<service_record_id>/invoice/

    Creates the Invoice and every InvoiceLineItem in one atomic
    transaction: every existing PartUsage on this ServiceRecord
    becomes a "part" line, snapshotting the price PartUsage itself
    already locked in at usage time — not re-reading Part.unit_price,
    which could have changed since. Any labor lines supplied in the
    request body become "labor" lines.

    Nothing here touches inventory stock — that already happened the
    moment each PartUsage was created. This step only reads and
    freezes what's already true; it must never deduct twice.

    Body: { "labor_lines": [{"description": str, "quantity": num, "unit_price": num}, ...] }
    labor_lines is optional — an invoice can be all parts, all labor,
    or a mix.
    """
    model = Invoice

    def post(self, request, service_record_id):
        service_record = self._get_service_record(request, service_record_id)
        if service_record is None:
            return Response(
                {"success": False, "message": "Catatan servis tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if hasattr(service_record, "invoice"):
            return Response(
                {"success": False, "message": "Catatan servis ini sudah memiliki invoice."},
                status=status.HTTP_409_CONFLICT,
            )

        labor_lines = request.data.get("labor_lines", [])

        try:
            with transaction.atomic():
                invoice = Invoice.objects.create(service_record=service_record, created_by=request.user)

                for pu in service_record.part_usages.select_related("part").all():
                    InvoiceLineItem.objects.create(
                        invoice=invoice, kind="part",
                        description=pu.part.name, quantity=pu.quantity,
                        unit_price=pu.unit_price_at_time, part=pu.part,
                    )

                for line in labor_lines:
                    InvoiceLineItem.objects.create(
                        invoice=invoice, kind="labor",
                        description=line.get("description", "Jasa"),
                        quantity=line.get("quantity", 1),
                        unit_price=line.get("unit_price", 0),
                    )
        except ValueError as e:
            # Raised by Invoice.save() for either of two real,
            # actionable setup problems, not a server bug — so both
            # belong in a 400 the frontend can display, not a raw
            # 500: the organization has no invoice_code configured,
            # or (added 31 Jul, Made's own hard requirement) the
            # originating WorkOrder has no mechanic assigned yet.
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "invoice": InvoiceSerializer(invoice).data},
            status=status.HTTP_201_CREATED,
        )

    def _get_service_record(self, request, service_record_id):
        # Deliberately not self.get_queryset() — that filters by
        # self.model, which is Invoice here, not ServiceRecord. Same
        # tenant-scoping logic as TenantScopedAPIView, applied to the
        # actual model this lookup needs.
        user = request.user
        if user.role == "super_admin":
            qs = ServiceRecord.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = ServiceRecord.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=service_record_id).select_related("vehicle__customer").first()


class InvoiceDetailView(TenantScopedAPIView):
    """
    GET /api/invoices/<id>/ — read-only. Invoices are frozen
    documents; there is deliberately no PUT/PATCH here for financial
    content, only the dedicated status endpoint below.
    """
    model = Invoice

    def get(self, request, pk):
        invoice = self.get_object(pk)
        return Response({"success": True, "invoice": InvoiceSerializer(invoice).data})


class InvoiceStatusUpdateView(TenantScopedAPIView):
    """
    PATCH /api/invoices/<id>/status/

    "PAID" is not an accepted value here at all — Chris's own
    explicit call: PAID must only ever be system-derived, set the
    moment apps.payments.models.Payment.record() sees balance_due
    actually reach zero — never a human's typed claim with no
    relationship to real money received.

    UPDATED — DRAFT is now a one-way exit. Once an invoice leaves
    DRAFT (to ISSUED or CANCELLED), it can never be PATCHed back to
    DRAFT. This closes a real gap: without it, ISSUED -> DRAFT ->
    ISSUED again would fire InvoiceIssued (see below) a second time
    for the same invoice, double-recognizing revenue. Chris's own
    explicit call, once this was surfaced — not assumed silently.

    Manually settable values are DRAFT (only from DRAFT itself, i.e.
    a no-op), ISSUED, and CANCELLED. CANCELLED is additionally
    blocked if real payments already exist against the invoice — see
    the existing comment on that check below, unchanged from before.

    Line items, prices, and snapshots stay frozen regardless of how
    many times status changes — status is workflow metadata, not
    financial content, same distinction as before.
    """
    model = Invoice

    MANUALLY_SETTABLE_STATUSES = {"DRAFT", "ISSUED", "CANCELLED"}

    def patch(self, request, pk):
        invoice = self.get_object(pk)
        new_status = request.data.get("status")
        old_status = invoice.status

        if new_status == "PAID":
            return Response(
                {
                    "success": False,
                    "message": (
                        "Status 'Lunas' tidak bisa diatur secara manual — "
                        "catat pembayaran melalui endpoint pembayaran "
                        "(/api/invoices/<id>/payments/), status akan berubah "
                        "otomatis saat sisa tagihan mencapai nol."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_status not in self.MANUALLY_SETTABLE_STATUSES:
            return Response(
                {"success": False, "message": "Status tidak valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_status == "DRAFT" and old_status != "DRAFT":
            return Response(
                {
                    "success": False,
                    "message": (
                        "Invoice sudah pernah diterbitkan atau dibatalkan — "
                        "tidak bisa dikembalikan ke status Draf."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_status == "CANCELLED" and invoice.payments.exists():
            return Response(
                {
                    "success": False,
                    "message": (
                        "Invoice ini sudah memiliki pembayaran tercatat — "
                        "tidak bisa dibatalkan langsung. Proses refund/credit "
                        "memo belum tersedia (akan datang di Sprint 2)."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            invoice.status = new_status
            invoice.save(update_fields=["status"])

            # Sprint 2, Task 2.1 — revenue recognition fires exactly
            # once, at the real DRAFT -> ISSUED transition. The DRAFT
            # one-way guard above is what makes "exactly once" an
            # actual guarantee rather than just an intention — without
            # it, this same `if` would fire again on a later re-issue.
            if old_status == "DRAFT" and new_status == "ISSUED":
                from apps.core.events.bus import default_bus
                from apps.invoicing.events import InvoiceIssued

                # Computed the same way Invoice.subtotal itself already
                # does — sum() over the .subtotal property, not a DB
                # aggregate — consistent with that existing idiom.
                service_amount = sum(
                    (li.subtotal for li in invoice.line_items.filter(kind="labor")),
                    Decimal("0"),
                )
                parts_amount = sum(
                    (li.subtotal for li in invoice.line_items.filter(kind="part")),
                    Decimal("0"),
                )
                event = InvoiceIssued(
                    organization_id=invoice.organization_id,
                    invoice_id=invoice.id,
                    service_amount=service_amount,
                    parts_amount=parts_amount,
                    total=service_amount + parts_amount,
                    line_item_count=invoice.line_items.count(),
                )
                # Task 2.3, Half A's own reason this field exists —
                # the one durable reference a later cancellation needs
                # to find and reverse this exact posting. Saved BEFORE
                # publish() so it's durable even if publish() itself
                # ever changed behavior — event_id is generated at
                # construction time above, not by publish() itself.
                invoice.issued_event_id = event.event_id
                invoice.save(update_fields=["issued_event_id"])
                default_bus.publish(event)

            # Task 2.3, Half A — the unpaid-cancellation reversal.
            # Deliberately scoped to old_status == "ISSUED" only: a
            # DRAFT invoice cancelled directly never had anything
            # posted for it (InvoiceIssued never fired), so publishing
            # a cancellation event for it would just be audit-trail
            # noise with nothing to reverse. The CANCELLED-with-
            # payments guard above already keeps this branch
            # unpaid-only — a paid refund is Task 2.3 Half B, not yet
            # built, and still hits that guard's 409 today.
            if new_status == "CANCELLED" and old_status == "ISSUED":
                from apps.core.events.bus import default_bus
                from apps.invoicing.events import InvoiceCancelled

                default_bus.publish(InvoiceCancelled(
                    organization_id=invoice.organization_id,
                    invoice_id=invoice.id,
                    issued_event_id=invoice.issued_event_id,
                ))

        return Response({"success": True, "invoice": InvoiceSerializer(invoice).data})


class InvoicePdfView(TenantScopedAPIView):
    """
    GET /api/invoices/<id>/receipt.pdf
    Made's own ask, 31 Jul: a real, downloadable PDF for LUNAS
    invoices, so SA/cashier can forward it themselves via their own
    WhatsApp — same manual-download pattern already built for
    Estimate quotations, not automated sending.

    Confirmed with Chris: hard-gated to PAID only, not available for
    any other status — a DRAFT/ISSUED invoice isn't yet a finished
    receipt, and a CANCELLED one shouldn't be handed to a customer as
    if it were still valid. Enforced here, not just hidden in the
    frontend — a real API consumer hitting this URL directly must
    still be blocked regardless of what any UI button shows.

    This gate is now meaningfully stronger than before — PAID can
    only be reached via Payment.record() actually zeroing out
    balance_due (see InvoiceStatusUpdateView above), so a PDF served
    from here now genuinely corresponds to money received, not just
    a status field someone set by hand.

    Returns a raw HttpResponse, not a DRF Response — same reasoning
    already established for ContractExportTerminView and
    EstimateQuotationPdfView: a real file, not JSON, and DRF's own
    finalize_response() passes any HttpResponseBase through unchanged.
    """
    model = Invoice

    def get(self, request, pk):
        invoice = self.get_object(pk)
        if invoice.status != "PAID":
            return Response(
                {"success": False, "message": "PDF hanya tersedia untuk invoice yang sudah Lunas."},
                status=status.HTTP_409_CONFLICT,
            )
        pdf_bytes = build_invoice_pdf(invoice, org_name=invoice.organization.name)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        # invoice.number genuinely contains slashes ("INV/REG/AM/0004/
        # 2026") — would break as a raw filename on a real filesystem.
        # Verified directly against the real format before writing
        # this, not assumed safe — same class of bug already caught
        # once before with a contract title.
        safe_number = "".join(c if c.isalnum() or c in " -_" else "_" for c in invoice.number)
        response["Content-Disposition"] = f'attachment; filename="Invoice_{safe_number}.pdf"'
        return response
