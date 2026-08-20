# =============================================================================
# === backend/apps/appointments/views.py ===
# =============================================================================
from datetime import date, timedelta

from apps.core.views import TenantScopedAPIView
from apps.customers.auth import (CustomerJWTAuthentication,
                                 IsCustomerAuthenticated)
from apps.service.models import Vehicle
from django.db.models import Count
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Appointment
from .serializers import (AppointmentAvailabilityDaySerializer,
                          AppointmentCreateSerializer, AppointmentSerializer,
                          TenantAppointmentSerializer)


def _parse_date(raw, default):
    if not raw:
        return default
    return date.fromisoformat(raw)


class AppointmentAvailabilityView(APIView):
    """
    GET /api/customer/appointments/availability/?since=&as_of=
    Drives the customer-facing calendar — which days are still
    bookable. Shop-wide fact, the same for every customer looking at
    the same day, so no per-customer filtering beyond authentication
    itself. Defaults to a 30-day forward window when no range is
    given.
    """
    authentication_classes = [CustomerJWTAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get(self, request):
        customer = request.user
        organization = customer.organization

        since = _parse_date(request.query_params.get("since"), default=date.today())
        as_of = _parse_date(request.query_params.get("as_of"), default=since + timedelta(days=30))

        counts = (
            Appointment.objects.filter(
                organization=organization, requested_date__gte=since, requested_date__lte=as_of,
                status__in=["CONFIRMED", "CONVERTED"],
            )
            .values("requested_date")
            .annotate(count=Count("id"))
        )
        booked_by_date = {row["requested_date"]: row["count"] for row in counts}

        days = []
        current = since
        while current <= as_of:
            booked = booked_by_date.get(current, 0)
            days.append({
                "date": current, "booked": booked,
                "capacity": organization.daily_appointment_capacity,
                "available": booked < organization.daily_appointment_capacity,
            })
            current += timedelta(days=1)

        return Response({"success": True, "days": AppointmentAvailabilityDaySerializer(days, many=True).data})


class AppointmentListCreateView(APIView):
    """
    GET/POST /api/customer/appointments/
    """
    authentication_classes = [CustomerJWTAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get(self, request):
        customer = request.user
        appointments = Appointment.objects.filter(customer=customer).select_related("vehicle").order_by("-requested_date")
        return Response({"success": True, "results": AppointmentSerializer(appointments, many=True).data})

    def post(self, request):
        customer = request.user
        serializer = AppointmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        # Real ownership check — a logged-in customer must only ever
        # be able to book for one of THEIR OWN vehicles, same
        # discipline as CustomerWorkOrderDetailView's own ownership
        # check elsewhere in this codebase.
        vehicle = Vehicle.objects.filter(pk=data["vehicle_id"], customer=customer).first()
        if vehicle is None:
            return Response({"success": False, "message": "Kendaraan tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        appointment = Appointment.create_if_available(
            customer=customer, vehicle=vehicle,
            requested_date=data["requested_date"], notes=data.get("notes", ""),
        )
        if appointment is None:
            return Response(
                {"success": False, "message": "Tanggal ini sudah penuh. Silakan pilih tanggal lain."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"success": True, "appointment": AppointmentSerializer(appointment).data},
            status=status.HTTP_201_CREATED,
        )


class AppointmentCancelView(APIView):
    """POST /api/customer/appointments/<id>/cancel/"""
    authentication_classes = [CustomerJWTAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def post(self, request, pk):
        customer = request.user
        appointment = Appointment.objects.filter(pk=pk, customer=customer).first()
        if appointment is None:
            return Response({"success": False, "message": "Janji temu tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        try:
            appointment.cancel()
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"success": True, "appointment": AppointmentSerializer(appointment).data})

class TenantAppointmentListView(TenantScopedAPIView):
    """
    GET /api/appointments/?all=1
    Staff-facing — Made and his mechanics need to see real, upcoming
    bookings to know who's actually coming in. Defaults to CONFIRMED
    only, the actionable set — CANCELLED has nothing left to act on,
    and CONVERTED already has its own real home, the resulting
    WorkOrder itself. ?all=1 shows every status for a full history
    view.
    """
    model = Appointment

    def get(self, request):
        appointments = self.get_queryset().select_related("customer", "vehicle").order_by("requested_date")
        if request.query_params.get("all") != "1":
            appointments = appointments.filter(status="CONFIRMED")
        return Response({"success": True, "results": TenantAppointmentSerializer(appointments, many=True).data})


class TenantAppointmentConvertView(TenantScopedAPIView):
    """
    POST /api/appointments/<id>/convert/
    The real missing link — Appointment.convert_to_work_order()
    has existed and been tested since the model was first built;
    this is the first thing that actually calls it. "Customer
    arrived" becomes a real WorkOrder, right here.
    """
    model = Appointment

    def post(self, request, pk):
        appointment = self.get_object(pk)
        try:
            work_order = appointment.convert_to_work_order(received_by=request.user.full_name)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "success": True,
            "appointment": TenantAppointmentSerializer(appointment).data,
            "work_order_id": str(work_order.id),
        })


class TenantAppointmentCancelView(TenantScopedAPIView):
    """
    POST /api/appointments/<id>/cancel/
    Staff-side cancellation — a customer calling in by phone rather
    than using the app. Same real cancel() method the customer-
    facing AppointmentCancelView above already uses; this exists
    purely because staff need their own authenticated path to it,
    not a different cancellation rule.
    """
    model = Appointment

    def post(self, request, pk):
        appointment = self.get_object(pk)
        try:
            appointment.cancel()
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"success": True, "appointment": TenantAppointmentSerializer(appointment).data})