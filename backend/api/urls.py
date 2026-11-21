from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("geocode", views.geocode_view, name="geocode"),
    path("places/suggest", views.place_suggest, name="place-suggest"),
    path("places/lookup", views.place_lookup, name="place-lookup"),
    path("analyze", views.analyze, name="analyze"),
    path("heatmap", views.heatmap, name="heatmap"),
    path("alerts", views.alerts, name="alerts"),
    path("debug/routes", views.debug_routes, name="debug-routes"),
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
