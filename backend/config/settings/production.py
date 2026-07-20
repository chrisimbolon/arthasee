# =============================================================================
# === backend/config/settings/production.py ===
# =============================================================================
from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE":   "django.db.backends.postgresql",
        "NAME":     config("DB_NAME"),
        "USER":     config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST":     config("DB_HOST", default="db"),
        "PORT":     config("DB_PORT", default="5432"),
    }
}

SECURE_SSL_REDIRECT       = True
SESSION_COOKIE_SECURE     = True
CSRF_COOKIE_SECURE        = True
SECURE_HSTS_SECONDS       = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
