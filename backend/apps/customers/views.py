# =============================================================================
# === backend/apps/customers/views.py ===
# =============================================================================
from datetime import timedelta

from apps.core.views import TenantScopedAPIView
from apps.service.models import Customer, Vehicle
from apps.workorders.models import WorkOrder
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import (CustomerJWTAuthentication, IsCustomerAuthenticated,
                   generate_customer_access_token)
from .email import send_magic_link_email
from .models import MagicLinkToken, TrackingLink
from .payload import build_work_order_tracking_payload
from .serializers import (CustomerSelfRegistrationSerializer,
                          CustomerSessionSerializer,
                          CustomerWorkOrderSummarySerializer,
                          MagicLinkRequestSerializer,
                          MagicLinkVerifySerializer, PublicTrackingSerializer,
                          TrackingLinkSerializer)
from .tenant import get_customer_portal_organization

# Mirrors WorkOrder.STATUS_CHOICES' own labels — duplicated rather
# than imported, since this is customer-facing copy and the two are
# allowed to diverge on wording without that being a bug (e.g. if
# Made ever wants friendlier public-facing status text later).
STATUS_LABEL = {
    "OPEN": "Terbuka", "IN_PROGRESS": "Dikerjakan", "QC": "Pemeriksaan Kualitas",
    "DONE": "Selesai", "CANCELLED": "Dibatalkan",
}


class TrackingLinkListView(TenantScopedAPIView):
    """
    GET/POST /api/work-orders/<work_order_id>/tracking-links/
    Internal, authenticated — Made/SA generates a link here, then
    copies it into WhatsApp by hand. Deliberately manual, matching
    the same "no automated sending" discipline already established
    for Estimasi/Invoice PDF downloads — B3 (automated WhatsApp) is
    still on hold.
    """
    model = TrackingLink

    def get(self, request, work_order_id):
        links = self.get_queryset().filter(work_order_id=work_order_id)
        return Response({"success": True, "results": TrackingLinkSerializer(links, many=True).data})

    def post(self, request, work_order_id):
        work_order = get_object_or_404(WorkOrder, pk=work_order_id)
        # Same tenant-scoping discipline as everywhere else — a user
        # from a different org must never be able to mint a tracking
        # link for a WorkOrder they can't even see.
        if request.user.role != "super_admin":
            org_ids = request.user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            if work_order.organization_id not in org_ids:
                return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)
        link = TrackingLink.objects.create(
            organization=work_order.organization, work_order=work_order, created_by=request.user,
        )
        return Response({"success": True, "tracking_link": TrackingLinkSerializer(link).data}, status=status.HTTP_201_CREATED)


class TrackingLinkRevokeView(TenantScopedAPIView):
    """POST /api/tracking-links/<id>/revoke/ — leaked link, wrong
    person, contract ended, whatever the real reason. The WorkOrder
    itself is never touched; only this one link stops working."""
    model = TrackingLink

    def post(self, request, pk):
        link = self.get_object(pk)
        link.is_revoked = True
        link.save(update_fields=["is_revoked"])
        return Response({"success": True, "tracking_link": TrackingLinkSerializer(link).data})


class PublicTrackingView(APIView):
    """
    GET /api/track/<token>/

    The ONLY unauthenticated endpoint in this entire codebase. Every
    other view in this project assumes a real, logged-in CustomUser;
    this one deliberately doesn't, since the entire point of Fase 2
    v1 is zero-login tracking. AllowAny is safe here specifically
    BECAUSE this view returns a hand-built, whitelisted payload (see
    PublicTrackingSerializer) rather than ever serializing a real
    model instance wholesale — there's no path for an internal-only
    field to leak here just by existing on WorkOrder/Vehicle/Invoice.
    """
    permission_classes = [AllowAny]

    def get(self, request, token):
        link = TrackingLink.objects.filter(token=token, is_revoked=False).select_related(
            "work_order__vehicle", "work_order__assigned_to",
        ).first()
        if link is None:
            # Deliberately the same generic message whether the token
            # never existed or was revoked — a public endpoint must
            # never confirm or deny which case it is.
            return Response(
                {"success": False, "message": "Link tidak ditemukan atau sudah tidak berlaku."},
                status=status.HTTP_404_NOT_FOUND,
            )

        link.record_view()
        # Shared with CustomerWorkOrderDetailView below (Fase 2.5) —
        # see payload.py's own docstring for why this is a plain
        # function, not duplicated whitelist logic in two views.
        payload = build_work_order_tracking_payload(link.work_order)
        return Response({"success": True, "tracking": PublicTrackingSerializer(payload).data})


class CustomerMagicLinkRequestView(APIView):
    """
    POST /api/customer-auth/magic-link/
    Fase 2.5 — step 1 of login. Body: {"email": "..."}.

    Real delivery via Resend (email.py), wired in 3 Aug — Chris's own
    choice over SendGrid. Until RESEND_API_KEY is actually configured
    (no API key/domain set up yet as of this writing), send_magic_link_
    email() fails soft and this view falls back to returning the raw
    token directly in the response, but ONLY in DEBUG — see the
    dev_token logic below, which self-eliminates the moment real
    sending genuinely works, no further code change needed then.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MagicLinkRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"].strip().lower()
        # .first(), not .get() — Customer.email has no unique
        # constraint (a real, known v1 limitation: the same person
        # could in principle be a Customer under this email at more
        # than one Arthasee-powered shop). Picks the first match
        # rather than trying to disambiguate — worth a real decision
        # later if that scenario ever actually comes up, not solved
        # here on a guess.
        customer = Customer.objects.filter(email__iexact=email).first() if email else None

        dev_token = None
        if customer is not None:
            link = MagicLinkToken.objects.create(
                organization=customer.organization, customer=customer,
                expires_at=timezone.now() + timedelta(minutes=15),
            )
            # Resend, wired in 3 Aug (Chris's own choice over
            # SendGrid) — see email.py's own docstring. Fails soft:
            # if RESENaD_API_KEY isn't configured yet (or a real send
            # fails), send_magic_link_email() logs it and returns
            # False, but this view's own response never changes
            # either way — same reasoning as everywhere else here,
            # never let the caller learn anything from whether the
            # send succeeded.
            sent = send_magic_link_email(customer, link.token)
            # dev_token only ever appears when a real email genuinely
            # did NOT go out — not the original plan (which was to
            # remove this passthrough entirely once real delivery
            # existed), reconsidered: that plan would've needed a
            # manual code change to actually enforce, easy to forget.
            # This version self-eliminates instead — the moment
            # RESEND_API_KEY is real and sending works, `sent` is
            # True and dev_token is never populated, DEBUG or not, no
            # further action needed. Until then, local development
            # still works via this same path without a real inbox.
            if not sent and settings.DEBUG:
                dev_token = link.token

        # Deliberately the SAME response whether the email matched a
        # real Customer or not — never confirm or deny whether an
        # email is registered, same reasoning as PublicTrackingView's
        # own generic 404.
        response_data = {"success": True, "message": "Jika email terdaftar, link masuk telah dikirim."}
        if dev_token:
            response_data["dev_token"] = dev_token
        return Response(response_data)


class CustomerMagicLinkVerifyView(APIView):
    """
    POST /api/customer-auth/magic-link/verify/
    Fase 2.5 — step 2 of login. Body: {"token": "..."}. Single-use —
    MagicLinkToken.mark_used() means clicking the same link twice
    (a forwarded email, a stale browser tab) fails the second time,
    same real-world expectation as any other magic-link flow.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MagicLinkVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        link = MagicLinkToken.objects.select_related("customer").filter(
            token=serializer.validated_data["token"],
        ).first()
        if link is None or not link.is_valid:
            return Response(
                {"success": False, "message": "Link tidak valid atau sudah kadaluarsa."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        link.mark_used()
        customer = link.customer
        access_token = generate_customer_access_token(customer)
        session = {"access": access_token, "name": customer.name, "email": customer.email}
        return Response({"success": True, "session": CustomerSessionSerializer(session).data})

class CustomerSelfRegistrationView(APIView):
    """
    POST /api/customer-auth/register/
    Body: {"full_name": ..., "phone": ..., "email": ..., "plate_number": ...}

    Made's own confirmed decision (mandatory login, no guest
    checkout) surfaced a real gap: the existing magic-link flow only
    ever LOOKS UP an existing Customer, never creates one — a
    genuine first-time visitor had no way in at all. This endpoint
    is that missing path.

    Organization is resolved via get_customer_portal_organization(),
    never from any client-supplied value — single-deployment-per-
    shop for now, see tenant.py's own docstring for what changes
    when this becomes real multi-tenant subdomain routing later.

    Defense in depth: the real intended flow always checks
    CustomerMagicLinkRequestView FIRST, only showing the
    registration form when that lookup comes back empty — but this
    view re-checks for an existing Customer with the same email in
    the SAME organization anyway, before creating anything. A direct
    call to this endpoint (buggy client, stale frontend state, or
    someone poking the API directly) must never create a duplicate
    Customer for a real person who already has an account. If one
    already exists, this behaves exactly like a normal login request
    instead — the submitted plate_number is deliberately ignored in
    that case, no vehicle side effect on what's really just a
    misrouted login attempt — never a silent no-op, never an error
    revealing whether the email was already registered, same "never
    confirm or deny" discipline as CustomerMagicLinkRequestView's
    own response shape. Verified by hand across all three real cases
    (new registration, duplicate email, plate conflict) before this
    was written.

    Vehicle.plate_number is unique per organization (a real DB
    constraint) — a plate that already exists for this org is
    rejected with a clear message BEFORE attempting to create
    anything, never left to surface as a raw IntegrityError.

    Missing Vehicle fields (manufacture_year, vehicle_type, model)
    get honest, clearly-flagged placeholder values — Chris's own
    explicit call: real intake staff fills these in properly when
    the customer's actual appointment converts into a real
    WorkOrder, not guessed at here.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        organization = get_customer_portal_organization()
        if organization is None:
            return Response(
                {"success": False, "message": "Portal pelanggan belum dikonfigurasi dengan benar."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = CustomerSelfRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        email = data["email"]

        existing_customer = Customer.objects.filter(organization=organization, email__iexact=email).first()

        if existing_customer is not None:
            customer = existing_customer
        else:
            plate_conflict = Vehicle.objects.filter(
                organization=organization, plate_number=data["plate_number"],
            ).exists()
            if plate_conflict:
                return Response(
                    {
                        "success": False,
                        "message": (
                            "Plat nomor ini sudah terdaftar di sistem kami. "
                            "Silakan hubungi bengkel untuk verifikasi akun Anda."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                customer = Customer.objects.create(
                    organization=organization,
                    name=data["full_name"],
                    phone=data["phone"],
                    email=email,
                )
                Vehicle.objects.create(
                    customer=customer,
                    plate_number=data["plate_number"],
                    manufacture_year=0,
                    vehicle_type="UNKNOWN",
                    model="Belum diisi",
                )

        link = MagicLinkToken.objects.create(
            organization=customer.organization, customer=customer,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        sent = send_magic_link_email(customer, link.token)

        # Same self-eliminating dev_token pattern as
        # CustomerMagicLinkRequestView — appears only when a real
        # send genuinely did not go out, DEBUG or not, no further
        # action needed once real sending works.
        dev_token = None
        if not sent and settings.DEBUG:
            dev_token = link.token

        response_data = {
            "success": True,
            "message": "Pendaftaran berhasil — link masuk telah dikirim ke email Anda.",
        }
        if dev_token:
            response_data["dev_token"] = dev_token
        return Response(response_data, status=status.HTTP_201_CREATED)

class CustomerWorkOrdersListView(APIView):
    """
    GET /api/customer/work-orders/
    Fase 2.5 dashboard — the real reason accounts exist over one-off
    tracking links: a fleet client's full vehicle list in one place.
    Active (OPEN/IN_PROGRESS/QC) and history (DONE/CANCELLED) split
    server-side, matching Chris's own confirmed "active first, history
    behind a tab" scope — the frontend doesn't have to re-derive that
    split from a flat list.
    """
    authentication_classes = [CustomerJWTAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get(self, request):
        customer = request.user  # a real Customer instance — see auth.py
        # Filtering by customer_id explicitly, not the model instance
        # — functionally identical to vehicle__customer=customer
        # (Django resolves both to the same SQL), just marginally
        # more explicit. The real bug behind an earlier test failure
        # here turned out to be in the TEST's expected count, not this
        # filter — see CustomerWorkOrdersListViewTests.test_only_
        # returns_this_customers_own_work_orders' own comment for the
        # real story.
        work_orders = WorkOrder.objects.filter(vehicle__customer_id=customer.id).select_related(
            "vehicle",
        ).order_by("-created_at")

        def summarize(qs):
            return CustomerWorkOrderSummarySerializer([
                {
                    "id": str(wo.id),
                    "work_order_number": wo.number,
                    "status": STATUS_LABEL.get(wo.status, wo.status),
                    "vehicle_plate": wo.vehicle.plate_number,
                    "vehicle_model": wo.vehicle.model,
                    "created_at": wo.created_at,
                }
                for wo in qs
            ], many=True).data

        active = [wo for wo in work_orders if wo.status in ("OPEN", "IN_PROGRESS", "QC")]
        history = [wo for wo in work_orders if wo.status in ("DONE", "CANCELLED")]
        return Response({"success": True, "active": summarize(active), "history": summarize(history)})


class CustomerWorkOrderDetailView(APIView):
    """
    GET /api/customer/work-orders/<id>/
    The same real, whitelisted payload as PublicTrackingView (see
    payload.py) — just reached via a logged-in Customer session
    instead of a one-off token. Real tenant/ownership check: a
    logged-in customer must only ever be able to open a WorkOrder for
    one of THEIR OWN vehicles, never any WorkOrder id they happen to
    guess or construct — same discipline as every other ownership
    check in this codebase, just enforced against Customer instead of
    organization membership.
    """
    authentication_classes = [CustomerJWTAuthentication]
    permission_classes = [IsCustomerAuthenticated]

    def get(self, request, pk):
        customer = request.user
        work_order = WorkOrder.objects.filter(
            pk=pk, vehicle__customer_id=customer.id,
        ).select_related("vehicle", "assigned_to").first()
        if work_order is None:
            return Response({"success": False, "message": "Work order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        payload = build_work_order_tracking_payload(work_order)
        return Response({"success": True, "tracking": PublicTrackingSerializer(payload).data})
