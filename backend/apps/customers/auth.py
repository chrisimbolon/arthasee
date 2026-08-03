# =============================================================================
# === backend/apps/customers/auth.py ===
# =============================================================================
"""
Arthasee — Customer Portal Authentication (Fase 2.5)

Chris's own explicit call, 3 Aug: "Complete separation from
CustomUser is essential for security." A customer must never be able
to accidentally (or maliciously) end up with internal staff
permissions just because both systems happen to use JWTs.

Deliberately NOT built on rest_framework_simplejwt's own
User-model-based flow (that's tied to CustomUser, exactly what needs
avoiding here) — a plain PyJWT-signed token instead, carrying a
"customer_access" token_type claim that CustomerJWTAuthentication
requires explicitly. A CustomUser access token (issued by simplejwt)
has a completely different claim shape (no "customer_id", a different
"token_type") — there's no field-shape overlap that could let one
token type be mistaken for the other, and IsCustomerAuthenticated
below checks the resolved object is a real Customer instance, not
just "some request.user is set."

CUSTOMER_PORTAL_SECRET_KEY: falls back to settings.SECRET_KEY if not
explicitly configured, so this is buildable and testable right now
without a new required setting — but for real separation in
production, a genuinely distinct secret should be set. Add to
config/settings/base.py:
    CUSTOMER_PORTAL_SECRET_KEY = config("CUSTOMER_PORTAL_SECRET_KEY", default=SECRET_KEY)
"""
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from apps.service.models import Customer

CUSTOMER_ACCESS_TOKEN_LIFETIME = timedelta(days=30)


def _signing_key():
    # getattr with a fallback, not a hard settings.CUSTOMER_PORTAL_SECRET_KEY
    # reference — this must not crash a fresh checkout that hasn't
    # added the setting yet. See this module's own docstring for the
    # exact line to add for real separation in production.
    return getattr(settings, "CUSTOMER_PORTAL_SECRET_KEY", settings.SECRET_KEY)


def generate_customer_access_token(customer):
    """
    30-day lifetime, deliberately long — Chris's own scope call: no
    refresh-token/blacklist machinery for a v1 customer portal used
    infrequently (checking on a job, checking a fleet's vehicles).
    If a token expires, the customer just requests a fresh magic
    link — same low-friction spirit as the login itself, not a
    problem worth a second, more complex token system to avoid.
    """
    now = timezone.now()
    payload = {
        "token_type":  "customer_access",
        "customer_id": str(customer.id),
        "iat": int(now.timestamp()),
        "exp": int((now + CUSTOMER_ACCESS_TOKEN_LIFETIME).timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm="HS256")


class CustomerJWTAuthentication(BaseAuthentication):
    """
    Sets request.user to a real Customer model instance — deliberately
    NOT a CustomUser, and deliberately not given a fake is_authenticated
    property to make it "look like" one. IsCustomerAuthenticated below
    is the only permission class that should ever be paired with this;
    DRF's own built-in IsAuthenticated would crash on
    request.user.is_authenticated, since Customer has no such
    attribute — that crash-instead-of-silently-succeeding is
    deliberate, not an oversight, so a view can never end up
    accidentally treating a Customer as authenticated via the wrong
    permission class.
    """

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return None
        token = header[len("Bearer "):].strip()
        try:
            payload = jwt.decode(token, _signing_key(), algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Sesi sudah kadaluarsa — masuk kembali dengan link baru.")
        except jwt.InvalidTokenError:
            raise AuthenticationFailed("Token tidak valid.")

        if payload.get("token_type") != "customer_access":
            # Deliberately silent, not an error — a request carrying
            # some other kind of bearer token (e.g. a real CustomUser
            # token, on a shared browser/device) should fall through
            # to whatever other authentication is configured, not be
            # treated as a malformed customer request.
            return None

        try:
            customer = Customer.objects.get(id=payload["customer_id"])
        except Customer.DoesNotExist:
            raise AuthenticationFailed("Pelanggan tidak ditemukan.")

        return (customer, token)


class IsCustomerAuthenticated(BasePermission):
    """
    The only permission class that should ever pair with
    CustomerJWTAuthentication — checks request.user is genuinely a
    Customer instance, not just "truthy," so a stray CustomUser
    session on the same request object could never be mistaken for a
    valid customer login.
    """

    def has_permission(self, request, view):
        return isinstance(request.user, Customer)
