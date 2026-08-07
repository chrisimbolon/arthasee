# =============================================================================
# === backend/apps/payments/views.py ===
# =============================================================================
"""
NOTE (flagged, not guessed silently): TenantScopedAPIView's exact
interface (get_object, get_queryset, model attribute) is pattern-
matched from how apps.invoicing.views already uses it — I have not
seen apps/core/views.py directly. _get_invoice() below mirrors
InvoiceCreateView._get_service_record()'s own cross-model lookup
shape for the same reason that method exists: self.get_queryset()
filters by self.model (Payment here), not Invoice, so a manual
tenant-scoped lookup is needed to fetch the parent Invoice from the
URL's invoice_id. Worth a quick sanity check against the real
TenantScopedAPIView before relying on this in production.
"""
from apps.core.views import TenantScopedAPIView
from apps.invoicing.models import Invoice
from rest_framework import status
from rest_framework.response import Response

from .models import Payment
from .serializers import PaymentRecordSerializer, PaymentSerializer


class InvoicePaymentListCreateView(TenantScopedAPIView):
    """
    GET  /api/invoices/<invoice_id>/payments/  — payment history for one invoice
    POST /api/invoices/<invoice_id>/payments/  — record a new payment

    POST body: {"amount": num, "method": str (optional, default "cash"),
                 "received_at": iso-datetime (optional, defaults to now),
                 "reference": str (optional), "notes": str (optional)}

    All the real business logic (status guard, overpayment guard,
    auto-transition to PAID) lives in Payment.record() — this view is
    thin on purpose, same division of responsibility as
    InvoiceCreateView delegating to Invoice.save().
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
            # Same 400-not-500 reasoning as InvoiceCreateView's own
            # ValueError handling — these are real, actionable
            # problems (wrong status, overpayment), not server bugs.
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
