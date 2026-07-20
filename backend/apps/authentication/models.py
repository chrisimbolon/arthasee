# =============================================================================
# === backend/apps/authentication/models.py ===
# =============================================================================
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email wajib diisi.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "super_admin")
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Deliberately minimal roles for Phase 1 — "owner" (shop staff,
    default) and "super_admin" (platform-level access, matches
    TenantScopedAPIView's bypass check). Nothing about mechanics,
    multi-level shop staff hierarchy, or per-technician access was on
    the handwritten spec — inventing that now would be exactly the
    premature complexity every DevelopIndo roadmap has avoided. Add
    real roles when a real need for them shows up, not before.
    """
    class Role(models.TextChoices):
        OWNER       = "owner",       "Pemilik Bengkel"
        SUPER_ADMIN = "super_admin", "Super Admin"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email      = models.EmailField(unique=True)
    full_name  = models.CharField(max_length=200, verbose_name="Nama Lengkap")
    phone      = models.CharField(max_length=20, blank=True, verbose_name="Nomor Telepon")
    role       = models.CharField(max_length=20, choices=Role.choices, default=Role.OWNER)
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name        = "User"
        verbose_name_plural  = "Users"

    def __str__(self):
        return self.email
