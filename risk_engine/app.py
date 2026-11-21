"""Flask risk engine (internal). Chunk 1: app factory, /health, token guard, error shape.

/v1/evaluate, /v1/heatmap and /v1/alerts are added in Chunks 2 and 4.
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
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

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

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

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
