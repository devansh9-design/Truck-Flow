"""Rate limits: guests per IP, signed-in users per account, 429 with Retry-After."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

RATES = {
    "auth": {"anon": "3/min", "user": "3/min"},
    "geocode": {"anon": "2/min", "user": "4/min"},
}


@pytest.fixture(autouse=True)
def _rates(settings):
    settings.API_RATES = RATES
    cache.clear()
    yield
    cache.clear()


def _login(client, ip="10.0.0.1"):
    return client.post("/api/auth/login", {"email": "x@example.com", "password": "nope-nope"},
                       format="json", REMOTE_ADDR=ip)


def test_login_attempts_are_limited_per_ip():
    c = APIClient()
    assert [_login(c).status_code for _ in range(3)] == [401, 401, 401]
    r = _login(c)
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "RATE_LIMITED" and err["details"]["retry_after_s"] > 0
    assert int(r["Retry-After"]) > 0
    assert _login(c, ip="10.0.0.2").status_code == 401  # another client is unaffected


def test_signed_in_users_are_counted_per_account_with_their_own_rate(monkeypatch):
    monkeypatch.setattr("api.views.geocode", lambda q: [])
    token = APIClient().post("/api/auth/signup", {"name": "A", "email": "a@example.com",
                                                  "password": "lorry-weather-42", "country": "US"},
                             format="json").json()["token"]
    guest = APIClient()
    assert [guest.get("/api/geocode", {"q": "Denver"}).status_code for _ in range(3)] == [200, 200, 429]
    user = APIClient()
    user.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    # Same IP as the guest, but counted per account at the higher user rate.
    assert [user.get("/api/geocode", {"q": "Denver"}).status_code for _ in range(5)] == [200] * 4 + [429]


def test_unlisted_scope_and_health_are_not_limited():
    c = APIClient()
    assert all(c.get("/api/countries").status_code == 200 for _ in range(10))
