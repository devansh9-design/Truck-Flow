"""Accounts (A6-A9): sign-up, sign-in, tokens, profile, saved trips and their authorization."""

from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from accounts.models import MAX_SAVED_TRIPS, AuthToken, SavedTrip, User, hash_token

pytestmark = pytest.mark.django_db

PASSWORD = "lorry-weather-42"


def signup(client=None, **over):
    body = {"name": "Ana Ruiz", "email": "Ana@Example.com", "password": PASSWORD, "country": "es"}
    body.update(over)
    return (client or APIClient()).post("/api/auth/signup", body, format="json")


def authed(token: str) -> APIClient:
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def trip_body(i: int = 0, **over):
    body = {
        "origin": {"label": "Madrid, Spain", "lat": 40.4168, "lon": -3.7038 + i / 100},
        "destination": {"label": "Barcelona, Spain", "lat": 41.3874, "lon": 2.1686},
        "departure_time": "2026-11-21T08:00:00Z",
        "load_weight_lb": 42000,
        "interval_mi": 25,
        "time_zone": "Europe/Madrid",
        "summary": {"recommended_label": "Route A", "max_level": "LOW", "distance_mi": 386.2},
    }
    body.update(over)
    return body


# ---- sign-up / sign-in ------------------------------------------------------------------------


def test_signup_creates_user_and_returns_token_and_profile():
    r = signup()
    assert r.status_code == 201
    body = r.json()
    assert body["token"] and body["expires_at"].endswith("Z")
    assert body["user"] == {**body["user"], "email": "ana@example.com", "name": "Ana Ruiz",
                            "country": "ES", "country_name": "Spain", "continent": "Europe",
                            "is_staff": False}
    user = User.objects.get(email="ana@example.com")
    assert user.check_password(PASSWORD) and user.password != PASSWORD  # hashed
    # Only the token's hash is stored.
    assert AuthToken.objects.filter(key_hash=hash_token(body["token"]), user=user).exists()
    assert not AuthToken.objects.filter(key_hash=body["token"]).exists()


@pytest.mark.parametrize("over, field", [
    ({"email": "not-an-email"}, "email"),
    ({"name": ""}, "name"),
    ({"country": "XX"}, "country"),
    ({"country": ""}, "country"),
    ({"password": "short"}, "password"),
    ({"password": "password123"}, "password"),  # common
    ({"password": "1234567890"}, "password"),  # numeric
])
def test_signup_validation(over, field):
    r = signup(**over)
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["details"]["field"] == field


def test_signup_rejects_duplicate_email_case_insensitively():
    signup()
    r = signup(email="ANA@example.com ")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "email"


def test_login_with_any_email_case_and_wrong_password():
    signup()
    ok = APIClient().post("/api/auth/login", {"email": "ANA@example.com", "password": PASSWORD},
                          format="json")
    assert ok.status_code == 200 and ok.json()["user"]["email"] == "ana@example.com"
    for body in ({"email": "ana@example.com", "password": "wrong-password"},
                 {"email": "nobody@example.com", "password": PASSWORD}):
        r = APIClient().post("/api/auth/login", body, format="json")
        assert r.status_code == 401
        assert r.json()["error"] == {"code": "INVALID_CREDENTIALS",
                                     "message": "Email or password is incorrect."}


def test_inactive_user_cannot_sign_in_or_use_token():
    token = signup().json()["token"]
    User.objects.update(is_active=False)
    assert APIClient().post("/api/auth/login", {"email": "ana@example.com", "password": PASSWORD},
                            format="json").status_code == 401
    assert authed(token).get("/api/auth/me").status_code == 401


# ---- tokens -----------------------------------------------------------------------------------


def test_me_needs_a_valid_token():
    r = APIClient().get("/api/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert r["WWW-Authenticate"].startswith("Bearer")
    r = authed("made-up").get("/api/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_INVALID"
    bad = APIClient()
    bad.credentials(HTTP_AUTHORIZATION="Bearer a b")
    assert bad.get("/api/auth/me").status_code == 401


def test_token_expires_after_30_days_without_use_and_slides_with_use():
    with freeze_time("2026-11-20T12:00:00Z"):
        token = signup().json()["token"]
    with freeze_time("2026-12-15T12:00:00Z"):  # day 25: still valid, and use extends it
        assert authed(token).get("/api/auth/me").status_code == 200
    with freeze_time("2027-01-10T12:00:00Z"):  # 26 days after last use
        assert authed(token).get("/api/auth/me").status_code == 200
    with freeze_time("2027-02-10T12:00:01Z"):  # > 30 days after last use
        assert authed(token).get("/api/auth/me").status_code == 401


def test_logout_revokes_only_that_token():
    a = signup().json()["token"]
    b = APIClient().post("/api/auth/login", {"email": "ana@example.com", "password": PASSWORD},
                         format="json").json()["token"]
    assert authed(a).post("/api/auth/logout").status_code == 204
    assert authed(a).get("/api/auth/me").status_code == 401
    assert authed(b).get("/api/auth/me").status_code == 200


def test_guest_endpoints_ignore_missing_token_but_reject_a_bad_one():
    assert APIClient().get("/api/countries").status_code == 200
    r = authed("expired-or-fake").get("/api/countries")
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_INVALID"


# ---- profile ----------------------------------------------------------------------------------


def test_profile_update_and_continent():
    token = signup().json()["token"]
    r = authed(token).patch("/api/auth/me", {"country": "br", "name": "Ana R."}, format="json")
    assert r.status_code == 200
    assert r.json()["user"] | {} == {**r.json()["user"], "country": "BR", "continent": "South America",
                                     "name": "Ana R."}
    bad = authed(token).patch("/api/auth/me", {"country": "ZZ"}, format="json")
    assert bad.status_code == 400 and bad.json()["error"]["details"]["field"] == "country"
    # Email and staff flag cannot be changed through the profile.
    authed(token).patch("/api/auth/me", {"email": "x@y.z", "is_staff": True}, format="json")
    u = User.objects.get()
    assert u.email == "ana@example.com" and not u.is_staff


def test_password_change_signs_out_other_devices():
    a = signup().json()["token"]
    b = APIClient().post("/api/auth/login", {"email": "ana@example.com", "password": PASSWORD},
                         format="json").json()["token"]
    wrong = authed(a).post("/api/auth/password",
                           {"current_password": "nope", "new_password": "new-secret-99"}, format="json")
    assert wrong.status_code == 400 and wrong.json()["error"]["details"]["field"] == "current_password"
    weak = authed(a).post("/api/auth/password",
                          {"current_password": PASSWORD, "new_password": "123"}, format="json")
    assert weak.status_code == 400 and weak.json()["error"]["details"]["field"] == "new_password"
    ok = authed(a).post("/api/auth/password",
                        {"current_password": PASSWORD, "new_password": "new-secret-99"}, format="json")
    assert ok.status_code == 204
    assert authed(a).get("/api/auth/me").status_code == 200
    assert authed(b).get("/api/auth/me").status_code == 401
    assert User.objects.get().check_password("new-secret-99")


def test_delete_account_needs_password_and_removes_everything():
    token = signup().json()["token"]
    authed(token).post("/api/trips", trip_body(), format="json")
    r = authed(token).delete("/api/auth/me", {"password": "wrong"}, format="json")
    assert r.status_code == 401 and User.objects.count() == 1
    assert authed(token).delete("/api/auth/me", {"password": PASSWORD}, format="json").status_code == 204
    assert User.objects.count() == 0 and SavedTrip.objects.count() == 0 and AuthToken.objects.count() == 0


# ---- saved trips + authorization -------------------------------------------------------------


def test_trips_need_sign_in():
    for method, path in (("get", "/api/trips"), ("post", "/api/trips"), ("delete", "/api/trips/1"),
                         ("post", "/api/trips/import")):
        r = getattr(APIClient(), method)(path, {}, format="json")
        assert r.status_code == 401, (method, path)


def test_save_list_delete_newest_first():
    c = authed(signup().json()["token"])
    with freeze_time("2026-11-20T10:00:00Z"):
        first = c.post("/api/trips", trip_body(1), format="json")
    with freeze_time("2026-11-20T11:00:00Z"):
        second = c.post("/api/trips", trip_body(2), format="json")
    assert first.status_code == second.status_code == 201
    ids = [t["id"] for t in c.get("/api/trips").json()["trips"]]
    assert ids == [second.json()["trip"]["id"], first.json()["trip"]["id"]]
    t = c.get("/api/trips").json()["trips"][0]
    assert t["origin"]["label"] == "Madrid, Spain" and t["departure_time"] == "2026-11-21T08:00:00Z"
    assert c.delete(f"/api/trips/{ids[0]}").status_code == 204
    assert [t["id"] for t in c.get("/api/trips").json()["trips"]] == [ids[1]]


def test_identical_trip_is_replaced_and_list_capped_at_20():
    c = authed(signup().json()["token"])
    c.post("/api/trips", trip_body(0), format="json")
    c.post("/api/trips", trip_body(0), format="json")
    assert len(c.get("/api/trips").json()["trips"]) == 1
    for i in range(1, 25):
        c.post("/api/trips", trip_body(i), format="json")
    trips = c.get("/api/trips").json()["trips"]
    assert len(trips) == MAX_SAVED_TRIPS == SavedTrip.objects.count()
    assert trips[0]["origin"]["lon"] == pytest.approx(-3.7038 + 24 / 100)


@pytest.mark.parametrize("over, field", [
    ({"origin": "Madrid"}, "origin"),  # free text is not stored: places must be resolved
    ({"interval_mi": 30}, "interval_mi"),
    ({"load_weight_lb": 0}, "load_weight_lb"),
    ({"summary": {"recommended_label": "A", "max_level": "BAD", "distance_mi": 1}}, "summary"),
])
def test_trip_validation(over, field):
    c = authed(signup().json()["token"])
    r = c.post("/api/trips", trip_body(**over), format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == field


def test_users_only_see_and_delete_their_own_trips():
    ana = authed(signup().json()["token"])
    ben = authed(signup(email="ben@example.com", name="Ben").json()["token"])
    trip_id = ana.post("/api/trips", trip_body(), format="json").json()["trip"]["id"]
    assert ben.get("/api/trips").json()["trips"] == []
    r = ben.delete(f"/api/trips/{trip_id}")
    assert r.status_code == 404  # not 403: another user's trip is not revealed
    assert SavedTrip.objects.filter(pk=trip_id).exists()


def test_import_moves_browser_trips_keeping_order():
    c = authed(signup().json()["token"])
    newest_first = [trip_body(3), trip_body(2), trip_body(1)]
    r = c.post("/api/trips/import", {"trips": newest_first}, format="json")
    assert r.status_code == 200
    lons = [t["origin"]["lon"] for t in r.json()["trips"]]
    assert lons == pytest.approx([-3.7038 + 0.03, -3.7038 + 0.02, -3.7038 + 0.01])
    too_many = c.post("/api/trips/import", {"trips": [trip_body(i) for i in range(21)]}, format="json")
    assert too_many.status_code == 400


# ---- staff ------------------------------------------------------------------------------------


def test_admin_stats_is_staff_only_and_groups_by_continent():
    ana = signup().json()["token"]
    signup(email="ben@example.com", name="Ben", country="US")
    signup(email="cy@example.com", name="Cy", country="FR")
    assert APIClient().get("/api/admin/stats").status_code == 401
    r = authed(ana).get("/api/admin/stats")
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    User.objects.filter(email="ana@example.com").update(is_staff=True)
    body = authed(ana).get("/api/admin/stats").json()
    assert body["users_total"] == 3 and body["signups_last_7_days"] == 3
    assert body["by_continent"]["Europe"] == 2 and body["by_continent"]["North America"] == 1
    assert body["by_country"][0] == {"code": "ES", "name": "Spain", "users": 1} or \
        body["by_country"][0]["users"] == 1
    assert {r["code"] for r in body["by_country"]} == {"ES", "US", "FR"}


def test_countries_list_covers_iso_3166_with_continents():
    body = APIClient().get("/api/countries").json()
    assert len(body["countries"]) == 249
    assert {"code": "ES", "name": "Spain", "continent": "Europe"} in body["countries"]
    assert {c["continent"] for c in body["countries"]} == set(body["continents"])


def test_createsuperuser_manager():
    admin = User.objects.create_superuser("Boss@Example.com", PASSWORD, name="Boss", country="US")
    assert admin.is_staff and admin.is_superuser and admin.email == "boss@example.com"
    assert timezone.now() - admin.date_joined < timedelta(minutes=1)
