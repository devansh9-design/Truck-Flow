import pytest

from app import create_app, require_token

TOKEN = "test-token"


@pytest.fixture
def app():
    app = create_app({"RISK_ENGINE_TOKEN": TOKEN, "TESTING": True})

    @app.get("/v1/_protected")
    @require_token
    def protected():
        return {"ok": True}

    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_health_needs_no_token(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Token": "wrong"}, {"X-Internal-Token": ""}])
def test_missing_or_wrong_token_is_401(client, headers):
    r = client.get("/v1/_protected", headers=headers)
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_correct_token_passes(client):
    r = client.get("/v1/_protected", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200


def test_unconfigured_token_rejects_everything():
    app = create_app({"RISK_ENGINE_TOKEN": ""})

    @app.get("/v1/_p")
    @require_token
    def p():
        return {}

    assert app.test_client().get("/v1/_p", headers={"X-Internal-Token": ""}).status_code == 401


def test_unknown_route_uses_error_shape(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.get_json()["error"]["code"] == "NOT_FOUND"


def test_open_meteo_url_defaults_to_the_public_api(monkeypatch):
    monkeypatch.delenv("OPEN_METEO_URL", raising=False)
    provider = create_app({"TESTING": True}).config["FORECAST_PROVIDER"]
    assert provider._url == "https://api.open-meteo.com/v1/forecast"


def test_open_meteo_url_can_point_at_a_relay(monkeypatch):
    monkeypatch.setenv("OPEN_METEO_URL", "https://relay.example/api/open-meteo")
    provider = create_app({"TESTING": True}).config["FORECAST_PROVIDER"]
    assert provider._url == "https://relay.example/api/open-meteo"
