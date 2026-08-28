# =============================================================================
# === backend/apps/payments/views.py ===
# =============================================================================
"""
NOTE: TenantScopedAPIView's exact interface is confirmed against the
real apps/core/views.py.
"""
from apps.accounting.models import Account
from apps.core.views import TenantScopedAPIView
from apps.invoicing.models import Invoice
from apps.purchasing.models import SupplierInvoice
from apps.workorders.models import Mechanic
from rest_framework import status
from rest_framework.response import Response

from .models import OperatingExpense, Payment, Refund, SupplierPayment
from .serializers import (OperatingExpenseRecordSerializer,
                          OperatingExpenseSerializer, PaymentRecordSerializer,
                          PaymentSerializer, RefundRecordSerializer,
                          RefundSerializer, SupplierPaymentRecordSerializer,
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


class OperatingExpenseListCreateView(TenantScopedAPIView):
    """
    GET  /api/operating-expenses/  — every real operating expense for this org
    POST /api/operating-expenses/  — record a new one

    27 Aug 2026 — Made's own confirmed real request: a guided
    alternative to the generic Manual Adjusting Journal for a
    recurring operating cost. All real logic lives in
    OperatingExpense.record() — this view is thin, resolving
    `account_code` and `mechanic` against the ACTING organization
    specifically, never trusting a raw code/id directly. Uses
    TenantScopedAPIView's own get_organization()/get_queryset(),
    the same established pattern QuickPurchaseListCreateView already
    proves out — not the older per-view _get_invoice()-style helper
    the other three views in this file happen to use.
    """
    model = OperatingExpense

    def get(self, request):
        expenses = (
            self.get_queryset()
            .select_related("account", "mechanic", "created_by")
        )
        return Response(
            {"success": True, "operating_expenses": OperatingExpenseSerializer(expenses, many=True).data}
        )

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = OperatingExpenseRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            account = Account.resolve(organization, data["account_code"])
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        mechanic = None
        if data.get("mechanic"):
            mechanic = Mechanic.objects.filter(organization=organization, pk=data["mechanic"]).first()
            if mechanic is None:
                return Response(
                    {"success": False, "message": "Mekanik tidak ditemukan."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            expense = OperatingExpense.record(
                organization=organization, account=account, amount=data["amount"],
                method=data.get("method", "cash"), paid_at=data.get("paid_at"),
                mechanic=mechanic, reference=data.get("reference", ""),
                notes=data.get("notes", ""), created_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "operating_expense": OperatingExpenseSerializer(expense).data},
            status=status.HTTP_201_CREATED,
        )
