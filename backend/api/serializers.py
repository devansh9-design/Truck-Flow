from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from routing.sampling import ALLOWED_INTERVALS_MI
from truckrisk_schemas import Place

MAX_LOAD_LB = 100_000
MIN_LOAD_LB = 1
PAST_TOLERANCE = timedelta(hours=1)


class PlaceField(serializers.Field):
    """Free text (geocoded server-side) or an already-resolved {label, lat, lon}."""

    default_error_messages = {
        "invalid": "Enter a place name or a {label, lat, lon} object.",
        "length": "Place text must be 2-200 characters.",
    }

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not 2 <= len(text) <= 200:
                self.fail("length")
            return text
        if isinstance(data, dict):
            try:
                return Place.model_validate(data).model_dump()
            except ValueError:
                self.fail("invalid")
        self.fail("invalid")

    def to_representation(self, value):
        return value


class IsoDateTimeWithOffset(serializers.Field):
    default_error_messages = {
        "invalid": "Use ISO 8601 with a timezone offset, e.g. 2026-11-21T06:00:00-07:00.",
        "naive": "Departure time must include a timezone offset.",
    }

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        try:
            value = datetime.fromisoformat(data)
        except ValueError:
            self.fail("invalid")
        if value.tzinfo is None or value.utcoffset() is None:
            self.fail("naive")
        return value.astimezone(UTC)

    def to_representation(self, value):
        return value.isoformat()


class TripRequestSerializer(serializers.Serializer):
    origin = PlaceField()
    destination = PlaceField()
    departure_time = IsoDateTimeWithOffset()
    load_weight_lb = serializers.FloatField(
        min_value=MIN_LOAD_LB,
        max_value=MAX_LOAD_LB,
        error_messages={
            "min_value": "Load weight must be between 1 and 100,000 lb.",
            "max_value": "Load weight must be between 1 and 100,000 lb.",
        },
    )
    interval_mi = serializers.ChoiceField(
        choices=ALLOWED_INTERVALS_MI,
        default=25,
        error_messages={"invalid_choice": "Sampling interval must be 10, 25 or 50 miles."},
    )

    def validate_departure_time(self, value: datetime) -> datetime:
        now = timezone.now()
        if value < now - PAST_TOLERANCE:
            raise serializers.ValidationError(
                "Departure time cannot be more than 1 hour in the past."
            )
        if value > now + timedelta(days=settings.FORECAST_HORIZON_DAYS):
            raise serializers.ValidationError(
                f"Departure time must be within the {settings.FORECAST_HORIZON_DAYS}-day "
                "forecast horizon."
            )
        return value

    def validate(self, attrs):
        o, d = attrs["origin"], attrs["destination"]
        if isinstance(o, str) and isinstance(d, str) and o.casefold() == d.casefold():
            raise serializers.ValidationError(
                {"destination": "Origin and destination must be different."}
            )
        return attrs


class GeocodeQuerySerializer(serializers.Serializer):
    q = serializers.CharField(
        min_length=2,
        max_length=200,
        trim_whitespace=True,
        error_messages={
            "min_length": "Search text must be 2-200 characters.",
            "max_length": "Search text must be 2-200 characters.",
            "required": "Query parameter q is required.",
            "blank": "Search text must be 2-200 characters.",
        },
    )
