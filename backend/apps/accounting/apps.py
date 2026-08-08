# =============================================================================
# === backend/apps/accounting/apps.py ===
# =============================================================================
from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"
    verbose_name = "Accounting"

    def ready(self):
        """
        Subscribes AccountingEventHandler to the shared event bus
        once, at Django startup. Imports are local, not module-level
        — apps.py is loaded very early in Django's own startup
        sequence, before every app's models are necessarily ready;
        importing apps.accounting.handlers (which imports
        apps.accounting.models) at module level here risks
        AppRegistryNotReady. Standard Django pattern for this exact
        situation, not a workaround specific to this codebase.
        """
        from apps.accounting.handlers import AccountingEventHandler
        from apps.core.events.bus import default_bus

        default_bus.subscribe(AccountingEventHandler())
