"""CORE-2 (checkpoints + ETA): Testing strategy §2.2."""

from datetime import UTC, datetime, timedelta

import pytest

from routing.sampling import checkpoint_miles, round_to_hour, sample_checkpoints
from routing.track import SectionInput, build_track, haversine_mi

from .helpers import line_length, straight_line, track_for

DEP = datetime(2026, 11, 21, 13, 0, tzinfo=UTC)


def test_100_mi_at_25_gives_0_25_50_75_100():
    track = track_for(straight_line(100))
    cps = sample_checkpoints(track, 25, DEP)
    assert [round(c.mile, 6) for c in cps] == [0, 25, 50, 75, round(track.distance_mi, 6)]
    assert track.distance_mi == pytest.approx(100, abs=1e-6)


def test_103_mi_final_checkpoint_is_destination():
    coords = straight_line(103)
    track = track_for(coords)
    cps = sample_checkpoints(track, 25, DEP)
    assert [round(c.mile) for c in cps] == [0, 25, 50, 75, 100, 103]
    assert (cps[-1].lat, cps[-1].lon) == pytest.approx(coords[-1])
    assert (cps[0].lat, cps[0].lon) == pytest.approx(coords[0])


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_route_shorter_than_interval_has_origin_and_destination_only(interval):
    track = track_for(straight_line(interval * 0.4, step_mi=0.5))
    cps = sample_checkpoints(track, interval, DEP)
    assert len(cps) == 2
    assert cps[0].mile == 0 and cps[-1].mile == pytest.approx(track.distance_mi)


@pytest.mark.parametrize("interval,expected", [(10, 11), (25, 5), (50, 3)])
def test_interval_counts(interval, expected):
    assert len(checkpoint_miles(100.0, interval)) == expected


def test_float_noise_does_not_add_tiny_last_segment():
    assert checkpoint_miles(100.000001, 25) == [0, 25, 50, 75, 100.000001]


def test_constant_speed_eta_proportional_to_distance():
    track = track_for(straight_line(200), mph=50)
    cps = sample_checkpoints(track, 25, DEP)
    for cp in cps:
        assert cp.elapsed_s == pytest.approx(cp.mile / 50 * 3600, rel=1e-6)
        assert cp.eta == DEP + timedelta(seconds=cp.elapsed_s)


def test_two_sections_with_different_speeds():
    a = straight_line(50)
    b = straight_line(50, start=a[-1])
    track = build_track(
        [
            SectionInput(coords=a, length_mi=line_length(a), duration_s=3600),  # 50 mph
            SectionInput(coords=b, length_mi=line_length(b), duration_s=1800),  # 100 mph
        ]
    )
    cps = sample_checkpoints(track, 25, DEP)
    elapsed = [round(c.elapsed_s) for c in cps]
    assert elapsed == [0, 1800, 3600, 4500, 5400]


def test_spans_shape_eta_within_a_section():
    # 4 steps of 25 mi; first two spans are slow (1 h each), last two fast (0.25 h each).
    coords = straight_line(100, step_mi=25)
    spans = [
        (0, 3600.0),
        (1, 3600.0),
        (2, 900.0),
        (3, 900.0),
    ]
    track = build_track(
        [SectionInput(coords=coords, length_mi=line_length(coords), duration_s=9000, spans=spans)]
    )
    cps = sample_checkpoints(track, 25, DEP)
    assert [round(c.elapsed_s) for c in cps] == [0, 3600, 7200, 8100, 9000]


def test_router_length_is_authoritative():
    coords = straight_line(100)
    track = build_track([SectionInput(coords=coords, length_mi=105.0, duration_s=6300)])
    assert track.distance_mi == pytest.approx(105.0)


@pytest.mark.parametrize(
    "minute,second,expected_hour",
    [(29, 59, 13), (30, 0, 14), (0, 0, 13), (59, 59, 14), (15, 0, 13)],
)
def test_eta_rounding_to_nearest_hour(minute, second, expected_hour):
    t = datetime(2026, 11, 21, 13, minute, second, tzinfo=UTC)
    assert round_to_hour(t) == datetime(2026, 11, 21, expected_hour, tzinfo=UTC)


def test_forecast_hour_is_rounded_eta():
    track = track_for(straight_line(100), mph=60)
    cps = sample_checkpoints(track, 25, DEP)
    # 25 mi @ 60 mph = 25 min -> 13:25 -> 13:00; 50 mi = 50 min -> 14:00
    assert cps[1].forecast_hour == datetime(2026, 11, 21, 13, tzinfo=UTC)
    assert cps[2].forecast_hour == datetime(2026, 11, 21, 14, tzinfo=UTC)


def test_naive_departure_rejected():
    with pytest.raises(ValueError):
        sample_checkpoints(track_for(straight_line(10)), 10, datetime(2026, 11, 21, 13))


@pytest.mark.parametrize(
    "a,b,reference_mi",
    [
        # Denver -> Salt Lake City great-circle ~ 371 mi
        ((39.7392, -104.9903), (40.7608, -111.8910), 371.1),
        # New York (JFK) -> Los Angeles (LAX) ~ 2,475 mi
        ((40.6413, -73.7781), (33.9416, -118.4085), 2475.0),
        # 1 degree of latitude ~ 69.09 mi
        ((0.0, 0.0), (1.0, 0.0), 69.09),
    ],
)
def test_haversine_within_half_percent(a, b, reference_mi):
    assert haversine_mi(a, b) == pytest.approx(reference_mi, rel=0.005)
