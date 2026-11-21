"""Shared wire models for the Django API and the Flask risk engine.

Units contract (every value on the wire):
    distance  -> miles (mi)
    speed     -> miles per hour (mph)
    intensity -> inches per hour (in/hr)
    weight    -> pounds (lb)
    duration  -> seconds (s)
    time      -> ISO 8601, UTC ("Z") in responses
"""

from .models import (
    HEATMAP_HOURS,
    HEATMAP_VARIABLES,
    RISK_SCORES,
    CheckpointIn,
    CheckpointResult,
    ErrorBody,
    ErrorDetail,
    EvaluateRequest,
    EvaluateResponse,
    HeatmapGrid,
    HeatmapRequest,
    HeatmapResponse,
    LatLon,
    Place,
    Risk,
    RiskFactors,
    RiskLevel,
    Weather,
)
from .timeutil import iso_z, round_to_hour
from .units import (
    KG_PER_LB,
    METERS_PER_MILE,
    lb_to_kg,
    meters_to_miles,
    miles_to_meters,
)

__all__ = [
    "HEATMAP_HOURS",
    "HEATMAP_VARIABLES",
    "RISK_SCORES",
    "KG_PER_LB",
    "METERS_PER_MILE",
    "CheckpointIn",
    "CheckpointResult",
    "ErrorBody",
    "ErrorDetail",
    "EvaluateRequest",
    "EvaluateResponse",
    "HeatmapGrid",
    "HeatmapRequest",
    "HeatmapResponse",
    "LatLon",
    "Place",
    "Risk",
    "RiskFactors",
    "RiskLevel",
    "Weather",
    "iso_z",
    "lb_to_kg",
    "meters_to_miles",
    "miles_to_meters",
    "round_to_hour",
]
