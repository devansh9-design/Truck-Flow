"""Trip workflow shared by the debug route endpoint (Chunk 1) and /api/analyze (Chunk 2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from clients import risk_engine
from geo.geocode import resolve_place
from geo.routes import CandidateRoute, plan_routes
from routing.sampling import Checkpoint, sample_checkpoints
from routing.track import haversine_mi
from scoring.rank import NO_TRAVEL_WARNING, RankInput, rank_routes
from scoring.score import score_route
from truckrisk_schemas import CheckpointIn, Place, iso_z

from .errors import ValidationFailed

# Origin and destination closer than this after geocoding are "the same place".
SAME_PLACE_MI = 0.1
ROUTE_LETTERS = "ABCDEFGHIJ"


@dataclass
class PlannedRoute:
    id: str
    label: str
    route: CandidateRoute
    checkpoints: list[Checkpoint]
    departure: datetime

    @property
    def arrival(self) -> datetime:
        return self.departure + timedelta(seconds=self.route.duration_s)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "source": self.route.source,
            "distance_mi": round(self.route.distance_mi, 1),
            "duration_s": round(self.route.duration_s),
            "arrival_time": iso_z(self.arrival),
            "geometry": {
                "type": "LineString",
                "coordinates": [[round(lon, 5), round(lat, 5)] for lat, lon in self.route.track.coords],
            },
            "checkpoints": [
                {
                    "id": f"{self.id}-c{cp.index}",
                    "index": cp.index,
                    "mile": round(cp.mile, 1),
                    "lat": round(cp.lat, 5),
                    "lon": round(cp.lon, 5),
                    "eta": iso_z(cp.eta),
                    "forecast_hour": iso_z(cp.forecast_hour),
                }
                for cp in self.checkpoints
            ],
        }


@dataclass
class TripPlan:
    origin: Place
    destination: Place
    departure: datetime
    load_weight_lb: float
    interval_mi: int
    routes: list[PlannedRoute]
    notes: list[str]

    def bbox(self) -> list[float]:
        lats = [p[0] for r in self.routes for p in r.route.track.coords]
        lons = [p[1] for r in self.routes for p in r.route.track.coords]
        return [round(min(lons), 4), round(min(lats), 4), round(max(lons), 4), round(max(lats), 4)]

    def trip_dict(self) -> dict:
        return {
            "origin": self.origin.model_dump(),
            "destination": self.destination.model_dump(),
            "departure_time": iso_z(self.departure),
            "load_weight_lb": self.load_weight_lb,
            "interval_mi": self.interval_mi,
        }


def plan_trip(data: dict) -> TripPlan:
    """Geocode -> 3 truck routes -> checkpoints + ETAs. No weather yet."""
    origin = resolve_place(data["origin"], "origin")
    destination = resolve_place(data["destination"], "destination")
    if haversine_mi((origin.lat, origin.lon), (destination.lat, destination.lon)) < SAME_PLACE_MI:
        raise ValidationFailed(
            "Origin and destination must be different.", {"field": "destination"}
        )

    departure: datetime = data["departure_time"]
    load = float(data["load_weight_lb"])
    interval = int(data["interval_mi"])

    plan = plan_routes(origin, destination, departure, load)
    routes = [
        PlannedRoute(
            id=f"r{i}",
            label=f"Route {ROUTE_LETTERS[i]}",
            route=cand,
            checkpoints=sample_checkpoints(cand.track, interval, departure),
            departure=departure,
        )
        for i, cand in enumerate(plan.routes)
    ]
    return TripPlan(
        origin=origin,
        destination=destination,
        departure=departure,
        load_weight_lb=load,
        interval_mi=interval,
        routes=routes,
        notes=plan.notes,
    )


def analyze_trip(data: dict) -> dict:
    """A3: plan the trip, evaluate every checkpoint's ETA-hour weather, score and rank routes."""
    plan = plan_trip(data)
    route_dicts = {r.id: r.to_dict() for r in plan.routes}

    # Exact (unrounded) positions and ETAs, so Flask's hour rounding matches ours.
    checkpoints = [
        CheckpointIn(id=f"{r.id}-c{cp.index}", lat=cp.lat, lon=cp.lon, eta=cp.eta)
        for r in plan.routes
        for cp in r.checkpoints
    ]
    results = {res.id: res for res in risk_engine.evaluate(plan.load_weight_lb, checkpoints)}

    rank_inputs: list[RankInput] = []
    for r in plan.routes:
        rd = route_dicts[r.id]
        for cp in rd["checkpoints"]:
            res = results[cp["id"]]
            cp["forecast_hour"] = iso_z(res.forecast_hour)
            cp["weather"] = res.weather.model_dump()
            cp["risk"] = res.risk.model_dump(mode="json")
        # Score on unrounded checkpoint miles; the rounded ones are for display.
        levels = [results[c["id"]].risk.level for c in rd["checkpoints"]]
        score = score_route([c.mile for c in r.checkpoints], levels)
        rd["summary"] = score.to_dict()
        rd["warnings"] = [NO_TRAVEL_WARNING] if score.has_no_travel else []
        rank_inputs.append(
            RankInput(
                id=r.id,
                no_travel_mi=score.no_travel_mi,
                severe_mi=score.severe_mi,
                high_mi=score.high_mi,
                avg_risk=score.avg_risk,
                duration_s=r.route.duration_s,
            )
        )

    ranking = rank_routes(rank_inputs)
    routes_out = []
    for rank, rid in enumerate(ranking.order, start=1):
        rd = route_dicts[rid]
        routes_out.append({"id": rid, "rank": rank, "recommended": rank == 1,
                           **{k: v for k, v in rd.items() if k != "id"}})

    return {
        "trip": plan.trip_dict(),
        "routes": routes_out,
        "recommendation": {
            "route_id": ranking.order[0],
            "decided_by": ranking.decided_by,
            "reason": ranking.reason,
        },
        "corridor": {"bbox": plan.bbox()},
        "notes": plan.notes,
    }
