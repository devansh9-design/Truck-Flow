"""CORE-3: every threshold edge (Testing strategy §2.1) plus property tests."""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rules import classify_rain, classify_snow, classify_wind, evaluate, load_override
from truckrisk_schemas import RiskLevel, Weather

L, M, H, S, NT = "LOW", "MODERATE", "HIGH", "SEVERE", "NO_TRAVEL"


@pytest.mark.parametrize(
    "value,expected",
    [(0, L), (24.99, L), (25, M), (34.99, M), (35, H), (44.99, H), (45, S), (54.99, S), (55, NT),
     (120, NT)],
)
def test_wind_edges(value, expected):
    assert classify_wind(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(0, L), (0.099, L), (0.10, M), (0.249, M), (0.25, H), (0.499, H), (0.50, S), (1.00, S),
     (1.001, NT)],
)
def test_rain_edges(value, expected):
    assert classify_rain(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(0, L), (0.49, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H), (2.0, S), (3.0, S), (3.001, NT)],
)
def test_snow_edges(value, expected):
    assert classify_snow(value) == expected


@pytest.mark.parametrize(
    "wind,load,expected",
    [
        (55, 1_000, NT),
        (45, 30_000, S),  # not over 30,000
        (45, 30_001, NT),
        (54.99, 30_001, NT),
        (35, 40_000, H),  # not over 40,000
        (35, 40_001, S),
        (44.99, 40_001, S),
        (34.99, 80_000, M),  # no override below 35 mph
    ],
)
def test_load_rules(wind, load, expected):
    risk = evaluate(Weather(wind_mph=wind, rain_in_hr=0, snow_in_hr=0), load)
    assert risk.level == expected
    assert risk.score == RiskLevel(expected).score


def test_load_override_field_records_only_what_the_load_changed():
    assert load_override(45, 30_001) == NT
    assert load_override(35, 40_001) == S
    assert load_override(55, 99_000) is None  # wind alone is already No Travel
    assert load_override(44.99, 30_001) is None  # 30k rule needs >= 45 mph
    risk = evaluate(Weather(wind_mph=40, rain_in_hr=0, snow_in_hr=0), 45_000)
    assert risk.factors.load_override == "SEVERE" and risk.factors.wind == H


def test_load_rule_never_lowers():
    # Severe snow + light wind + heavy load stays Severe.
    risk = evaluate(Weather(wind_mph=36, rain_in_hr=0, snow_in_hr=2.5), 41_000)
    assert risk.level == S
    # No Travel rain is not lowered by a Severe load override.
    risk = evaluate(Weather(wind_mph=36, rain_in_hr=1.2, snow_in_hr=0), 41_000)
    assert risk.level == NT


def test_worst_factor_wins():
    risk = evaluate(Weather(wind_mph=10, rain_in_hr=0.3, snow_in_hr=2.2), 10_000)
    assert risk.level == S
    assert (risk.factors.rain, risk.factors.snow) == (H, S)
    assert "snow 2.20 in/hr" in risk.reason


def test_reasons():
    calm = evaluate(Weather(wind_mph=5, rain_in_hr=0, snow_in_hr=0), 1)
    assert calm.reason == "All conditions below Moderate thresholds."
    loaded = evaluate(Weather(wind_mph=46, rain_in_hr=0, snow_in_hr=0), 35_000)
    assert loaded.reason == "No Travel: wind 46.0 mph with load 35,000 lb (> 30,000 lb)."


@pytest.mark.parametrize("bad", [-0.01, math.nan, math.inf, -math.inf, "3", None, True])
@pytest.mark.parametrize("fn", [classify_wind, classify_rain, classify_snow])
def test_negative_nonfinite_or_non_number_raise(fn, bad):
    with pytest.raises(ValueError):
        fn(bad)


@pytest.mark.parametrize("bad", [-1, math.nan, math.inf, -math.inf])
def test_bad_load_raises(bad):
    with pytest.raises(ValueError):
        load_override(40, bad)


# --- properties ----------------------------------------------------------------

wind_st = st.floats(min_value=0, max_value=150, allow_nan=False)
rain_st = st.floats(min_value=0, max_value=5, allow_nan=False)
snow_st = st.floats(min_value=0, max_value=10, allow_nan=False)
load_st = st.floats(min_value=1, max_value=100_000, allow_nan=False)
bump_st = st.floats(min_value=0, max_value=50, allow_nan=False)


def _score(w, r, s, load):
    return evaluate(Weather(wind_mph=w, rain_in_hr=r, snow_in_hr=s), load).score


@given(wind_st, rain_st, snow_st, load_st, bump_st)
def test_monotonic_in_each_input(w, r, s, load, bump):
    base = _score(w, r, s, load)
    assert _score(w + bump, r, s, load) >= base
    assert _score(w, r + bump, s, load) >= base
    assert _score(w, r, s + bump, load) >= base


@given(wind_st, rain_st, snow_st, load_st, st.floats(min_value=0, max_value=100_000))
def test_heavier_load_never_lowers(w, r, s, load, extra):
    assert _score(w, r, s, load + extra) >= _score(w, r, s, load)


@given(wind_st, rain_st, snow_st, load_st)
def test_result_is_a_valid_level(w, r, s, load):
    risk = evaluate(Weather(wind_mph=w, rain_in_hr=r, snow_in_hr=s), load)
    assert risk.level in set(RiskLevel)
    assert risk.score == risk.level.score
