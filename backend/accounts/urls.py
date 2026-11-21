from django.urls import path

from . import views

urlpatterns = [
    path("countries", views.countries, name="countries"),
    path("auth/signup", views.signup, name="signup"),
    path("auth/login", views.login, name="login"),
    path("auth/logout", views.logout, name="logout"),
    path("auth/me", views.me, name="me"),
    path("auth/password", views.change_password, name="change-password"),
    path("trips", views.trips, name="trips"),
    path("trips/import", views.import_trips, name="trips-import"),
    path("trips/<int:trip_id>", views.trip_detail, name="trip-detail"),
    path("admin/stats", views.admin_stats, name="admin-stats"),
]
