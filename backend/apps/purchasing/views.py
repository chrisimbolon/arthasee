# =============================================================================
# === backend/apps/purchasing/views.py ===
# =============================================================================
"""
NOTE: TenantScopedAPIView's exact interface is confirmed against the
real apps/core/views.py, including the new get_organization() method
added alongside this delivery — see apps/core/PATCH_get_organization.md.
"""
from apps.core.views import TenantScopedAPIView
from apps.inventory.models import Part
from rest_framework import status
from rest_framework.response import Response

from .models import (GoodsReceivedNote, GoodsReceivedNoteLineItem,
                     PurchaseReturn, Supplier, SupplierInvoice)
from .serializers import (GoodsReceivedNoteRecordSerializer,
                          GoodsReceivedNoteSerializer,
                          PurchaseReturnRecordSerializer,
                          PurchaseReturnSerializer,
                          SupplierInvoiceRecordSerializer,
                          SupplierInvoiceSerializer, SupplierSerializer)


class SupplierListCreateView(TenantScopedAPIView):
    """
    GET  /api/suppliers/  — list
    POST /api/suppliers/  — create

    Supplier has zero creation-time side effects (no sequence
    numbering, no events, no stock movement) — a plain ModelSerializer
    is enough, unlike GoodsReceivedNote/SupplierInvoice below, which
    both go through a real .record()/.receive() classmethod instead.
    """
    model = Supplier

    def get(self, request):
        suppliers = self.get_queryset()
        return Response({"success": True, "suppliers": SupplierSerializer(suppliers, many=True).data})

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = SupplierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        supplier = serializer.save(organization=organization)
        return Response(
            {"success": True, "supplier": SupplierSerializer(supplier).data},
            status=status.HTTP_201_CREATED,
        )


class SupplierDetailView(TenantScopedAPIView):
    """GET /api/suppliers/<id>/"""
    model = Supplier

    def get(self, request, pk):
        supplier = self.get_object(pk)
        return Response({"success": True, "supplier": SupplierSerializer(supplier).data})


class GoodsReceivedNoteListCreateView(TenantScopedAPIView):
    """
    GET  /api/goods-received-notes/  — list
    POST /api/goods-received-notes/  — record a delivery

    All real logic (sequence numbering, the real StockAdjustment side
    effect per line, the GoodsReceived event) lives in
    GoodsReceivedNote.receive() — this view is thin, and its only
    real job beyond calling that method is resolving `supplier` and
    every line's `part` against the ACTING organization specifically,
    never trusting the raw UUIDs a request supplies.
    """
    model = GoodsReceivedNote

    def get(self, request):
        grns = (
            self.get_queryset()
            .select_related("supplier", "received_by")
            .prefetch_related("line_items__part")
        )
        return Response({"success": True, "goods_received_notes": GoodsReceivedNoteSerializer(grns, many=True).data})

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = GoodsReceivedNoteRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        supplier = Supplier.objects.filter(organization=organization, pk=data["supplier"]).first()
        if supplier is None:
            return Response(
                {"success": False, "message": "Supplier tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        lines = []
        for line in data["lines"]:
            part = Part.objects.filter(organization=organization, pk=line["part"]).first()
            if part is None:
                return Response(
                    {"success": False, "message": f"Part dengan id {line['part']} tidak ditemukan."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            lines.append({"part": part, "quantity": line["quantity"], "unit_cost": line["unit_cost"]})

        try:
            grn = GoodsReceivedNote.receive(
                organization=organization, supplier=supplier, lines=lines,
                received_at=data.get("received_at"),
                reference=data.get("reference", ""), notes=data.get("notes", ""),
                received_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "goods_received_note": GoodsReceivedNoteSerializer(grn).data},
            status=status.HTTP_201_CREATED,
        )


class GoodsReceivedNoteDetailView(TenantScopedAPIView):
    """
    GET /api/goods-received-notes/<id>/ — read-only. GRNs are frozen
    documents, same discipline as Invoice — no PATCH/PUT here at all.
    """
    model = GoodsReceivedNote

    def get(self, request, pk):
        grn = self.get_object(pk)
        return Response({"success": True, "goods_received_note": GoodsReceivedNoteSerializer(grn).data})


class SupplierInvoiceListCreateView(TenantScopedAPIView):
    """
    GET  /api/supplier-invoices/  — list
    POST /api/supplier-invoices/  — record a supplier's bill

    Same tenant-scoped-resolution discipline as GoodsReceivedNote
    above — `supplier` and every id in `goods_received_note_ids` are
    resolved against the acting organization, never trusted directly.
    """
    model = SupplierInvoice

    def get(self, request):
        invoices = self.get_queryset().select_related("supplier").prefetch_related("goods_received_notes")
        return Response({"success": True, "supplier_invoices": SupplierInvoiceSerializer(invoices, many=True).data})

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = SupplierInvoiceRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        supplier = Supplier.objects.filter(organization=organization, pk=data["supplier"]).first()
        if supplier is None:
            return Response(
                {"success": False, "message": "Supplier tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        grns = []
        for grn_id in data.get("goods_received_note_ids", []):
            grn = GoodsReceivedNote.objects.filter(organization=organization, pk=grn_id).first()
            if grn is None:
                return Response(
                    {"success": False, "message": f"GRN dengan id {grn_id} tidak ditemukan."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            grns.append(grn)

        try:
            invoice = SupplierInvoice.record(
                organization=organization, supplier=supplier, amount=data["amount"],
                invoice_date=data["invoice_date"], goods_received_notes=grns,
                supplier_invoice_number=data.get("supplier_invoice_number", ""),
                due_date=data.get("due_date"), notes=data.get("notes", ""),
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "supplier_invoice": SupplierInvoiceSerializer(invoice).data},
            status=status.HTTP_201_CREATED,
        )


class SupplierInvoiceDetailView(TenantScopedAPIView):
    """GET /api/supplier-invoices/<id>/"""
    model = SupplierInvoice

    def get(self, request, pk):
        invoice = self.get_object(pk)
        return Response({"success": True, "supplier_invoice": SupplierInvoiceSerializer(invoice).data})

class PurchaseReturnListCreateView(TenantScopedAPIView):
    """
    GET  /api/purchase-returns/  — list
    POST /api/purchase-returns/  — record a return

    All real logic (the Case-A guard, the cumulative partial-return
    cap, the real StockAdjustment side effect per line, the
    PurchaseReturned event) lives in PurchaseReturn.create_return() —
    this view is thin, and its only real job beyond calling that
    method is resolving `goods_received_note` and every line's
    `grn_line_item` against the ACTING organization specifically,
    same tenant-scoped-resolution discipline as
    GoodsReceivedNoteListCreateView above.
    """
    model = PurchaseReturn

    def get(self, request):
        returns = (
            self.get_queryset()
            .select_related("goods_received_note", "created_by")
            .prefetch_related("line_items__goods_received_note_line_item__part")
        )
        return Response({"success": True, "purchase_returns": PurchaseReturnSerializer(returns, many=True).data})

    def post(self, request):
        organization = self.get_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )

        input_serializer = PurchaseReturnRecordSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        grn = GoodsReceivedNote.objects.filter(organization=organization, pk=data["goods_received_note"]).first()
        if grn is None:
            return Response(
                {"success": False, "message": "GRN tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        lines = []
        for line in data["lines"]:
            grn_line = GoodsReceivedNoteLineItem.objects.filter(
                organization=organization, pk=line["grn_line_item"],
            ).first()
            if grn_line is None:
                return Response(
                    {"success": False, "message": f"Item GRN dengan id {line['grn_line_item']} tidak ditemukan."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            lines.append({"grn_line_item": grn_line, "quantity": line["quantity"]})

        try:
            purchase_return = PurchaseReturn.create_return(
                organization=organization, goods_received_note=grn, lines=lines,
                return_date=data.get("return_date"), reason=data["reason"],
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "purchase_return": PurchaseReturnSerializer(purchase_return).data},
            status=status.HTTP_201_CREATED,
        )


class PurchaseReturnDetailView(TenantScopedAPIView):
    """
    GET /api/purchase-returns/<id>/ — read-only. Purchase returns are
    frozen documents, same discipline as GRN/Invoice — no PATCH/PUT.
    """
    model = PurchaseReturn

    def get(self, request, pk):
        purchase_return = self.get_object(pk)
        return Response({"success": True, "purchase_return": PurchaseReturnSerializer(purchase_return).data})