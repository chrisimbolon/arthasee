# =============================================================================
# === backend/apps/contracts/views.py ===
# =============================================================================
from decimal import Decimal, InvalidOperation

from apps.core.views import TenantScopedAPIView
from rest_framework import status
from rest_framework.response import Response

from .models import Contract, ContractImport, TerminPeriod
from .parsing import (ContractParseError, diff_against_contract,
                      parse_hps_workbook)
from .serializers import (ContractImportSerializer, ContractListSerializer,
                          ContractSerializer, TerminPeriodSerializer)


class ContractListView(TenantScopedAPIView):
    """
    GET/POST /api/contracts/
    Creating a Contract here is deliberately lightweight — just the
    title/customer/fiscal_year/termin_count. It always starts with
    zero ContractVehicles; every vehicle and line item on it, even
    the very first, comes in exclusively through a ContractImport
    upload + apply(), never through this endpoint directly.
    """
    model = Contract

    def get(self, request):
        contracts = self.get_queryset().select_related("customer").order_by("-fiscal_year")
        serializer = ContractListSerializer(contracts, many=True)
        return Response({"success": True, "count": contracts.count(), "results": serializer.data})

    def post(self, request):
        org = self._resolve_org(request)
        if org is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ContractSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            contract = serializer.save(organization=org, created_by=request.user)
            # Confirmed with Chris: all termin slots generated upfront,
            # in full, the moment a Contract exists — not added one at
            # a time as they happen. See Contract.generate_termin_
            # periods()'s own docstring for why amount_expected starts
            # at 0 here rather than a real figure.
            contract.generate_termin_periods()
            return Response(
                {"success": True, "contract": ContractSerializer(contract).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _resolve_org(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        return membership.organization if membership else None


class ContractDetailView(TenantScopedAPIView):
    """
    GET /api/contracts/<id>/ — includes every ContractVehicle and its
    current ACTIVE line items: the exact "menu" a WorkOrder for one
    of these vehicles should be able to draw from.
    """
    model = Contract

    def get(self, request, pk):
        contract = self.get_object(pk)
        return Response({"success": True, "contract": ContractSerializer(contract).data})


class ContractImportUploadView(TenantScopedAPIView):
    """
    GET/POST /api/contracts/<contract_id>/imports/
    GET lists every import ever attempted for this contract (newest
    first, per ContractImport's own Meta.ordering) — the "Riwayat
    Import" history a contract-detail page needs. POST uploads and
    parses a new HPS/RAB Excel file.

    Never touches live ContractVehicle/ContractLineItem rows directly
    on upload — always creates a PENDING_REVIEW ContractImport, even
    for a brand-new Contract with no vehicles yet (that first
    upload's diff is simply all "added").
    """
    model = ContractImport

    def get(self, request, contract_id):
        contract = self._get_contract(request, contract_id)
        if contract is None:
            return Response(
                {"success": False, "message": "Contract tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        imports = ContractImport.objects.filter(contract=contract).order_by("-uploaded_at")
        serializer = ContractImportSerializer(imports, many=True)
        return Response({"success": True, "count": imports.count(), "results": serializer.data})

    def post(self, request, contract_id):
        contract = self._get_contract(request, contract_id)
        if contract is None:
            return Response(
                {"success": False, "message": "Contract tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            return Response(
                {"success": False, "message": "File Excel wajib diunggah."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        contract_import = ContractImport.objects.create(
            organization=contract.organization, contract=contract,
            original_file=uploaded_file, uploaded_by=request.user,
        )

        try:
            uploaded_file.seek(0)
            parsed = parse_hps_workbook(uploaded_file)
        except ContractParseError as e:
            contract_import.parse_error = str(e)
            contract_import.save(update_fields=["parse_error"])
            return Response(
                {
                    "success": False,
                    "message": "Gagal membaca file Excel — periksa apakah formatnya sesuai template.",
                    "contract_import": ContractImportSerializer(contract_import).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        diff = diff_against_contract(parsed, contract)
        contract_import.parsed_diff = diff
        contract_import.document_total = parsed.document_total
        contract_import.computed_total = parsed.computed_total
        contract_import.save(update_fields=["parsed_diff", "document_total", "computed_total"])

        return Response(
            {"success": True, "contract_import": ContractImportSerializer(contract_import).data},
            status=status.HTTP_201_CREATED,
        )

    def _get_contract(self, request, contract_id):
        # Deliberately not self.get_queryset() — that filters by
        # self.model, which is ContractImport here, not Contract. Same
        # pattern already used in apps.inventory.views/apps.invoicing.views
        # for the same reason.
        user = request.user
        if user.role == "super_admin":
            qs = Contract.objects.all()
        else:
            org_ids = user.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            qs = Contract.objects.filter(organization_id__in=org_ids)
        return qs.filter(pk=contract_id).first()


class ContractImportDetailView(TenantScopedAPIView):
    """GET /api/contract-imports/<id>/ — the diff review screen's data source."""
    model = ContractImport

    def get(self, request, pk):
        contract_import = self.get_object(pk)
        return Response({"success": True, "contract_import": ContractImportSerializer(contract_import).data})


class ContractImportApplyView(TenantScopedAPIView):
    """
    POST /api/contract-imports/<id>/apply/
    Body: {"confirmed_diff": {...}}

    confirmed_diff is the reviewed diff, WITH any fields a human
    filled in that the source document never provided — most notably
    Vehicle.manufacture_year on any "added_vehicles" entry, since that
    field is required and non-nullable on the existing Vehicle model
    but appears nowhere in the real HPS document reviewed for this
    project.
    """
    model = ContractImport

    def post(self, request, pk):
        contract_import = self.get_object(pk)
        confirmed_diff = request.data.get("confirmed_diff")
        if confirmed_diff is None:
            return Response(
                {"success": False, "message": "confirmed_diff wajib disertakan."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            contract_import.apply(confirmed_diff, applied_by=request.user)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        except KeyError as e:
            return Response(
                {"success": False, "message": f"Data yang dikonfirmasi kurang lengkap: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"success": True, "contract_import": ContractImportSerializer(contract_import).data})


class ContractImportRejectView(TenantScopedAPIView):
    """POST /api/contract-imports/<id>/reject/"""
    model = ContractImport

    def post(self, request, pk):
        contract_import = self.get_object(pk)
        try:
            contract_import.reject()
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({"success": True, "contract_import": ContractImportSerializer(contract_import).data})


class TerminPeriodRealizeView(TenantScopedAPIView):
    """
    POST /api/termin-periods/<id>/realize/
    Body: {"amount_received": "12000000", "received_at": "2026-08-15"}
    (received_at optional — defaults to today, same as
    WorkOrderCloseView's own optional service_date pattern.)

    The only write path onto amount_received/received_at at all —
    TerminPeriodSerializer marks both read-only, same "this only
    happens through its own explicit action" discipline already
    proven by WorkOrderStage.start()/complete().
    """
    model = TerminPeriod

    def post(self, request, pk):
        period = self.get_object(pk)
        raw_amount = request.data.get("amount_received")
        if raw_amount in (None, ""):
            return Response(
                {"success": False, "message": "Nilai realisasi wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # Converted explicitly, not left to save()'s own implicit
            # coercion — Decimal("not-a-number") raises
            # decimal.InvalidOperation, which is neither a ValueError
            # nor a TypeError, and would otherwise surface as an
            # unhandled 500 instead of a clean 400. Confirmed
            # directly, not assumed, before writing this guard.
            amount = Decimal(str(raw_amount))
        except InvalidOperation:
            return Response(
                {"success": False, "message": "Nilai realisasi tidak valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        received_at = request.data.get("received_at") or None
        period.record_realization(amount, received_date=received_at)
        return Response({"success": True, "termin_period": TerminPeriodSerializer(period).data})
