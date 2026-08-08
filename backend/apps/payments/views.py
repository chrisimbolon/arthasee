# =============================================================================
# === backend/apps/payments/views.py ===
# =============================================================================
"""
NOTE: TenantScopedAPIView's exact interface (get_object, get_queryset,
model attribute) is confirmed against the real apps/core/views.py —
_get_invoice() below mirrors InvoiceCreateView._get_service_record()'s
own cross-model lookup shape for the same reason that method exists:
self.get_queryset() filters by self.model, not Invoice.
"""
from apps.core.views import TenantScopedAPIView
from apps.invoicing.models import Invoice
from rest_framework import status
from rest_framework.response import Response

from .models import Payment, Refund
from .serializers import (PaymentRecordSerializer, PaymentSerializer,
                          RefundRecordSerializer, RefundSerializer)


class InvoicePaymentListCreateView(TenantScopedAPIView):
    """
    GET  /api/invoices/<invoice_id>/payments/  — payment history for one invoice
    POST /api/invoices/<invoice_id>/payments/  — record a new payment

    All the real business logic (status guard, overpayment guard,
    auto-transition to PAID) lives in Payment.record() — this view is
    thin on purpose.
    """
    model = Payment

    def get(self, request, invoice_id):
        invoice = self._get_invoice(request, invoice_id)
        if invoice is None:
            return Response(
                {"success": False, "message": "Invoice tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        payments = invoice.payments.select_related("received_by").all()
        return Response({"success": True, "payments": PaymentSerializer(payments, many=True).data})

    def post(self, request, invoice_id):
        invoice = self._get_invoice(request, invoice_id)
        if invoice is None:
            return Response(
                {"success": False, "message": "Invoice tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = PaymentRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            payment = Payment.record(
                invoice=invoice,
                amount=data["amount"],
                method=data.get("method", "cash"),
                received_at=data.get("received_at"),
                reference=data.get("reference", ""),
                notes=data.get("notes", ""),
                received_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "payment": PaymentSerializer(payment).data},
            status=status.HTTP_201_CREATED,
        )

    def _get_invoice(self, request, invoice_id):
        user = request.user
        if user.role == "super_admin":
            qs = Invoice.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = Invoice.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=invoice_id).first()


class InvoiceRefundView(TenantScopedAPIView):
    """
    POST /api/invoices/<invoice_id>/refund/ — Task 2.3, Half B.
    Processes a full refund for a PAID invoice, transitioning it to
    CANCELLED. All the real logic (status guard, amount computation
    from invoice.total_paid, the status transition, the event
    publish) lives in Refund.record() — this view is thin, same
    division of responsibility as InvoicePaymentListCreateView
    delegating to Payment.record().

    No amount field accepted here — Refund.record() computes it from
    invoice.total_paid. This endpoint only ever refunds the full
    amount; a partially-paid invoice cannot reach here at all (it's
    still blocked by InvoiceStatusUpdateView's own CANCELLED guard,
    and Refund.record() itself requires status == "PAID").
    """
    model = Refund

    def post(self, request, invoice_id):
        invoice = self._get_invoice(request, invoice_id)
        if invoice is None:
            return Response(
                {"success": False, "message": "Invoice tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = RefundRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            refund = Refund.record(
                invoice=invoice,
                method=data.get("method", "cash"),
                reference=data.get("reference", ""),
                notes=data.get("notes", ""),
                refunded_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "refund": RefundSerializer(refund).data},
            status=status.HTTP_201_CREATED,
        )

    def _get_invoice(self, request, invoice_id):
        user = request.user
        if user.role == "super_admin":
            qs = Invoice.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = Invoice.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=invoice_id).first()
