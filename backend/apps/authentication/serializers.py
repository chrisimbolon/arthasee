# =============================================================================
# === backend/apps/authentication/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CustomUser
        fields = ["id", "email", "full_name", "phone", "role"]
        read_only_fields = ["id", "role"]


class RegisterSerializer(serializers.Serializer):
    """
    POST /api/auth/register/
    Creates a CustomUser, a new Organization for them, and the
    OrganizationMembership linking the two, all in one call — a shop
    owner signing up shouldn't need to know these are three separate
    tables under the hood.
    """
    email          = serializers.EmailField()
    password       = serializers.CharField(write_only=True, min_length=8)
    full_name      = serializers.CharField(max_length=200)
    phone          = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    organization_name = serializers.CharField(max_length=200, help_text="Nama bengkel")

    def validate_email(self, value):
        if CustomUser.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email sudah terdaftar.")
        return value
