"""Checkpoint weather at the ETA hour + risk rules -> one result per checkpoint (B2)."""

from __future__ import annotations

from datetime import UTC

from weather import ForecastProvider, cell_of

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
    hours = [round_to_hour(cp.eta.astimezone(UTC)) for cp in req.checkpoints]
    cells = [cell_of(cp.lat, cp.lon) for cp in req.checkpoints]
    series, meta = provider.series(cells)

    results: list[CheckpointResult] = []
    beyond: list[str] = []
    latest: str | None = None
    for cp, hour, cell in zip(req.checkpoints, hours, cells, strict=True):
        s = series[cell]
        weather = s.at(hour)
        if weather is None:
            beyond.append(cp.id)
            latest = iso_z(s.last_hour)
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
    return EvaluateResponse(results=results, meta={"source": "open-meteo", **meta})
