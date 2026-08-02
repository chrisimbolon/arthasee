# =============================================================================
# === backend/apps/workorders/views.py ===
# =============================================================================
from datetime import date, timedelta

from apps.core.views import TenantScopedAPIView
from apps.inventory.models import StockAdjustment
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from .models import (Mechanic, WorkOrder, WorkOrderJobLine,
                     WorkOrderMaterialLine, WorkOrderStage)
from .pdf import build_job_ticket_pdf
from .serializers import (MechanicSerializer, WorkOrderJobLineSerializer,
                          WorkOrderListSerializer,
                          WorkOrderMaterialLineSerializer, WorkOrderSerializer,
                          WorkOrderStageSerializer)

# Statuses a WorkOrder can still be actively edited in — once it's
# DONE or CANCELLED, it's frozen, matching ServiceRecord's own
# append-only philosophy from that point forward.
OPEN_STATUSES = ("OPEN", "IN_PROGRESS", "QC")


class WorkOrderListView(TenantScopedAPIView):
    """GET/POST /api/vehicles/<vehicle_id>/work-orders/"""
    model = WorkOrder

    def get(self, request, vehicle_id):
        orders = self.get_queryset().filter(vehicle_id=vehicle_id).select_related("vehicle__customer")
        serializer = WorkOrderListSerializer(orders, many=True)
        return Response({"success": True, "count": orders.count(), "results": serializer.data})

    def post(self, request, vehicle_id):
        # Mirror-image guard of EstimateListView.post() — same real
        # gap, the other creation path: a vehicle already mid-repair
        # (an active WorkOrder) or already carrying a PENDING Estimate
        # shouldn't be able to get a second, independent WorkOrder
        # created directly. This is the real enforcement layer; the
        # frontend disables the "Buat Work Order" button proactively
        # too, but a slow double-click or a second browser tab must
        # still be caught here.
        #
        # Local import: apps.workorders has no other reason to depend
        # on apps.estimates at module level — Estimate.approve()
        # already established the convention of importing across
        # these two apps locally rather than at module scope.
        from apps.estimates.models import Estimate

        if self.get_queryset().filter(vehicle_id=vehicle_id, status__in=OPEN_STATUSES).exists():
            return Response(
                {"success": False, "message": "Kendaraan ini sudah punya work order aktif — selesaikan atau batalkan dulu sebelum membuat yang baru."},
                status=status.HTTP_409_CONFLICT,
            )
        if Estimate.objects.filter(vehicle_id=vehicle_id, status="PENDING").exists():
            return Response(
                {"success": False, "message": "Kendaraan ini punya estimasi yang menunggu persetujuan — selesaikan itu dulu sebelum membuat work order baru."},
                status=status.HTTP_409_CONFLICT,
            )

        payload = dict(request.data)
        payload["vehicle"] = vehicle_id
        serializer = WorkOrderSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            # WorkOrder.save() calls WorkOrderSequence.next_number(),
            # which uses select_for_update() — that requires an
            # active transaction to attach its row lock to. Every
            # OTHER write path in this file either has no number-
            # generation step at all, or (close()/cancel()) already
            # owns its own atomic() block internally. This is the one
            # spot that was missing it — caught in real usage, not by
            # the test suite, since Django's TestCase wraps every test
            # method in its own transaction automatically, which
            # accidentally hid the exact gap a real HTTP request
            # (running with no implicit transaction) exposed immediately.
            with transaction.atomic():
                order = serializer.save(created_by=request.user)
            return Response(
                {"success": True, "work_order": WorkOrderSerializer(order).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class WorkOrderDetailView(TenantScopedAPIView):
    """
    GET/PUT /api/work-orders/<id>/
    PUT is deliberately narrow — only odometer_km_intake, received_by,
    notes, assigned_to are writable, and only while the order is
    still open. Status changes go through the dedicated status/close/
    cancel endpoints below, since those carry real side effects PUT
    shouldn't hide.
    """
    model = WorkOrder

    def get(self, request, pk):
        order = self.get_object(pk)
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})

    def put(self, request, pk):
        order = self.get_object(pk)
        if order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan — tidak bisa diubah."},
                status=status.HTTP_409_CONFLICT,
            )
        allowed = {k: v for k, v in request.data.items() if k in ("odometer_km_intake", "received_by", "notes", "assigned_to")}
        serializer = WorkOrderSerializer(order, data=allowed, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "work_order": WorkOrderSerializer(order).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class WorkOrderJobTicketPdfView(TenantScopedAPIView):
    """
    GET /api/work-orders/<id>/job-ticket.pdf

    Made's own confirmed answer, 1 Aug: this is an internal, no-price
    shop-floor job ticket for the mechanic, printed the moment "Mulai
    Dikerjakan" is clicked — not before. That's a real, enforced
    gate here, not just a hidden frontend button: a WorkOrder that
    hasn't started yet has nothing real to print (no work_started_at
    to show, and printing an empty ticket early risks it going stale
    or getting handed to the wrong mechanic before the job is even
    assigned for real). Mirrors the same "backend is the real
    enforcement, frontend just disables proactively" split already
    established for the vehicle-lock guard (see EstimateListView.post
    and WorkOrderListView.post above).

    Returns a raw HttpResponse, not a DRF Response — same reasoning
    as EstimateQuotationPdfView: a real file, not JSON.
    """
    model = WorkOrder

    def get(self, request, pk):
        work_order = self.get_object(pk)
        # Chris's own catch, 1 Aug: WorkOrder.mark_started() is
        # deliberately a no-op for a WorkOrder with no Estimate
        # origin (see that method's own docstring) — work_started_at
        # stays null forever for a direct-entry WorkOrder even after
        # "Mulai Dikerjakan" is clicked. Gating this endpoint on
        # work_started_at would leave it permanently 409 for the
        # majority of real jobs. The real trigger is the status
        # transition itself (OPEN -> IN_PROGRESS), which fires
        # unconditionally regardless of Estimate origin — that's the
        # actual signal to gate on.
        if work_order.status == "OPEN":
            return Response(
                {"success": False, "message": "Job ticket tersedia setelah work order mulai dikerjakan."},
                status=status.HTTP_409_CONFLICT,
            )
        pdf_bytes = build_job_ticket_pdf(work_order, org_name=work_order.organization.name)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        # Sanitized the same way EstimateQuotationPdfView's own
        # filename is — no reason to trust a real plate number won't
        # ever carry a character a filesystem chokes on.
        safe_plate = "".join(c if c.isalnum() or c in " -_" else "_" for c in work_order.vehicle.plate_number)
        response["Content-Disposition"] = f'attachment; filename="WO_{work_order.number}_{safe_plate}.pdf"'
        return response


class WorkOrderStatusUpdateView(TenantScopedAPIView):
    """
    PATCH /api/work-orders/<id>/status/
    Only moves between OPEN/IN_PROGRESS/QC — plain pipeline progress,
    no side effects. DONE and CANCELLED are handled by the dedicated
    close/cancel endpoints below, since those actually do things
    (freeze into a ServiceRecord, reverse stock) that a bare status
    write must never trigger implicitly.

    The one real side effect this endpoint DOES carry: transitioning
    into IN_PROGRESS calls WorkOrder.mark_started(), Made's own
    "jam mulai dikerjakan" request — see that method's own docstring
    for exactly when it does (and deliberately doesn't) record
    anything. Included in the same update_fields as the status write
    itself, one save for one real event, not two.
    """
    model = WorkOrder

    def patch(self, request, pk):
        order = self.get_object(pk)
        new_status = request.data.get("status")
        if new_status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Gunakan endpoint /close/ atau /cancel/ untuk status ini."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        order.status = new_status
        update_fields = ["status", "updated_at"]
        if new_status == "IN_PROGRESS":
            order.mark_started()
            update_fields.append("work_started_at")
        order.save(update_fields=update_fields)
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})


class WorkOrderCloseView(TenantScopedAPIView):
    """
    POST /api/work-orders/<id>/close/ — freezes into a ServiceRecord.

    Accepts an optional service_date, so closing a Work Order can
    genuinely replace the old free-text quick-entry flow entirely —
    that flow's one real advantage was backdating a visit that
    happened days ago (a forgotten live entry, or migrating old
    paper records). WorkOrder.close() itself already accepted this
    parameter; it was just never exposed through the API until now.
    """
    model = WorkOrder

    def post(self, request, pk):
        order = self.get_object(pk)
        service_date = None
        raw_date = request.data.get("service_date")
        if raw_date:
            try:
                service_date = date.fromisoformat(raw_date)
            except ValueError:
                return Response(
                    {"success": False, "message": "Format tanggal tidak valid — gunakan YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            order.close(service_date=service_date, closed_by=request.user)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})


class WorkOrderCancelView(TenantScopedAPIView):
    """POST /api/work-orders/<id>/cancel/ — reverses any stock deducted."""
    model = WorkOrder

    def post(self, request, pk):
        order = self.get_object(pk)
        try:
            order.cancel()
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({"success": True, "work_order": WorkOrderSerializer(order).data})


class WorkOrderJobLineListView(TenantScopedAPIView):
    """GET/POST /api/work-orders/<work_order_id>/job-lines/"""
    model = WorkOrderJobLine

    def get(self, request, work_order_id):
        lines = self.get_queryset().filter(work_order_id=work_order_id)
        serializer = WorkOrderJobLineSerializer(lines, many=True)
        return Response({"success": True, "count": lines.count(), "results": serializer.data})

    def post(self, request, work_order_id):
        work_order = self._get_open_work_order(request, work_order_id)
        if work_order is None:
            return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        if work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        payload = dict(request.data)
        payload["work_order"] = work_order_id
        serializer = WorkOrderJobLineSerializer(data=payload)
        if serializer.is_valid():
            line = serializer.save()
            return Response(
                {"success": True, "job_line": WorkOrderJobLineSerializer(line).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _get_open_work_order(self, request, work_order_id):
        user = request.user
        if user.role == "super_admin":
            qs = WorkOrder.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = WorkOrder.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=work_order_id).first()


class WorkOrderJobLineToggleView(TenantScopedAPIView):
    """PATCH /api/work-orders/job-lines/<id>/toggle/ — flips is_done."""
    model = WorkOrderJobLine

    def patch(self, request, pk):
        line = self.get_object(pk)
        if line.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        # Chris's own catch, 2 Aug — caught live in production: a job
        # line could be marked "done" before the WorkOrder even left
        # OPEN, i.e. before "Mulai WO Sekarang" was ever clicked. Same
        # real-work-must-have-begun rule as WorkOrder.close() itself
        # rejecting OPEN — this is the checkbox-level equivalent, one
        # layer down. The frontend also stops rendering the checkbox
        # as clickable while OPEN, but that's the proactive layer;
        # this is what actually enforces it.
        if line.work_order.status == "OPEN":
            return Response(
                {"success": False, "message": 'Work order harus "Mulai Dikerjakan" dulu sebelum item bisa ditandai selesai.'},
                status=status.HTTP_409_CONFLICT,
            )
        line.is_done = not line.is_done
        line.save(update_fields=["is_done"])
        return Response({"success": True, "job_line": WorkOrderJobLineSerializer(line).data})


class WorkOrderJobLineAssignStageView(TenantScopedAPIView):
    """
    PATCH /api/work-orders/job-lines/<id>/assign-stage/
    Body: {"stage": "<uuid>"} or {"stage": null} to clear it.
    Separate from the plain create-with-stage path — lets a job line
    created before any stage existed get grouped in later, or moved
    between stages, without needing to delete and recreate it.
    """
    model = WorkOrderJobLine

    def patch(self, request, pk):
        line = self.get_object(pk)
        if line.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        stage_id = request.data.get("stage")
        if stage_id:
            stage = WorkOrderStage.objects.filter(id=stage_id, work_order=line.work_order).first()
            if stage is None:
                return Response(
                    {"success": False, "message": "Tahap tidak ditemukan untuk work order ini."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            line.stage = stage
        else:
            line.stage = None
        line.save(update_fields=["stage"])
        return Response({"success": True, "job_line": WorkOrderJobLineSerializer(line).data})


class WorkOrderJobLineDetailView(TenantScopedAPIView):
    """
    PUT/DELETE /api/work-orders/job-lines/<id>/

    Chris's own explicit ask, 2 Aug — caught live from a real screen-
    shot: a job line typed with a typo ("Pemasangan Kembal") had no
    way to ever be fixed. Only toggle() and assign-stage() existed
    before this; a description, once saved, was permanent, and there
    was no way to remove a wrongly-added line either.

    Mirrors WorkOrderMaterialLineDetailView's own DELETE pattern in
    shape, but genuinely simpler — a job line touches no inventory,
    so there's no stock to reverse and no "reason" to record.

    Locking uses WorkOrderJobLine.is_locked (see models.py) rather
    than repeating the OPEN_STATUSES check inline — that property
    also covers the stage-completed case toggle()/assign-stage()
    above don't currently check, which is deliberate: this is a new,
    stricter lock introduced specifically for edit/delete, not a
    silent tightening of those two pre-existing endpoints.
    """
    model = WorkOrderJobLine

    def put(self, request, pk):
        line = self.get_object(pk)
        if line.is_locked:
            return Response(
                {"success": False, "message": "Item ini sudah selesai atau work order sudah ditutup — tidak bisa diubah."},
                status=status.HTTP_409_CONFLICT,
            )
        description = request.data.get("description", "")
        if isinstance(description, str):
            description = description.strip()
        if not description:
            return Response(
                {"success": False, "errors": {"description": ["Deskripsi tidak boleh kosong."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        line.description = description
        line.save(update_fields=["description"])
        return Response({"success": True, "job_line": WorkOrderJobLineSerializer(line).data})

    def delete(self, request, pk):
        line = self.get_object(pk)
        if line.is_locked:
            return Response(
                {"success": False, "message": "Item ini sudah selesai atau work order sudah ditutup — tidak bisa dihapus."},
                status=status.HTTP_409_CONFLICT,
            )
        line.delete()
        return Response({"success": True, "message": "Item dihapus."})


class WorkOrderStageListView(TenantScopedAPIView):
    """
    GET/POST /api/work-orders/<work_order_id>/stages/
    Stages are purely optional, additive grouping — see
    WorkOrderStage's own docstring. Most Work Orders (routine,
    single-visit jobs) never create one at all.
    """
    model = WorkOrderStage

    def get(self, request, work_order_id):
        stages = self.get_queryset().filter(work_order_id=work_order_id).prefetch_related("job_lines")
        serializer = WorkOrderStageSerializer(stages, many=True)
        return Response({"success": True, "count": stages.count(), "results": serializer.data})

    def post(self, request, work_order_id):
        work_order = self._get_open_work_order(request, work_order_id)
        if work_order is None:
            return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        if work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        payload = dict(request.data)
        payload["work_order"] = work_order_id
        if not payload.get("sequence"):
            # A convenience default, not a strict identifier — sequence
            # only ever drives display ordering, never a uniqueness
            # guarantee, so a simple count-based next value is
            # deliberately not defended against a deleted-stage edge
            # case producing a duplicate. Cheap ordering hint, not
            # WorkOrder.number's own sequence discipline.
            payload["sequence"] = WorkOrderStage.objects.filter(work_order_id=work_order_id).count() + 1
        serializer = WorkOrderStageSerializer(data=payload)
        if serializer.is_valid():
            stage = serializer.save()
            return Response(
                {"success": True, "stage": WorkOrderStageSerializer(stage).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _get_open_work_order(self, request, work_order_id):
        user = request.user
        if user.role == "super_admin":
            qs = WorkOrder.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = WorkOrder.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=work_order_id).first()


class WorkOrderStageDetailView(TenantScopedAPIView):
    """
    GET/PUT/DELETE /api/work-orders/stages/<id>/
    PUT touches name/sequence/assigned_to/expected_duration_hours —
    started_at/completed_at still move exclusively through the
    dedicated start/complete endpoints below, same "a bare write
    must never hide a real side effect" discipline as
    WorkOrderDetailView's own PUT. assigned_to/expected_duration_hours
    are deliberately NOT required to set a stage in motion — Made's
    diagram showed real assignment, but nothing about starting or
    completing a stage should force data entry that isn't there yet,
    same "trust human judgment" reasoning as completing a stage never
    requiring all its job lines to be checked off first.
    """
    model = WorkOrderStage

    def get(self, request, pk):
        stage = self.get_object(pk)
        return Response({"success": True, "stage": WorkOrderStageSerializer(stage).data})

    def put(self, request, pk):
        stage = self.get_object(pk)
        if stage.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        allowed = {
            k: v for k, v in request.data.items()
            if k in ("name", "sequence", "assigned_to", "expected_duration_hours")
        }
        serializer = WorkOrderStageSerializer(stage, data=allowed, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "stage": WorkOrderStageSerializer(stage).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        stage = self.get_object(pk)
        if stage.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan — tahap tidak bisa dihapus."},
                status=status.HTTP_409_CONFLICT,
            )
        # Job lines under this stage are NOT deleted — SET_NULL on
        # WorkOrderJobLine.stage means they simply become unstaged
        # again, same as if they'd never been grouped at all. Real
        # checklist history never disappears just because its
        # organizational label did.
        stage.delete()
        return Response({
            "success": True,
            "message": "Tahap dihapus — item pekerjaan di dalamnya tetap ada, kembali menjadi tanpa tahap.",
        })


class WorkOrderStageStartView(TenantScopedAPIView):
    """POST /api/work-orders/stages/<id>/start/"""
    model = WorkOrderStage

    def post(self, request, pk):
        stage = self.get_object(pk)
        if stage.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            stage.start()
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        stage.save(update_fields=["started_at"])
        return Response({"success": True, "stage": WorkOrderStageSerializer(stage).data})


class WorkOrderStageCompleteView(TenantScopedAPIView):
    """POST /api/work-orders/stages/<id>/complete/"""
    model = WorkOrderStage

    def post(self, request, pk):
        stage = self.get_object(pk)
        if stage.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            stage.complete()
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        stage.save(update_fields=["started_at", "completed_at"])
        return Response({"success": True, "stage": WorkOrderStageSerializer(stage).data})


class WorkOrderMaterialLineListView(TenantScopedAPIView):
    """
    GET/POST /api/work-orders/<work_order_id>/material-lines/
    POST is where real-time stock deduction actually happens — see
    WorkOrderMaterialLine.save() in models.py.
    """
    model = WorkOrderMaterialLine

    def get(self, request, work_order_id):
        lines = self.get_queryset().filter(work_order_id=work_order_id).select_related("part")
        serializer = WorkOrderMaterialLineSerializer(lines, many=True)
        return Response({"success": True, "count": lines.count(), "results": serializer.data})

    def post(self, request, work_order_id):
        work_order = self._get_work_order(request, work_order_id)
        if work_order is None:
            return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        if work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan."},
                status=status.HTTP_409_CONFLICT,
            )
        payload = dict(request.data)
        payload["work_order"] = work_order_id
        serializer = WorkOrderMaterialLineSerializer(data=payload, context={"request": request})
        if serializer.is_valid():
            line = serializer.save()
            return Response(
                {"success": True, "material_line": WorkOrderMaterialLineSerializer(line).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _get_work_order(self, request, work_order_id):
        user = request.user
        if user.role == "super_admin":
            qs = WorkOrder.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = WorkOrder.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=work_order_id).first()


class WorkOrderMaterialLineDetailView(TenantScopedAPIView):
    """
    DELETE /api/work-orders/material-lines/<id>/
    Removing a material line before the WorkOrder closes must reverse
    the stock it already deducted — otherwise deleting a mistaken
    entry would leave stock permanently short for no reason. Reuses
    the same StockAdjustment mechanism as WorkOrder.cancel(), tagged
    "correction" rather than "work_order_cancelled" since this is a
    single-line fix, not a whole order being abandoned.
    """
    model = WorkOrderMaterialLine

    def delete(self, request, pk):
        line = self.get_object(pk)
        if line.work_order.status not in OPEN_STATUSES:
            return Response(
                {"success": False, "message": "Work order ini sudah selesai atau dibatalkan — baris tidak bisa dihapus."},
                status=status.HTTP_409_CONFLICT,
            )
        # Two real, distinct reasons a material line gets removed —
        # confirmed directly with Made: a customer cancelling an
        # already-installed part mid-repair (his actual described
        # scenario, e.g. a multi-day job where the car stays
        # overnight) is a genuinely different event from a mechanic
        # simply correcting a data-entry mistake, and deserves its
        # own honest label in the audit trail rather than both being
        # lumped under "correction". Defaults to "correction" if the
        # caller doesn't specify — the safer, more conservative
        # assumption when we don't actually know why.
        reason = request.data.get("reason")
        if reason not in ("correction", "customer_cancelled_part"):
            reason = "correction"
        with transaction.atomic():
            StockAdjustment.objects.create(
                organization=line.organization, part=line.part,
                quantity_change=line.quantity, reason=reason,
                notes=f"Baris material dihapus dari WO {line.work_order.number}",
            )
            line.delete()
        return Response({"success": True, "message": "Baris material dihapus, stok dikembalikan."})


class MechanicListView(TenantScopedAPIView):
    """GET/POST /api/mechanics/"""
    model = Mechanic

    def get(self, request):
        mechanics = self.get_queryset().order_by("name")
        serializer = MechanicSerializer(mechanics, many=True)
        return Response({"success": True, "count": mechanics.count(), "results": serializer.data})

    def post(self, request):
        org = self._resolve_org(request)
        if org is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = MechanicSerializer(data=request.data)
        if serializer.is_valid():
            mechanic = serializer.save(organization=org)
            return Response(
                {"success": True, "mechanic": MechanicSerializer(mechanic).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _resolve_org(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        return membership.organization if membership else None


class MechanicDetailView(TenantScopedAPIView):
    """
    GET/PUT /api/mechanics/<id>/
    Deliberately no DELETE — see Mechanic's own docstring in
    models.py. A mechanic who leaves the shop gets deactivated
    (is_active=False via this same PUT), not deleted, specifically
    because deleting would SET_NULL every historical
    WorkOrderStage.assigned_to they ever worked, silently erasing
    real "who did this" history.
    """
    model = Mechanic

    def get(self, request, pk):
        mechanic = self.get_object(pk)
        return Response({"success": True, "mechanic": MechanicSerializer(mechanic).data})

    def put(self, request, pk):
        mechanic = self.get_object(pk)
        serializer = MechanicSerializer(mechanic, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "mechanic": MechanicSerializer(mechanic).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


def _hours_elapsed(started_at):
    if started_at is None:
        return None
    return round((timezone.now() - started_at).total_seconds() / 3600, 1)


class DashboardSummaryView(TenantScopedAPIView):
    """
    GET /api/dashboard/summary/?period=today|week|month|year

    The concrete backend for all four of Made's numbered Owner
    Dashboard requirements from the 28 Jul meeting, aggregated in one
    call rather than four separate ones for a single screen. Most
    directly answers his own diagnosis of the real problem:
    "Masalah utama pd kontrol adalah pelacakan & pemeriksaan"
    (the main problem with control is tracking & checking).

    Deliberately does NOT use TenantScopedAPIView's usual
    self.get_queryset() pattern (which scopes through a single
    `model` attribute) — this view aggregates across three different
    models (Mechanic, WorkOrder, WorkOrderStage) in one response, so
    organization is resolved once, up front, the same explicit
    pattern already used by CustomerListView.post() and
    ContractImportUploadView, rather than forcing an artificial
    single-model queryset to stand in for all three.
    """
    model = WorkOrder  # nominal only — see docstring; not used for
    # get_queryset() here, just so TenantScopedAPIView's shared
    # permission plumbing still applies to this view.

    PERIOD_DAYS = {"today": 0, "week": 7, "month": 30, "year": 365}

    def get(self, request):
        org = self._resolve_org(request)
        if org is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        period = request.query_params.get("period", "today")
        if period not in self.PERIOD_DAYS:
            period = "today"
        since = self._period_start(period)

        active_mechanics = Mechanic.objects.filter(organization=org, is_active=True)
        # "Working right now" — a real mechanic currently assigned to
        # a stage that's genuinely in progress (started, not yet
        # completed). .distinct() at the DB level, not counted in
        # Python — the same mechanic assigned to two parallel stages
        # on different WorkOrders must only count once.
        working_mechanic_ids = (
            WorkOrderStage.objects
            .filter(organization=org, started_at__isnull=False, completed_at__isnull=True, assigned_to__isnull=False)
            .values_list("assigned_to_id", flat=True)
            .distinct()
        )

        vehicles_cleared = WorkOrder.objects.filter(
            organization=org, status="DONE", updated_at__gte=since,
        ).count()
        # updated_at is a safe, accurate "closed at" timestamp here —
        # WorkOrder.close() sets status/service_record/updated_at
        # together in its one save() call, and every write path
        # elsewhere in this app gates on OPEN_STATUSES, so nothing
        # ever touches a DONE WorkOrder again after that point.

        queued = WorkOrder.objects.filter(organization=org, status="OPEN").count()
        in_progress_qs = WorkOrder.objects.filter(organization=org, status="IN_PROGRESS").select_related("vehicle")
        in_progress = in_progress_qs.count()

        # is_overdue is a Python property, not a DB column — filtered
        # here in Python, not the queryset, same reasoning already
        # established for Vehicle.is_due_for_service: small,
        # per-shop-scale lists (already filtered to IN_PROGRESS only
        # above), simpler than duplicating threshold logic as a
        # queryset annotation.
        overdue_work_orders = [
            {
                "id": str(wo.id), "number": wo.number, "vehicle_plate": wo.vehicle.plate_number,
                "work_started_at": wo.work_started_at, "hours_elapsed": _hours_elapsed(wo.work_started_at),
            }
            for wo in in_progress_qs if wo.is_overdue
        ]

        stages_qs = (
            WorkOrderStage.objects
            .filter(organization=org, started_at__isnull=False, completed_at__isnull=True)
            .select_related("work_order")
        )
        overdue_stages = [
            {
                "id": str(s.id), "name": s.name,
                "work_order_id": str(s.work_order_id), "work_order_number": s.work_order.number,
                "started_at": s.started_at, "hours_elapsed": _hours_elapsed(s.started_at),
            }
            for s in stages_qs if s.is_overdue
        ]

        return Response({
            "success": True,
            "mechanics": {"active": active_mechanics.count(), "working": working_mechanic_ids.count()},
            "vehicles_cleared": {"count": vehicles_cleared, "period": period},
            "work_orders": {"queued": queued, "in_progress": in_progress},
            "overdue": {"work_orders": overdue_work_orders, "stages": overdue_stages},
        })

    def _resolve_org(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        return membership.organization if membership else None

    def _period_start(self, period):
        days = self.PERIOD_DAYS[period]
        if days == 0:
            return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return timezone.now() - timedelta(days=days)


class ActiveJobsView(TenantScopedAPIView):
    """
    GET /api/work-orders/active/
    B2 in the sprint review — a full roster of everything currently
    in motion across the shop, not just the overdue subset the Owner
    Dashboard's own summary already surfaces. Every WorkOrder still
    in OPEN_STATUSES, ordered longest-waiting-first — the most
    actionable ordering for exactly the kind of remote supervision
    Made's described wanting throughout this whole project.

    elapsed_since = work_started_at if set, else created_at — an
    honest approximation, not perfect precision: a direct-entry
    WorkOrder (no Estimate origin) never gets work_started_at
    populated even once IN_PROGRESS (see WorkOrder.mark_started()'s
    own docstring), so for that specific case this measures "time
    since the job was created" rather than "time actually in
    progress." Flagged here deliberately rather than silently
    treated as exact — there's no other real timestamp on the model
    to fall back to.
    """
    model = WorkOrder

    def get(self, request):
        work_orders = (
            self.get_queryset()
            .filter(status__in=OPEN_STATUSES)
            .select_related("vehicle", "vehicle__customer")
            .prefetch_related("stages", "stages__assigned_to")
        )

        results = []
        for wo in work_orders:
            current_stage = self._current_stage(wo)
            elapsed_since = wo.work_started_at or wo.created_at
            results.append({
                "id": str(wo.id),
                "number": wo.number,
                "vehicle_plate": wo.vehicle.plate_number,
                "customer_name": wo.vehicle.customer.name,
                "status": wo.status,
                "elapsed_since": elapsed_since,
                "elapsed_hours": _hours_elapsed(elapsed_since),
                "current_stage_name": current_stage.name if current_stage else None,
                "current_stage_mechanic": (
                    current_stage.assigned_to.name
                    if current_stage and current_stage.assigned_to else None
                ),
                "is_overdue": wo.is_overdue,
            })

        results.sort(key=lambda r: r["elapsed_hours"], reverse=True)
        return Response({"success": True, "count": len(results), "results": results})

    def _current_stage(self, wo):
        """
        The stage currently "in motion" — started but not completed.
        Returns None for a routine WorkOrder with no stages at all,
        or one where every stage is either not yet started or
        already completed. If more than one somehow qualifies (not
        enforced at the DB level, though normal usage shouldn't
        produce it), the most recently started one wins.
        """
        in_motion = [s for s in wo.stages.all() if s.started_at and not s.completed_at]
        if not in_motion:
            return None
        return max(in_motion, key=lambda s: s.started_at)
