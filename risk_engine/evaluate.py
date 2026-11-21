"""Checkpoint weather at the ETA hour + risk rules -> one result per checkpoint (B2)."""

from __future__ import annotations

from datetime import UTC

from weather import BeyondForecast, ForecastProvider, IncompleteWeather, cell_of

from rules import evaluate as classify
from truckrisk_schemas import (
    CheckpointResult,
    EvaluateRequest,
    EvaluateResponse,
    iso_z,
    round_to_hour,
)


class BeyondHorizon(Exception):
    def __init__(self, ids: list[str], latest: str | None):
        super().__init__("Checkpoint ETA is beyond the available forecast.")
        self.ids = ids
        self.latest = latest


def evaluate_checkpoints(req: EvaluateRequest, provider: ForecastProvider) -> EvaluateResponse:
    """All or nothing: any checkpoint that cannot be evaluated fails the whole call.

    Past the last forecast hour -> BeyondHorizon (422). Missing or null data inside
    the forecast range -> IncompleteWeather (502). Missing data is never read as calm.
    """
    hours = [round_to_hour(cp.eta.astimezone(UTC)) for cp in req.checkpoints]
    cells = [cell_of(cp.lat, cp.lon) for cp in req.checkpoints]
    series, meta = provider.series(cells)

    results: list[CheckpointResult] = []
    beyond: list[str] = []
    incomplete: IncompleteWeather | None = None
    latest: str | None = None
    for cp, hour, cell in zip(req.checkpoints, hours, cells, strict=True):
        s = series[cell]
        try:
            weather = s.at(hour)
        except BeyondForecast:
            beyond.append(cp.id)
            latest = iso_z(s.last_hour)
            continue
        except IncompleteWeather as exc:
            incomplete = incomplete or exc
            continue
        results.append(
            CheckpointResult(
                id=cp.id,
                forecast_hour=hour,
                weather=weather,
                risk=classify(weather, req.load_weight_lb),
            )
        )
    if beyond:
        raise BeyondHorizon(beyond, latest)
    if incomplete is not None:
        raise incomplete
    return EvaluateResponse(results=results, meta={"source": "open-meteo", **meta})
