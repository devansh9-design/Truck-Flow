"""CORE-4: scoring + ranking (Testing strategy §2.3; ranking halves of S2–S7, S9, S10)."""

import dataclasses
import itertools

import pytest

from scoring.rank import RANK_KEYS, RankInput, rank_key, rank_routes
from scoring.score import score_route
from truckrisk_schemas import RiskLevel

L, M, H, S, NT = (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.SEVERE,
                  RiskLevel.NO_TRAVEL)


# --- scoring -------------------------------------------------------------------


def test_segment_level_is_worse_endpoint():
    sc = score_route([0, 25, 50], [L, S, L])
    assert [seg.level for seg in sc.segments] == [S, S]
    assert sc.severe_mi == 50 and sc.miles_by_level[L] == 0


def test_miles_per_level_sum_to_route_distance():
    miles = [0, 25, 50, 75, 100, 103.4]
    sc = score_route(miles, [L, M, H, L, NT, L])
    assert sum(sc.miles_by_level.values()) == pytest.approx(103.4, abs=0.1)


def test_severe_and_no_travel_are_separate():
    sc = score_route([0, 10, 20], [NT, NT, L])
    assert sc.no_travel_mi == 20 and sc.severe_mi == 0
    assert sc.has_no_travel and sc.max_level == NT


def test_distance_weighted_average_by_hand():
    # segments: [0,10]=max(L,L)=1 ; [10,40]=max(L,H)=3 ; [40,50]=max(H,M)=3
    sc = score_route([0, 10, 40, 50], [L, L, H, M])
    assert sc.avg_risk == pytest.approx((10 * 1 + 30 * 3 + 10 * 3) / 50)  # 2.6


def test_summary_dict_shape_and_rounding():
    d = score_route([0, 12.345, 30.0], [L, H, L]).to_dict()
    assert d == {
        "miles_by_level": {"LOW": 0.0, "MODERATE": 0.0, "HIGH": 30.0, "SEVERE": 0.0, "NO_TRAVEL": 0.0},
        "severe_mi": 0.0,
        "high_mi": 30.0,
        "no_travel_mi": 0.0,
        "has_no_travel": False,
        "avg_risk": 3.0,
        "max_level": "HIGH",
    }


def test_single_checkpoint_route():
    sc = score_route([0], [M])
    assert sc.avg_risk == 2 and sum(sc.miles_by_level.values()) == 0


def test_bad_inputs():
    with pytest.raises(ValueError):
        score_route([0, 10], [L])
    with pytest.raises(ValueError):
        score_route([0, 10, 5], [L, L, L])


# --- ranking -------------------------------------------------------------------


def R(id, nt=0.0, sev=0.0, high=0.0, avg=1.0, dur=3600.0):  # noqa: N802
    return RankInput(id=id, no_travel_mi=nt, severe_mi=sev, high_mi=high, avg_risk=avg, duration_s=dur)


def test_keys_are_exactly_the_agreed_order():
    assert RANK_KEYS == ("no_travel_mi", "severe_mi", "high_mi", "avg_risk", "duration_s")


def test_s10_no_travel_ranks_below_only_severe():
    """A: 5 No Travel mi, 0 Severe; B: 0 No Travel, 10 Severe -> B recommended."""
    r = rank_routes([R("A", nt=5, sev=0, dur=100), R("B", nt=0, sev=10, dur=200)])
    assert r.order == ["B", "A"] and r.decided_by == "no_travel_mi"
    assert r.reason == "Fewest No Travel miles (0.0 vs 5.0)."


def test_s2_fewer_severe_miles_wins_over_faster():
    r = rank_routes([R("fast", sev=40, dur=100), R("clear", sev=0, dur=200)])
    assert r.order == ["clear", "fast"] and r.decided_by == "severe_mi"


def test_s5_equal_severe_fewer_high_wins():
    r = rank_routes([R("a", sev=5, high=58.0), R("b", sev=5, high=31.2)])
    assert r.order == ["b", "a"] and r.decided_by == "high_mi"
    assert r.reason == "Tied on No Travel miles (0.0), Severe miles (5.0); fewest High miles (31.2 vs 58.0)."


def test_s6_lower_average_wins():
    r = rank_routes([R("a", avg=1.8), R("b", avg=1.4)])
    assert r.order == ["b", "a"] and r.decided_by == "avg_risk"


def test_s7_everything_equal_shorter_duration_wins():
    r = rank_routes([R("slow", dur=7200), R("fast", dur=3600)])
    assert r.order == ["fast", "slow"] and r.decided_by == "duration_s"
    assert "shortest travel time (1 h 00 min vs 2 h 00 min)" in r.reason


def test_s9_all_no_travel_fewest_wins_then_spec_keys():
    r = rank_routes([R("a", nt=30, sev=0), R("b", nt=12, sev=50), R("c", nt=12, sev=20)])
    assert r.order == ["c", "b", "a"] and r.decided_by == "severe_mi"


def test_d6_ties_within_rounding_fall_through():
    r = rank_routes([R("a", sev=10.04, dur=200), R("b", sev=10.01, dur=100)])
    assert r.order == ["b", "a"] and r.decided_by == "duration_s"
    r = rank_routes([R("a", avg=1.304, dur=200), R("b", avg=1.296, dur=100)])
    assert r.decided_by == "duration_s"


def test_full_tie_keeps_input_order():
    r = rank_routes([R("x"), R("y")])
    assert r.order == ["x", "y"] and r.decided_by == "tie"


def test_only_route():
    assert rank_routes([R("x")]).decided_by == "only_route"


def test_no_other_field_affects_order():
    """Only the five keys are read: a subclass with extra fields ranks identically."""

    @dataclasses.dataclass(frozen=True)
    class WithExtras(RankInput):
        distance_mi: float = 0.0
        label: str = ""

    base = [R("a", sev=3, dur=500), R("b", sev=3, high=1, dur=100), R("c", nt=1)]
    expected = rank_routes(base).order
    for dist, label in itertools.product([1.0, 9999.0], ["Z", "A"]):
        extra = [WithExtras(**dataclasses.asdict(x), distance_mi=dist, label=label) for x in base]
        assert rank_routes(extra).order == expected
    assert rank_key(base[0]) == (0.0, 3.0, 0.0, 1.0, 500.0)


def test_input_order_irrelevant_when_keys_differ():
    rs = [R("a", sev=1), R("b", high=4), R("c", nt=2), R("d", avg=2.0)]
    for perm in itertools.permutations(rs):
        assert rank_routes(list(perm)).order == ["d", "b", "a", "c"]
