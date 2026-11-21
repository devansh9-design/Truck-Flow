"""Test settings: fixed, fake configuration so tests never depend on a local .env."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from .settings import *  # noqa: E402,F403

DEBUG = False
HERE_API_KEY = "test-key"
RISK_ENGINE_TOKEN = "test-token"
TRUCK_TARE_LB = 35_000.0

# Fast hashing in tests only.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# Rate limits off by default; tests/test_throttling.py sets real ones.
API_RATES: dict = {}
