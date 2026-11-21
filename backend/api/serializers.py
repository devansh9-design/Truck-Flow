from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from routing.sampling import ALLOWED_INTERVALS_MI
from truckrisk_schemas import ALERT_MAX_POINTS, Place

MAX_LOAD_LB = 100_000
MIN_LOAD_LB = 1
PAST_TOLERANCE = timedelta(hours=1)


class PlaceField(serializers.Field):
    """Free text (geocoded server-side) or an already-resolved {label, lat, lon}."""

    default_error_messages = {
        # Braces doubled: DRF formats these messages with str.format.
        "invalid": "Enter a place name or a {{label, lat, lon}} object.",
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


MAX_BBOX_LON_SPAN = 60.0  # coast to coast in the US is ~58 deg
MAX_BBOX_LAT_SPAN = 30.0


class HeatmapQuerySerializer(serializers.Serializer):
    """A4: `bbox` from corridor.bbox, `start` = departure hour (slider hour 0), load."""

    bbox = serializers.CharField()
    start = IsoDateTimeWithOffset()
    load_weight_lb = serializers.FloatField(
        min_value=MIN_LOAD_LB,
        max_value=MAX_LOAD_LB,
        error_messages={
            "min_value": "Load weight must be between 1 and 100,000 lb.",
            "max_value": "Load weight must be between 1 and 100,000 lb.",
        },
    )

    def validate_bbox(self, value: str) -> list[float]:
        try:
            parts = [float(p) for p in value.split(",")]
        except ValueError:
            parts = []
        if len(parts) != 4 or not all(math.isfinite(p) for p in parts):
            raise serializers.ValidationError("bbox must be minLon,minLat,maxLon,maxLat.")
        min_lon, min_lat, max_lon, max_lat = parts
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise serializers.ValidationError("bbox must be minLon,minLat,maxLon,maxLat with min < max.")
        if max_lon - min_lon > MAX_BBOX_LON_SPAN or max_lat - min_lat > MAX_BBOX_LAT_SPAN:
            raise serializers.ValidationError("bbox is too large for a trip corridor.")
        return parts

    def validate_start(self, value: datetime) -> datetime:
        now = timezone.now()
        # Hour 0 is the departure hour rounded down, so allow one more hour of slack.
        if value < now - PAST_TOLERANCE - timedelta(hours=1):
            raise serializers.ValidationError("start cannot be more than 2 hours in the past.")
        if value > now + timedelta(days=settings.FORECAST_HORIZON_DAYS):
            raise serializers.ValidationError("start is beyond the forecast horizon.")
        return value


class AlertPointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class AlertsRequestSerializer(serializers.Serializer):
    """A5: points sampled along the analysed routes (about every 50 mi, at most 100)."""

    points = AlertPointSerializer(many=True, allow_empty=False, max_length=ALERT_MAX_POINTS,
                                  error_messages={
                                      "max_length": f"At most {ALERT_MAX_POINTS} points.",
                                      "empty": "At least one point is required.",
                                  })
