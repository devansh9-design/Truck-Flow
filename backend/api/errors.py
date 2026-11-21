"""One JSON error shape for the whole public API (`docs/API contracts.md`)."""

from __future__ import annotations

import logging
from typing import Any

from django.http import Http404
from rest_framework import exceptions as drf_exc
from rest_framework.response import Response

log = logging.getLogger(__name__)


class ApiError(Exception):
    status = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationFailed(ApiError):
    status = 400
    code = "VALIDATION_ERROR"


class PlaceNotFound(ApiError):
    status = 404
    code = "PLACE_NOT_FOUND"


class NoRoute(ApiError):
    status = 422
    code = "NO_ROUTE"


class BeyondForecastHorizon(ApiError):
    status = 422
    code = "BEYOND_FORECAST_HORIZON"


class UpstreamError(ApiError):
    status = 502
    code = "UPSTREAM_ERROR"


class UpstreamTimeout(ApiError):
    status = 504
    code = "UPSTREAM_TIMEOUT"


def error_response(status: int, code: str, message: str, details: dict | None = None) -> Response:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return Response({"error": body}, status=status)


def _first_validation_message(detail: Any) -> tuple[str, str | None]:
    """Flatten DRF's nested error dict to (message, field)."""
    if isinstance(detail, dict):
        for field, value in detail.items():
            msg, _ = _first_validation_message(value)
            return msg, (None if field == "non_field_errors" else str(field))
    if isinstance(detail, list) and detail:
        return _first_validation_message(detail[0])
    return str(detail), None


def exception_handler(exc: Exception, context: dict) -> Response:
    if isinstance(exc, ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.details)
    if isinstance(exc, drf_exc.ValidationError):
        message, field = _first_validation_message(exc.detail)
        return error_response(400, "VALIDATION_ERROR", message, {"field": field} if field else None)
    if isinstance(exc, drf_exc.ParseError):
        return error_response(400, "VALIDATION_ERROR", "Request body is not valid JSON.")
    if isinstance(exc, Http404):
        return error_response(404, "NOT_FOUND", "Not found.")
    if isinstance(exc, drf_exc.APIException):
        # e.g. 405 method_not_allowed, 415 unsupported_media_type
        return error_response(exc.status_code, str(exc.default_code).upper(), str(exc.detail))
    log.exception("Unhandled error", exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "Unexpected server error.")
