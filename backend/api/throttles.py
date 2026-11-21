"""Per-endpoint rate limits (protect the HERE quota and the weather services).

Guests are counted per client IP, signed-in users per account. Rates come from
`settings.API_RATES` at request time, so tests can change them. Counters live in the
in-memory cache: one gunicorn worker (render.yaml) means one shared count.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class ScopedApiThrottle(SimpleRateThrottle):
    scope = ""

    def __init__(self) -> None:  # rates are read per request, not at start-up
        pass

    def get_cache_key(self, request, view) -> str:
        user = getattr(request, "user", None)
        ident = f"user:{user.pk}" if user and user.is_authenticated else f"ip:{self.get_ident(request)}"
        return f"throttle:{self.scope}:{ident}"

    def allow_request(self, request, view) -> bool:
        rates = getattr(settings, "API_RATES", {}).get(self.scope)
        if not rates:
            return True
        user = getattr(request, "user", None)
        self.rate = rates["user" if user and user.is_authenticated else "anon"]
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


def scoped(scope: str) -> type[ScopedApiThrottle]:
    """A throttle class for one scope, for `@throttle_classes([scoped("analyze")])`."""
    return type(f"{scope.title()}Throttle", (ScopedApiThrottle,), {"scope": scope})
