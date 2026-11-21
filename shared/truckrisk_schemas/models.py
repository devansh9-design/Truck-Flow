"""Pydantic models from `docs/API contracts.md` Part C."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RiskLevel(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"
    NO_TRAVEL = "NO_TRAVEL"

    @property
    def score(self) -> int:
        return RISK_SCORES[self]


# Ordinal scores, spec §5.3.
RISK_SCORES: dict[RiskLevel, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MODERATE: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.SEVERE: 4,
    RiskLevel.NO_TRAVEL: 5,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatLon(_Strict):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Place(LatLon):
    label: str


class Weather(_Strict):
    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float


class RiskFactors(_Strict):
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    load_override: Literal["SEVERE", "NO_TRAVEL"] | None


class Risk(_Strict):
    level: RiskLevel
    score: int = Field(ge=1, le=5)
    factors: RiskFactors
    reason: str


def _require_tz(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value


class CheckpointIn(_Strict):
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    eta: datetime

    _tz = field_validator("eta")(_require_tz)


class EvaluateRequest(_Strict):
    load_weight_lb: float = Field(gt=0, le=100_000)
    checkpoints: list[CheckpointIn] = Field(max_length=1000)


class CheckpointResult(_Strict):
    id: str
    forecast_hour: datetime
    weather: Weather
    risk: Risk

    _tz = field_validator("forecast_hour")(_require_tz)


class EvaluateResponse(_Strict):
    results: list[CheckpointResult]
    meta: dict[str, Any]


# --- Heatmap (A4 / B3, CORE-6) -------------------------------------------------

HEATMAP_HOURS = 49  # slider hours 0..48; hour 0 = departure hour (D14)
HEATMAP_VARIABLES = ("risk", "wind_mph", "rain_in_hr", "snow_in_hr")


class HeatmapRequest(_Strict):
    bbox: list[float] = Field(min_length=4, max_length=4)  # minLon, minLat, maxLon, maxLat
    start: datetime
    hours: Literal[49] = HEATMAP_HOURS
    load_weight_lb: float = Field(gt=0, le=100_000)
    max_cells: int = Field(default=256, ge=16, le=400)

    _tz = field_validator("start")(_require_tz)

    @field_validator("bbox")
    @classmethod
    def _bbox(cls, v: list[float]) -> list[float]:
        min_lon, min_lat, max_lon, max_lat = v
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError("bbox must be minLon,minLat,maxLon,maxLat with min < max")
        return v


class HeatmapGrid(_Strict):
    rows: int = Field(ge=1)
    cols: int = Field(ge=1)
    lats: list[float]  # cell-centre latitude of each row, south to north
    lons: list[float]  # cell-centre longitude of each column, west to east


class HeatmapResponse(_Strict):
    """49 frames per variable; each frame is rows x cols values, row-major.

    A value is null where the forecast has no usable data for that cell and hour
    (never replaced by zero or by Low risk).
    """

    grid: HeatmapGrid
    times: list[datetime]
    hours: int
    variables: dict[str, list[list[float | None]]]
    source: str
    generated_at: datetime

    @field_validator("variables")
    @classmethod
    def _names(cls, v: dict) -> dict:
        if set(v) != set(HEATMAP_VARIABLES):
            raise ValueError(f"variables must be exactly {HEATMAP_VARIABLES}")
        return v

    @model_validator(mode="after")
    def _shape(self) -> HeatmapResponse:
        g = self.grid
        if len(g.lats) != g.rows or len(g.lons) != g.cols:
            raise ValueError("grid lats/lons do not match rows/cols")
        if not (self.hours == len(self.times) == HEATMAP_HOURS):
            raise ValueError(f"a heatmap has exactly {HEATMAP_HOURS} hourly frames")
        for name, frames in self.variables.items():
            if len(frames) != self.hours or any(len(f) != g.rows * g.cols for f in frames):
                raise ValueError(f"{name}: every frame must have rows x cols values")
        return self


ALERT_MAX_POINTS = 100
ALERT_SEVERITIES = ("Extreme", "Severe", "Moderate", "Minor", "Unknown")


class AlertsRequest(_Strict):
    """A5/B4: points sampled along the analysed routes (about every 50 mi)."""

    points: list[LatLon] = Field(min_length=1, max_length=ALERT_MAX_POINTS)


class Alert(_Strict):
    """One NWS active alert. Informational only: never feeds a risk level or the ranking."""

    id: str
    event: str
    severity: Literal["Extreme", "Severe", "Moderate", "Minor", "Unknown"]
    headline: str | None
    areas: str
    onset: datetime | None
    ends: datetime | None  # None = NWS gives no end ("until further notice")
    point_index: int = Field(ge=0)  # first request point the alert covers


class AlertsResponse(_Strict):
    alerts: list[Alert]
    coverage: Literal["US", "unsupported_region"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail
