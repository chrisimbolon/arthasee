# =============================================================================
# === backend/apps/invoicing/views.py ===
# =============================================================================
from apps.core.views import TenantScopedAPIView
from apps.service.models import ServiceRecord
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from .models import Invoice, InvoiceLineItem
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
            # Raised by Invoice.save() when the organization has no
            # invoice_code configured — a real, actionable setup
            # problem, not a server bug, so it belongs in a 400 the
            # frontend can display, not a raw 500.
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

    The one deliberate exception to "invoices never change" — status
    (DRAFT -> ISSUED -> PAID, or CANCELLED) is workflow metadata, not
    financial content. Line items, prices, and snapshots stay frozen
    regardless of how many times status changes.
    """
    model = Invoice

    def patch(self, request, pk):
        invoice = self.get_object(pk)
        new_status = request.data.get("status")
        if new_status not in dict(Invoice.STATUS_CHOICES):
            return Response(
                {"success": False, "message": "Status tidak valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invoice.status = new_status
        invoice.save(update_fields=["status"])
        return Response({"success": True, "invoice": InvoiceSerializer(invoice).data})
