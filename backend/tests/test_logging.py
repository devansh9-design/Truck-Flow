"""Secrets never reach logs: httpx's per-request INFO lines contain HERE's apiKey."""

import logging

import httpx
import respx
from django.conf import settings


def test_httpx_request_lines_are_not_logged_at_info():
    assert settings.LOGGING["loggers"]["httpx"]["level"] == "WARNING"
    assert settings.LOGGING["loggers"]["httpcore"]["level"] == "WARNING"


@respx.mock
def test_api_key_in_url_is_not_logged(caplog):
    logging.config.dictConfig(settings.LOGGING)
    respx.get("https://router.test/v8/routes").mock(return_value=httpx.Response(200, json={}))
    with caplog.at_level(logging.DEBUG, logger=""):
        logging.getLogger("httpx").setLevel(settings.LOGGING["loggers"]["httpx"]["level"])
        httpx.get("https://router.test/v8/routes", params={"apiKey": "secret-key-123"})
    assert "secret-key-123" not in caplog.text
