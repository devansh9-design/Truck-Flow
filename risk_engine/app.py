"""Flask risk engine (internal): /health and token-protected /v1/evaluate.

/v1/heatmap and /v1/alerts are added in Chunk 4 and Upgrade 2.
"""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from evaluate import BeyondHorizon, evaluate_checkpoints
from flask import Flask, jsonify, request
from heatmap import build_heatmap
from heatmap import to_json as heatmap_json
from pydantic import ValidationError
from weather import OpenMeteoProvider, WeatherUpstreamError
from werkzeug.exceptions import HTTPException

from truckrisk_schemas import EvaluateRequest, HeatmapRequest

load_dotenv(Path(__file__).resolve().parent / ".env")
log = logging.getLogger(__name__)

HTTP_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    500: "INTERNAL_ERROR",
}


def error(status: int, code: str, message: str, details: dict | None = None):
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return jsonify({"error": body}), status


def require_token(view: Callable) -> Callable:
    """Reject calls without the shared X-Internal-Token (constant-time compare)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        from flask import current_app

        expected = current_app.config.get("RISK_ENGINE_TOKEN") or ""
        given = request.headers.get("X-Internal-Token", "")
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return error(401, "UNAUTHORIZED", "Missing or invalid internal token.")
        return view(*args, **kwargs)

    return wrapper


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config["RISK_ENGINE_TOKEN"] = os.environ.get("RISK_ENGINE_TOKEN", "")
    app.config["NWS_USER_AGENT"] = os.environ.get("NWS_USER_AGENT", "")
    if config:
        app.config.update(config)
    # Injectable so tests and scenarios can supply scripted weather.
    app.config.setdefault("FORECAST_PROVIDER", None)
    if app.config["FORECAST_PROVIDER"] is None:
        app.config["FORECAST_PROVIDER"] = OpenMeteoProvider()

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/v1/evaluate")
    @require_token
    def v1_evaluate():
        body = request.get_json(silent=True)
        if body is None:
            return error(400, "VALIDATION_ERROR", "Request body must be JSON.")
        try:
            req = EvaluateRequest.model_validate(body)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first["loc"])
            return error(400, "VALIDATION_ERROR", f"{field}: {first['msg']}", {"field": field})
        try:
            resp = evaluate_checkpoints(req, app.config["FORECAST_PROVIDER"])
        except BeyondHorizon as exc:
            return error(
                422,
                "BEYOND_FORECAST_HORIZON",
                "Part of this trip is beyond the available weather forecast"
                + (f" (forecast ends {exc.latest})." if exc.latest else "."),
                {"checkpoint_ids": exc.ids[:20], "count": len(exc.ids)},
            )
        except WeatherUpstreamError as exc:
            if exc.timeout:
                return error(504, "UPSTREAM_TIMEOUT", str(exc))
            return error(502, "UPSTREAM_ERROR", str(exc))
        return app.response_class(resp.model_dump_json(), mimetype="application/json")

    @app.post("/v1/heatmap")
    @require_token
    def v1_heatmap():
        body = request.get_json(silent=True)
        if body is None:
            return error(400, "VALIDATION_ERROR", "Request body must be JSON.")
        try:
            req = HeatmapRequest.model_validate(body)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first["loc"]) or "body"
            return error(400, "VALIDATION_ERROR", f"{field}: {first['msg']}", {"field": field})
        try:
            resp = build_heatmap(req, app.config["FORECAST_PROVIDER"])
        except WeatherUpstreamError as exc:
            if exc.timeout:
                return error(504, "UPSTREAM_TIMEOUT", str(exc))
            return error(502, "UPSTREAM_ERROR", str(exc))
        return app.response_class(heatmap_json(resp), mimetype="application/json")

    @app.errorhandler(HTTPException)
    def handle_http(exc: HTTPException):
        status = exc.code or 500
        code = HTTP_CODES.get(status, "UPSTREAM_ERROR" if status >= 500 else "VALIDATION_ERROR")
        return error(status, code, exc.description or exc.name)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return error(500, "INTERNAL_ERROR", "Unexpected server error.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5001")), debug=False)
