from __future__ import annotations

from django.conf import settings
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from clients import risk_engine
from geo.geocode import geocode

from .serializers import (
    AlertsRequestSerializer,
    GeocodeQuerySerializer,
    HeatmapQuerySerializer,
    TripRequestSerializer,
)
from .services import analyze_trip, iso_z, plan_trip


@api_view(["GET"])
def health(request: Request) -> Response:
    """A1: wakes Django and, through it, the risk engine."""
    return Response(
        {"status": "ok", "risk_engine": risk_engine.health(), "time": iso_z(timezone.now())}
    )


@api_view(["GET"])
def geocode_view(request: Request) -> Response:
    """A2: up to 5 candidate places."""
    ser = GeocodeQuerySerializer(data=request.query_params)
    ser.is_valid(raise_exception=True)
    places = geocode(ser.validated_data["q"])
    return Response({"results": [p.model_dump() for p in places]})


@api_view(["POST"])
def debug_routes(request: Request) -> Response:
    """Chunk 1 core check (DEBUG only): 3 routes with checkpoints + ETAs, no weather yet."""
    if not settings.DEBUG:
        raise Http404
    ser = TripRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    plan = plan_trip(ser.validated_data)
    return Response(
        {
            "trip": plan.trip_dict(),
            "routes": [r.to_dict() for r in plan.routes],
            "corridor": {"bbox": plan.bbox()},
            "notes": plan.notes,
        }
    )


@api_view(["POST"])
def analyze(request: Request) -> Response:
    """A3: three ranked routes with ETA-hour weather and risk at every checkpoint."""
    ser = TripRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    return Response(analyze_trip(ser.validated_data))


@api_view(["GET"])
def heatmap(request: Request) -> HttpResponse:
    """A4 (CORE-6): all 49 frames for the corridor in one response; the slider never refetches."""
    ser = HeatmapQuerySerializer(data=request.query_params)
    ser.is_valid(raise_exception=True)
    v = ser.validated_data
    body = risk_engine.heatmap(v["bbox"], v["start"], v["load_weight_lb"])
    return HttpResponse(body, content_type="application/json")


@api_view(["POST"])
def alerts(request: Request) -> HttpResponse:
    """A5 (non-core): NWS alerts near the routes. Informational; never changes risk or ranking."""
    ser = AlertsRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    body = risk_engine.alerts(ser.validated_data["points"])
    return HttpResponse(body, content_type="application/json")
