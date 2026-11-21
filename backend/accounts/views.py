"""Accounts API (A6-A9): sign-up / sign-in, profile, saved trips, staff statistics.

Authorization:
* `/api/auth/me*`, `/api/auth/logout`, `/api/trips*` need a signed-in user.
* A user only ever sees and changes their own trips: every query is filtered by
  `user=request.user`, so another user's trip id answers 404 (its existence is not revealed).
* `/api/admin/stats` needs a staff account (403 otherwise).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from api.errors import ApiError
from api.throttles import scoped
from truckrisk_schemas import iso_z

from .countries import CONTINENTS, COUNTRIES
from .models import MAX_SAVED_TRIPS, AuthToken, SavedTrip, User
from .serializers import (
    DeleteAccountSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    ProfileSerializer,
    SavedTripSerializer,
    SignupSerializer,
    TripImportSerializer,
    user_dict,
)


class InvalidCredentials(ApiError):
    status = 401
    code = "INVALID_CREDENTIALS"


def _session(user: User, status_code: int = 200) -> Response:
    token, raw = AuthToken.issue(user)
    return Response(
        {"token": raw, "expires_at": iso_z(token.expires_at), "user": user_dict(user)},
        status=status_code,
    )


@api_view(["GET"])
def countries(request: Request) -> Response:
    """Country picker data: ISO code, name, continent."""
    return Response({
        "continents": list(CONTINENTS),
        "countries": [{"code": c, "name": n, "continent": k} for c, (n, k) in COUNTRIES.items()],
    })


@api_view(["POST"])
@throttle_classes([scoped("auth")])
def signup(request: Request) -> Response:
    ser = SignupSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    v = ser.validated_data
    user = User.objects.create_user(v["email"], v["password"], name=v["name"], country=v["country"])
    return _session(user, status.HTTP_201_CREATED)


@api_view(["POST"])
@throttle_classes([scoped("auth")])
def login(request: Request) -> Response:
    ser = LoginSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = authenticate(request._request, email=ser.validated_data["email"].strip().lower(),
                        password=ser.validated_data["password"])
    if user is None:  # same answer for unknown email and wrong password
        raise InvalidCredentials("Email or password is incorrect.")
    return _session(user)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request: Request) -> Response:
    """Revokes the token used for this request (signs out this device only)."""
    request.auth.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def me(request: Request) -> Response:
    user: User = request.user
    if request.method == "PATCH":
        ser = ProfileSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        for field, value in ser.validated_data.items():
            setattr(user, field, value)
        user.save(update_fields=list(ser.validated_data) or None)
    elif request.method == "DELETE":
        ser = DeleteAccountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if not user.check_password(ser.validated_data["password"]):
            raise InvalidCredentials("Password is incorrect.", {"field": "password"})
        user.delete()  # cascades to tokens and saved trips
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response({"user": user_dict(user)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([scoped("auth")])
def change_password(request: Request) -> Response:
    """Changes the password and signs out every other device."""
    ser = PasswordChangeSerializer(data=request.data, context={"user": request.user})
    ser.is_valid(raise_exception=True)
    user: User = request.user
    user.set_password(ser.validated_data["new_password"])
    user.save(update_fields=["password"])
    AuthToken.objects.filter(user=user).exclude(pk=request.auth.pk).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# --- Saved trips -----------------------------------------------------------------------------


def trip_dict(t: SavedTrip) -> dict:
    return {
        "id": str(t.pk),
        "saved_at": iso_z(t.saved_at),
        "origin": t.origin,
        "destination": t.destination,
        "departure_time": iso_z(t.departure_time),
        "load_weight_lb": t.load_weight_lb,
        "interval_mi": t.interval_mi,
        "time_zone": t.time_zone,
        "summary": t.summary,
    }


def _trip_list(user: User) -> Response:
    return Response({"trips": [trip_dict(t) for t in user.trips.all()[:MAX_SAVED_TRIPS]]})


def _add_trip(user: User, data: dict, saved_at=None) -> SavedTrip:
    """Newest first; an identical trip is replaced; at most 20 kept (oldest dropped)."""
    trip = SavedTrip(user=user, saved_at=saved_at or timezone.now(), **data)
    for old in user.trips.all():
        if old.same_inputs(trip):
            old.delete()
    trip.save()
    stale = list(user.trips.values_list("pk", flat=True)[MAX_SAVED_TRIPS:])
    if stale:
        SavedTrip.objects.filter(pk__in=stale).delete()
    return trip


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([scoped("trips")])
def trips(request: Request) -> Response:
    if request.method == "POST":
        ser = SavedTripSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            trip = _add_trip(request.user, ser.validated_data)
        return Response({"trip": trip_dict(trip)}, status=status.HTTP_201_CREATED)
    return _trip_list(request.user)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
@throttle_classes([scoped("trips")])
def trip_detail(request: Request, trip_id: int) -> Response:
    deleted, _ = SavedTrip.objects.filter(pk=trip_id, user=request.user).delete()
    if not deleted:
        raise Http404
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([scoped("trips")])
def import_trips(request: Request) -> Response:
    """Moves trips saved in this browser into the account (oldest first, so order is kept)."""
    ser = TripImportSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    items = ser.validated_data["trips"]
    now = timezone.now()
    with transaction.atomic():
        # Request lists newest first: insert oldest first with stepped timestamps.
        for i, data in enumerate(reversed(items)):
            _add_trip(request.user, data, saved_at=now - timedelta(seconds=len(items) - i))
    return _trip_list(request.user)


# --- Staff -----------------------------------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAdminUser])
def admin_stats(request: Request) -> Response:
    """Who uses the app, by continent and country (staff only)."""
    active = User.objects.filter(is_active=True)
    by_country = {r["country"]: r["n"] for r in active.values("country").annotate(n=Count("id"))}
    by_continent: dict[str, int] = dict.fromkeys(CONTINENTS, 0)
    for code, n in by_country.items():
        by_continent[COUNTRIES.get(code, ("", "Unknown"))[1]] = (
            by_continent.get(COUNTRIES.get(code, ("", "Unknown"))[1], 0) + n
        )
    since = timezone.now() - timedelta(days=7)
    return Response({
        "users_total": active.count(),
        "signups_last_7_days": active.filter(date_joined__gte=since).count(),
        "saved_trips_total": SavedTrip.objects.count(),
        "by_continent": by_continent,
        "by_country": sorted(
            ({"code": c, "name": COUNTRIES.get(c, (c, ""))[0], "users": n} for c, n in by_country.items()),
            key=lambda r: (-r["users"], r["name"]),
        ),
    })
