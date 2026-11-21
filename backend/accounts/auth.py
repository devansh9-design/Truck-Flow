"""`Authorization: Bearer <token>` authentication (ADR 013).

The frontend (Vercel) and the API (Render) are different sites, where browsers block or
partition cookies, so sign-in uses a bearer token instead of a session cookie. No cookie
means no CSRF exposure. No header = guest (most endpoints stay open to guests).
"""

from __future__ import annotations

from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import AuthToken, hash_token

EXPIRED = "Your session has expired. Please sign in again."


class BearerTokenAuthentication(BaseAuthentication):
    keyword = b"bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Malformed Authorization header.")
        try:
            raw = parts[1].decode("ascii")
        except UnicodeDecodeError:
            raise AuthenticationFailed(EXPIRED) from None
        token = (AuthToken.objects.select_related("user")
                 .filter(key_hash=hash_token(raw)).first())
        if token is None or token.expired or not token.user.is_active:
            raise AuthenticationFailed(EXPIRED)
        token.touch()
        return token.user, token

    def authenticate_header(self, request) -> str:
        return 'Bearer realm="api"'
