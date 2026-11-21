"""Django settings. All secrets come from the environment (backend/.env locally)."""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = _env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-only-insecure-key" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false")

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# Behind Render's proxy TLS ends at the edge; trust its forwarded scheme in production.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "api",
    "accounts",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    # Compress JSON responses (route geometry, heatmap frames): no cookies or secrets in them.
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Accounts and saved trips (ADR 012). Deployed: Render Postgres via DATABASE_URL.
# Locally (DEBUG) a SQLite file is used when DATABASE_URL is unset.
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not _DATABASE_URL and not DEBUG:
    raise RuntimeError("DATABASE_URL must be set when DJANGO_DEBUG is false")
DATABASES = {
    "default": dj_database_url.parse(
        _DATABASE_URL or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ("email", "name")}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "truck-routing",
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = _env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

REST_FRAMEWORK = {
    # Optional sign-in (ADR 013): no header = guest; most endpoints stay open to guests.
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.auth.BearerTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    # Client IP for guest rate limits: count of proxies in front of Django that append to
    # X-Forwarded-For (Render: see docs/deployment.md). None = use the socket address.
    "NUM_PROXIES": int(os.environ["NUM_PROXIES"]) if os.environ.get("NUM_PROXIES") else None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "api.errors.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Weather-Aware Truck Routing API",
    "VERSION": "0.1.0",
}

# --- App configuration -----------------------------------------------------

HERE_API_KEY = os.environ.get("HERE_API_KEY", "")
HERE_GEOCODE_URL = os.environ.get(
    "HERE_GEOCODE_URL", "https://geocode.search.hereapi.com/v1/geocode"
)
HERE_ROUTES_URL = os.environ.get("HERE_ROUTES_URL", "https://router.hereapi.com/v8/routes")
HERE_AUTOCOMPLETE_URL = os.environ.get(
    "HERE_AUTOCOMPLETE_URL", "https://autocomplete.search.hereapi.com/v1/autocomplete"
)
HERE_LOOKUP_URL = os.environ.get("HERE_LOOKUP_URL", "https://lookup.search.hereapi.com/v1/lookup")

TRUCK_TARE_LB = float(os.environ.get("TRUCK_TARE_LB", "35000"))

RISK_ENGINE_URL = os.environ.get("RISK_ENGINE_URL", "http://127.0.0.1:5001").rstrip("/")
RISK_ENGINE_TOKEN = os.environ.get("RISK_ENGINE_TOKEN", "")

# Rate limits per endpoint group: guests per IP, signed-in users per account.
API_RATES = {
    "analyze": {"anon": "30/hour", "user": "120/hour"},
    "heatmap": {"anon": "60/hour", "user": "240/hour"},
    "alerts": {"anon": "60/hour", "user": "240/hour"},
    "geocode": {"anon": "60/min", "user": "120/min"},
    "auth": {"anon": "10/min", "user": "10/min"},
    "trips": {"anon": "60/min", "user": "60/min"},
}

# Forecast horizon (spec D11): Open-Meteo serves up to 16 days.
FORECAST_HORIZON_DAYS = 16

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # httpx logs every request URL at INFO, and HERE takes its key as the `apiKey`
    # query parameter: keep these loggers at WARNING so the key never reaches logs.
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
