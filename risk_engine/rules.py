"""Risk and load rules (CORE-3), exactly as `docs/projects specification.md` §5.1–5.3.

Intervals are half-open [lower, upper) (D1), except the spec's "Above" limits:
rain 1.00 in/hr and snow 3.00 in/hr stay Severe; only values above them are
No Travel.

Load rules (§5.2) can only raise a level, never lower it:
    45 <= wind < 55 mph and load > 30,000 lb -> NO_TRAVEL
    35 <= wind < 45 mph and load > 40,000 lb -> SEVERE
Wind >= 55 mph is No Travel for any load; the wind factor already says so,
so `load_override` stays None there (it records only what the load changed).

The load is the load as entered (D13), never the router's gross weight.
"""

from __future__ import annotations

import math

from truckrisk_schemas import Risk, RiskFactors, RiskLevel, Weather

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)

LOAD_NO_TRAVEL_LB = 30_000  # strictly greater than
LOAD_SEVERE_LB = 40_000  # strictly greater than


def _check(name: str, value: float) -> float:
    # isfinite rejects NaN and both infinities: +inf must never classify as No Travel.
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite, non-negative number, got {value!r}")
    return float(value)


def classify_wind(mph: float) -> RiskLevel:
    w = _check("wind_mph", mph)
    if w < 25:
        return L
    if w < 35:
        return M
    if w < 45:
        return H
    if w < 55:
        return S
    return NT


def classify_rain(in_hr: float) -> RiskLevel:
    r = _check("rain_in_hr", in_hr)
    if r < 0.10:
        return L
    if r < 0.25:
        return M
    if r < 0.50:
        return H
    if r <= 1.00:  # "Above 1.00" is No Travel, so 1.00 itself is Severe
        return S
    return NT


def classify_snow(in_hr: float) -> RiskLevel:
    s = _check("snow_in_hr", in_hr)
    if s < 0.5:
        return L
    if s < 1.0:
        return M
    if s < 2.0:
        return H
    if s <= 3.0:  # "Above 3.0" is No Travel, so 3.0 itself is Severe
        return S
    return NT


def load_override(wind_mph: float, load_lb: float) -> RiskLevel | None:
    w = _check("wind_mph", wind_mph)
    load = _check("load_weight_lb", load_lb)
    if 45 <= w < 55 and load > LOAD_NO_TRAVEL_LB:
        return NT
    if 35 <= w < 45 and load > LOAD_SEVERE_LB:
        return S
    return None


def _worst(*levels: RiskLevel | None) -> RiskLevel:
    return max((lv for lv in levels if lv is not None), key=lambda lv: lv.score)


_LABEL = {L: "Low", M: "Moderate", H: "High", S: "Severe", NT: "No Travel"}


def _reason(weather: Weather, factors: RiskFactors, level: RiskLevel, load_lb: float) -> str:
    if level == L:
        return "All conditions below Moderate thresholds."
    parts: list[str] = []
    if factors.wind == level:
        parts.append(f"wind {weather.wind_mph:.1f} mph")
    if factors.rain == level:
        parts.append(f"rain {weather.rain_in_hr:.2f} in/hr")
    if factors.snow == level:
        parts.append(f"snow {weather.snow_in_hr:.2f} in/hr")
    if factors.load_override is not None and factors.load_override == level.value:
        limit = LOAD_NO_TRAVEL_LB if level == NT else LOAD_SEVERE_LB
        parts.append(
            f"wind {weather.wind_mph:.1f} mph with load {load_lb:,.0f} lb (> {limit:,} lb)"
        )
    return f"{_LABEL[level]}: " + "; ".join(parts) + "."


def evaluate(weather: Weather, load_lb: float) -> Risk:
    """checkpoint_level = max(wind, rain, snow, load_override)  (spec §5.3)."""
    wind = classify_wind(weather.wind_mph)
    rain = classify_rain(weather.rain_in_hr)
    snow = classify_snow(weather.snow_in_hr)
    override = load_override(weather.wind_mph, load_lb)
    level = _worst(wind, rain, snow, override)
    factors = RiskFactors(
        wind=wind,
        rain=rain,
        snow=snow,
        load_override=override.value if override is not None else None,
    )
    return Risk(
        level=level,
        score=level.score,
        factors=factors,
        reason=_reason(weather, factors, level, load_lb),
    )
