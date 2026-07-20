# =============================================================================
# === backend/apps/authentication/views.py ===
# =============================================================================
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.organizations.models import Organization, OrganizationMembership

from .models import CustomUser
from .serializers import RegisterSerializer, UserSerializer


class RegisterView(APIView):
    """
    POST /api/auth/register/
    Wrapped in one atomic transaction on purpose — a user existing
    without an organization (or vice versa) is a broken account, not
    a partial success. Either all three rows get created, or none do.

    permission_classes = [AllowAny] is REQUIRED here, not optional —
    without it, this silently inherits the project's global default
    (IsAuthenticated), which would mean you'd have to already be
    logged in to register a new account. Discovered via a real 401
    failure across every RegisterViewTests case — this is exactly
    why that test gap mattered.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        with transaction.atomic():
            user = CustomUser.objects.create_user(
                email=data["email"], password=data["password"],
                full_name=data["full_name"], phone=data.get("phone", ""),
                role=CustomUser.Role.OWNER,
            )
            org = Organization.objects.create(name=data["organization_name"])
            OrganizationMembership.objects.create(
                organization=org, user=user, role="owner", is_active=True,
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            "success": True,
            "user":    UserSerializer(user).data,
            "tokens":  {"access": str(refresh.access_token), "refresh": str(refresh)},
        }, status=status.HTTP_201_CREATED)


class MeView(APIView):
    """GET /api/auth/me/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"success": True, "user": UserSerializer(request.user).data})
