from django.urls import path

from . import views

urlpatterns = [
    path("stats/", views.stats, name="stats"),
    path("releases/", views.releases, name="releases"),
    path("releases/latest/", views.release_latest, name="release-latest"),
    path("releases/<slug:release_id>/", views.release_detail, name="release-detail"),
    path("measurements/", views.measurements, name="measurements"),
    path("measurements/<str:record_key>/", views.measurement_record, name="measurement-record"),
    path("search/", views.search, name="search"),
    path("facets/", views.facets, name="facets"),
    path("sequences/<str:sequence_id>/", views.sequence_detail, name="sequence-detail"),
    path(
        "sequences/<str:sequence_id>/artifacts/<str:artifact_key>/",
        views.sequence_artifact_download,
        name="sequence-artifact-download",
    ),
    path("substrates/<str:substrate_id>/", views.substrate_detail, name="substrate-detail"),
    path("downloads/", views.downloads, name="downloads"),
]
