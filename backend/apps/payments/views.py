# =============================================================================
# === backend/apps/payments/views.py ===
# =============================================================================
"""
NOTE: TenantScopedAPIView's exact interface is confirmed against the
real apps/core/views.py.
"""
from apps.core.views import TenantScopedAPIView
from apps.invoicing.models import Invoice
from apps.purchasing.models import SupplierInvoice
from rest_framework import status
from rest_framework.response import Response

from .models import Payment, Refund, SupplierPayment
from .serializers import (PaymentRecordSerializer, PaymentSerializer,
                          RefundRecordSerializer, RefundSerializer,
                          SupplierPaymentRecordSerializer,
                          SupplierPaymentSerializer)


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
    POST /api/invoices/<invoice_id>/refund/ — processes a full refund
    for a PAID invoice, transitioning it to CANCELLED. All the real
    logic lives in Refund.record() — this view is thin.
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


class SupplierInvoicePayView(TenantScopedAPIView):
    """
    POST /api/supplier-invoices/<supplier_invoice_id>/pay/ — Sprint 3,
    Task 3.3. Pays a supplier invoice in full. Lives here, not in
    apps.purchasing, per the Roadmap's own posting matrix
    (SupplierPaymentMade is a payments-domain event) — same precedent
    as InvoiceRefundView already living here for Invoice, a resource
    owned by a different app. All real logic lives in
    SupplierPayment.record() — this view is thin.
    """
    model = SupplierPayment

    def post(self, request, supplier_invoice_id):
        supplier_invoice = self._get_supplier_invoice(request, supplier_invoice_id)
        if supplier_invoice is None:
            return Response(
                {"success": False, "message": "Invoice supplier tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = SupplierPaymentRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            payment = SupplierPayment.record(
                supplier_invoice=supplier_invoice,
                method=data.get("method", "bank_transfer"),
                reference=data.get("reference", ""),
                notes=data.get("notes", ""),
                paid_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "supplier_payment": SupplierPaymentSerializer(payment).data},
            status=status.HTTP_201_CREATED,
        )

    def _get_supplier_invoice(self, request, supplier_invoice_id):
        user = request.user
        if user.role == "super_admin":
            qs = SupplierInvoice.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = SupplierInvoice.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=supplier_invoice_id).first()
