"""URL routing for OpenKinetics Data."""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"ok": True, "service": "openkinetics-data"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/", include("data_api.urls")),
    path("sequence-artifacts/", include("data_api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.RELEASES_URL_BASE.rstrip("/") + "/",
        document_root=settings.RELEASES_ROOT,
    )
