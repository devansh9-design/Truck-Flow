"""Pydantic models from `docs/API contracts.md` Part C."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail
