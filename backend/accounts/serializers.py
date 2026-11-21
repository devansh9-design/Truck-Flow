from __future__ import annotations

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from api.serializers import PlaceField

from .countries import COUNTRIES
from .models import MAX_SAVED_TRIPS, User, normalize_email

RISK_LEVELS = ("LOW", "MODERATE", "HIGH", "SEVERE", "NO_TRAVEL")
INTERVALS = (10, 25, 50)


def validate_country(value: str) -> str:
    code = value.strip().upper()
    if code not in COUNTRIES:
        raise serializers.ValidationError("Choose a country from the list.")
    return code


def user_dict(user: User) -> dict:
    return {
        "id": user.pk,
        "email": user.email,
        "name": user.name,
        "country": user.country,
        "country_name": user.country_name,
        "continent": user.continent,
        "is_staff": user.is_staff,
        "date_joined": user.date_joined,
    }


class SignupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    country = serializers.CharField(max_length=2)

    def validate_email(self, value: str) -> str:
        email = normalize_email(value)
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError("An account with this email already exists. Sign in instead.")
        return email

    def validate_country(self, value: str) -> str:
        return validate_country(value)

    def validate(self, attrs: dict) -> dict:
        candidate = User(email=attrs["email"], name=attrs["name"], country=attrs["country"])
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from None
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class ProfileSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False, trim_whitespace=True)
    country = serializers.CharField(max_length=2, required=False)

    def validate_country(self, value: str) -> str:
        return validate_country(value)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        user = self.context["user"]
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Current password is incorrect."})
        try:
            password_validation.validate_password(attrs["new_password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from None
        return attrs


class DeleteAccountSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class PlaceDictField(PlaceField):
    """Saved trips store resolved places only ({label, lat, lon}), never free text."""

    default_error_messages = {**PlaceField.default_error_messages,
                              "resolved": "Saved trips need a resolved place ({{label, lat, lon}})."}

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            self.fail("resolved")
        return super().to_internal_value(data)


class TripSummarySerializer(serializers.Serializer):
    recommended_label = serializers.CharField(max_length=100, allow_blank=True)
    max_level = serializers.ChoiceField(choices=RISK_LEVELS)
    distance_mi = serializers.FloatField(min_value=0)


class SavedTripSerializer(serializers.Serializer):
    origin = PlaceDictField()
    destination = PlaceDictField()
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=1, max_value=100_000)
    interval_mi = serializers.ChoiceField(choices=INTERVALS)
    time_zone = serializers.CharField(max_length=64)
    summary = TripSummarySerializer()


class TripImportSerializer(serializers.Serializer):
    trips = SavedTripSerializer(many=True, max_length=MAX_SAVED_TRIPS)
