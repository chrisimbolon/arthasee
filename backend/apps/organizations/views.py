# =============================================================================
# === backend/apps/organizations/views.py ===
# =============================================================================
from datetime import date

from apps.accounting.coa import (seed_account_role_mappings,
                                 seed_asset_categories, seed_chart_of_accounts)
from apps.accounting.models import OpeningBalanceSession
from apps.accounting.periods import ensure_current_month_period
from PIL import Image
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (OrganizationSerializer,
                          OrganizationSettingsUpdateSerializer)


class MyOrganizationView(APIView):
    """
    GET/PATCH /api/organizations/mine/ — the current user's shop.

    PATCH added 5 Aug — real Organization Settings, letting an owner
    customize the auto-generated invoice_code (and shop display name)
    any time, rather than being stuck with whatever
    Organization._generate_invoice_code() produced at signup. See
    that method's own docstring for why registration itself never
    asks for this field at all.

    3 Sep 2026 — this is now ALSO the real save path for onboarding's
    own Step 1 (phone/address/invoice_code) — see
    OrganizationOnboardingCompleteView's own docstring below for why
    that responsibility moved here.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        if not membership:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({
            "success":      True,
            "organization": OrganizationSerializer(membership.organization).data,
            "role":         membership.role,
        })

    def patch(self, request):
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        if not membership:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Real role check — shop-wide settings like the invoice
        # prefix must only ever be changeable by the actual owner,
        # not any staff member who happens to hold a membership row.
        if membership.role != "owner":
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa mengubah pengaturan ini."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = OrganizationSettingsUpdateSerializer(
            membership.organization, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            "success":      True,
            "organization": OrganizationSerializer(membership.organization).data,
        })


class OrganizationLogoView(APIView):
    """
    POST/DELETE /api/organizations/mine/logo/ — upload or remove the
    shop's own logo, shown on this Settings page and on every
    generated invoice PDF (build_invoice_pdf in apps.invoicing.pdf).

    Separate endpoint from MyOrganizationView's own JSON PATCH, same
    "a real file doesn't mix with a JSON body" reasoning already
    established for SupplierInvoiceUploadAttachmentView. Owner-only —
    same role check as MyOrganizationView.patch(): a shop's brand
    identity is exactly the kind of setting a staff member must never
    be able to silently swap out from under the owner.

    6 Oct 2026 — real server-side validation, deliberately stricter
    than this codebase's three existing FileField upload endpoints
    (SupplierInvoice.attachment, ContractImport.original_file,
    IncomingLetter.file — none of which validate anything server-
    side today). Those sit behind a click-to-download link; this file
    renders INLINE, automatically, on two real, visible surfaces the
    moment it's uploaded — a bad or malicious file here is a much
    louder, more immediate failure than on those three.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
    MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB

    def _get_owned_organization(self, request):
        """
        Shared by post()/delete() below — same membership + owner-role
        lookup MyOrganizationView.patch() already uses, factored out
        rather than duplicated a third time.
        """
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        if not membership:
            return None, Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.role != "owner":
            return None, Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa mengubah logo."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return membership.organization, None

    def post(self, request):
        organization, error_response = self._get_owned_organization(request)
        if error_response:
            return error_response

        file_obj = request.FILES.get("logo")
        if file_obj is None:
            return Response(
                {"success": False, "message": "File logo tidak ditemukan pada request."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if file_obj.content_type not in self.ALLOWED_CONTENT_TYPES:
            return Response(
                {"success": False, "message": "Format file harus PNG, JPEG, atau WEBP."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if file_obj.size > self.MAX_SIZE_BYTES:
            return Response(
                {"success": False, "message": "Ukuran file maksimal 2 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Real content verification, not just the browser-supplied
        # Content-Type header above (trivially spoofed) — PIL actually
        # opens and verifies the file is a genuine, undamaged image
        # before it's ever saved as this org's logo. Image.verify()
        # consumes the file object's internal state, so file_obj is
        # explicitly rewound before it's handed to the model field —
        # the ORIGINAL uploaded bytes get saved, not anything PIL
        # touched.
        try:
            image = Image.open(file_obj)
            image.verify()
        except Exception:
            return Response(
                {"success": False, "message": "File bukan gambar yang valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        file_obj.seek(0)

        # Real cleanup, not an afterthought — every re-upload would
        # otherwise leave the previous file behind on disk forever,
        # since Django never deletes the old file on its own when a
        # FileField/ImageField is simply reassigned.
        old_logo = organization.logo
        organization.logo = file_obj
        organization.save(update_fields=["logo"])
        if old_logo:
            old_logo.delete(save=False)

        return Response({"success": True, "organization": OrganizationSerializer(organization).data})

    def delete(self, request):
        organization, error_response = self._get_owned_organization(request)
        if error_response:
            return error_response

        if organization.logo:
            organization.logo.delete(save=False)
            organization.logo = None
            organization.save(update_fields=["logo"])

        return Response({"success": True, "organization": OrganizationSerializer(organization).data})


class OrganizationOnboardingCompleteView(APIView):
    """
    POST /api/organizations/mine/complete-onboarding/ — no payload.

    3 Sep 2026 — REDESIGNED for the Opening Balance wizard becoming a
    real, mandatory Step 2 after the profile step (Chris's own
    confirmed direction). Previously this single call both saved
    phone/address/invoice_code AND flipped onboarding_completed —
    correct for a one-step gate, but a real gap once a genuine Step 2
    existed: a browser refresh mid-Step-2 would have nothing
    persisted to tell the gate "Step 1 is already done, skip straight
    to Step 2" — it would just re-show Step 1 from scratch, or worse,
    with the OLD contract, there was no Step 2 to return to at all.

    Real fix: Step 1 now saves phone/address/invoice_code via the
    existing, plain MyOrganizationView.patch() path (through
    OrganizationSettingsUpdateSerializer, already proven, no new
    serializer needed) — WITHOUT touching onboarding_completed. This
    endpoint's only remaining job is the final, explicit flag flip,
    guarded by a real check that Step 1's own data genuinely exists
    first. Called identically from BOTH of Step 2's real exit paths
    (a posted OpeningBalanceSession, or the "Bengkel Baru — Mulai
    dari Nol" path for a shop with no prior history) — which path
    happened is entirely orthogonal to this call; neither passes a
    payload, and neither needs to.

    OnboardingCompleteSerializer is now dead code, removed — its one
    real job (require + save phone/address/invoice_code in the same
    call as the flag flip) no longer matches how this flow works.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        if not membership:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.role != "owner":
            return Response(
                {"success": False, "message": "Hanya pemilik bengkel yang bisa menyelesaikan pengaturan awal."},
                status=status.HTTP_403_FORBIDDEN,
            )

        org = membership.organization
        # Real, server-side guard — not just trusted from frontend
        # step ordering. A Step 2 call arriving with Step 1's own
        # data genuinely missing (e.g. a stray direct API call, or a
        # future frontend bug skipping straight to Step 2) must never
        # silently complete onboarding for a shop with no real
        # profile on record — same "a real business rule deserves a
        # real server-side guarantee" reasoning the original 29 Aug
        # design already established for this exact endpoint.
        if not (org.phone and org.address and org.invoice_code):
            return Response(
                {"success": False, "message": "Lengkapi profil bengkel (Langkah 1) terlebih dahulu."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 18 Sep 2026 -- Brand-New Workshop Readiness fallout. Real
        # fix -- see this file's own top-of-diff note for the full
        # story. seed_chart_of_accounts()/ensure_current_month_period()
        # are both real, already-idempotent functions (seed_coa's own
        # management command already relies on that idempotency for
        # its own safe re-run guarantee) -- calling them
        # unconditionally here, every time onboarding completes, is
        # safe even if a prior call already seeded them, and closes
        # the COA_NOT_SEEDED / NO_ACCOUNTING_PERIOD blocks a genuinely
        # fresh signup would otherwise still hit.
        #
        # The Opening Position pillar: if no OpeningBalanceSession
        # exists at all yet, this genuinely IS the "brand-new shop,
        # no prior history" case confirm_zero() exists for -- create
        # one and confirm it right here, at the one real, shared
        # point both of Step 2's exit paths already funnel through.
        # A session that already exists (the real Opening Balance
        # path, already POSTED via OpeningBalanceStep's own
        # handlePost) is left completely untouched by this.
        seed_chart_of_accounts(org)
        seed_asset_categories(org)
        seed_account_role_mappings(org)
        ensure_current_month_period(org)
        # 28 Sep 2026 — CORRECTION to the comment above: an existing session is
        # NOT always already POSTED. An empty DRAFT (started, then abandoned —
        # e.g. "Isi Saldo Awal" clicked, then back to Tipe Bengkel and Bengkel
        # Baru chosen) used to be left untouched here, so onboarding_completed
        # flipped to True while the readiness gate still said
        # OPENING_BALANCE_NOT_RESOLVED. ensure_zero_opening_position() resolves
        # every case in one place (see its own docstring): create+confirm when
        # there is none, confirm an empty draft, leave a POSTED or already-
        # confirmed session alone, and REFUSE a draft holding real lines — the
        # refusal is returned as a clean 400 BEFORE onboarding_completed is
        # flipped, never a silent discard of data entered in good faith.
        try:
            OpeningBalanceSession.ensure_zero_opening_position(
                organization=org, start_date=date.today(), confirmed_by=request.user,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        org.onboarding_completed = True
        org.save(update_fields=["onboarding_completed"])
        return Response({
            "success":      True,
            "organization": OrganizationSerializer(org).data,
        })
