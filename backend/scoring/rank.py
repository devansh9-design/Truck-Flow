"""Route ranking (CORE-4, spec §5.4 and D4, D6).

Sort key, in this exact order and nothing else:
    0. no_travel_mi  fewest   (our safety key, D4)
    1. severe_mi     fewest   (spec)
    2. high_mi       fewest   (spec)
    3. avg_risk      lowest   (spec)
    4. duration_s    shortest (spec)
Miles are compared rounded to 0.1 mi and avg_risk to 0.01 (D6), so
floating-point noise never decides a ranking.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

RANK_KEYS = ("no_travel_mi", "severe_mi", "high_mi", "avg_risk", "duration_s")

_PRECISION = {"no_travel_mi": 1, "severe_mi": 1, "high_mi": 1, "avg_risk": 2, "duration_s": 0}
_NAMES = {
    "no_travel_mi": "No Travel miles",
    "severe_mi": "Severe miles",
    "high_mi": "High miles",
    "avg_risk": "average risk",
    "duration_s": "travel time",
}
_WINNER_VERB = {
    "no_travel_mi": "fewest",
    "severe_mi": "fewest",
    "high_mi": "fewest",
    "avg_risk": "lowest",
    "duration_s": "shortest",
}
NO_TRAVEL_WARNING = "NO_TRAVEL_CONDITIONS"


@dataclass(frozen=True)
class RankInput:
    id: str
    no_travel_mi: float
    severe_mi: float
    high_mi: float
    avg_risk: float
    duration_s: float


@dataclass(frozen=True)
class Ranking:
    order: list[str]  # route ids, rank 1 first
    decided_by: str  # one of RANK_KEYS, "tie" or "only_route"
    reason: str


def rank_key(r: RankInput) -> tuple:
    return tuple(round(getattr(r, k), _PRECISION[k]) for k in RANK_KEYS)


def _fmt(key: str, value: float) -> str:
    if key == "duration_s":
        h, m = divmod(round(value / 60), 60)
        return f"{h} h {m:02d} min"
    return f"{value:.{_PRECISION[key]}f}"


def rank_routes(routes: Sequence[RankInput]) -> Ranking:
    if not routes:
        raise ValueError("no routes to rank")
    ordered = sorted(routes, key=rank_key)  # stable: equal keys keep input order
    ids = [r.id for r in ordered]
    if len(ordered) == 1:
        return Ranking(ids, "only_route", "Only one route option is available.")

    first, second = rank_key(ordered[0]), rank_key(ordered[1])
    tied: list[str] = []
    for i, key in enumerate(RANK_KEYS):
        if first[i] != second[i]:
            winner = _fmt(key, first[i])
            runner = _fmt(key, second[i])
            prefix = ""
            if tied:
                prefix = "Tied on " + ", ".join(
                    f"{_NAMES[k]} ({_fmt(k, first[RANK_KEYS.index(k)])})" for k in tied
                ) + "; "
            verb = _WINNER_VERB[key]
            text = f"{verb} {_NAMES[key]} ({winner} vs {runner})."
            reason = prefix + (text if prefix else text[0].upper() + text[1:])
            return Ranking(ids, key, reason)
        tied.append(key)
    return Ranking(ids, "tie", "The top routes are tied on every ranking key; kept the router's order.")
