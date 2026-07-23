# =============================================================================
# === backend/config/urls.py ===
# =============================================================================
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),

    path("api/auth/",          include("apps.authentication.urls")),
    path("api/organizations/", include("apps.organizations.urls")),
    path("api/",               include("apps.service.urls")),
    path("api/",               include("apps.inventory.urls")),
    path("api/",               include("apps.invoicing.urls")),
    path("api/",               include("apps.workorders.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
