"""User accounts (ADR 012): email login, profile country, sign-in tokens, saved trips.

Accounts are optional: guests can still analyse trips. An account adds a profile country
(continent derived from it) and saved trips stored on the server.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from .countries import COUNTRIES

TOKEN_TTL = timedelta(days=30)
# Activity extends a token at most this often (avoids a DB write on every request).
TOKEN_TOUCH_EVERY = timedelta(hours=1)
MAX_SAVED_TRIPS = 20


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **fields) -> User:
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=normalize_email(email), **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **fields) -> User:
        fields.setdefault("is_staff", True)
        fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name", "country"]

    def save(self, *args, **kwargs) -> None:
        self.email = normalize_email(self.email)
        super().save(*args, **kwargs)

    @property
    def country_name(self) -> str:
        return COUNTRIES.get(self.country, ("", ""))[0]

    @property
    def continent(self) -> str:
        return COUNTRIES.get(self.country, ("", ""))[1]

    def __str__(self) -> str:
        return self.email


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthToken(models.Model):
    """A sign-in token. Only its SHA-256 is stored, so a database leak exposes no usable token."""

    key_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tokens")
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    @classmethod
    def issue(cls, user: User) -> tuple[AuthToken, str]:
        """New token for `user`; returns (token row, raw token to give the client once)."""
        raw = secrets.token_urlsafe(32)
        now = timezone.now()
        tok = cls.objects.create(key_hash=hash_token(raw), user=user, created_at=now,
                                 last_used_at=now, expires_at=now + TOKEN_TTL)
        return tok, raw

    @property
    def expired(self) -> bool:
        return self.expires_at <= timezone.now()

    def touch(self) -> None:
        """Sliding expiry: a token in use stays valid for TOKEN_TTL after its last use."""
        now = timezone.now()
        if now - self.last_used_at >= TOKEN_TOUCH_EVERY:
            self.last_used_at = now
            self.expires_at = now + TOKEN_TTL
            self.save(update_fields=["last_used_at", "expires_at"])


class SavedTrip(models.Model):
    """Trip inputs plus a short summary. Reopening re-runs the analysis (fresh weather)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trips")
    origin = models.JSONField()  # {label, lat, lon}
    destination = models.JSONField()
    departure_time = models.DateTimeField()
    load_weight_lb = models.FloatField()
    interval_mi = models.PositiveSmallIntegerField()
    time_zone = models.CharField(max_length=64)
    summary = models.JSONField()  # {recommended_label, max_level, distance_mi}
    saved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-saved_at", "-id"]

    def same_inputs(self, other: SavedTrip) -> bool:
        return (
            self.origin.get("lat") == other.origin.get("lat")
            and self.origin.get("lon") == other.origin.get("lon")
            and self.destination.get("lat") == other.destination.get("lat")
            and self.destination.get("lon") == other.destination.get("lon")
            and self.departure_time == other.departure_time
            and self.load_weight_lb == other.load_weight_lb
            and self.interval_mi == other.interval_mi
        )
