# =============================================================================
# === backend/apps/letters/apps.py ===
# =============================================================================
from django.apps import AppConfig


class LettersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.letters"
    verbose_name = "Surat Masuk / Keluar"
