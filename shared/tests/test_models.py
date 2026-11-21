from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from truckrisk_schemas import (
    CheckpointIn,
    EvaluateRequest,
    RiskLevel,
    lb_to_kg,
    meters_to_miles,
)


def test_risk_scores_are_ordinal_1_to_5():
    assert [lvl.score for lvl in RiskLevel] == [1, 2, 3, 4, 5]


def test_checkpoint_requires_timezone():
    with pytest.raises(ValidationError):
        CheckpointIn(id="c0", lat=1, lon=1, eta=datetime(2026, 11, 21, 13))
    ok = CheckpointIn(id="c0", lat=1, lon=1, eta=datetime(2026, 11, 21, 13, tzinfo=UTC))
    assert ok.eta.tzinfo is not None


def test_evaluate_request_rejects_extra_fields_and_bad_load():
    with pytest.raises(ValidationError):
        EvaluateRequest(load_weight_lb=0, checkpoints=[])
    with pytest.raises(ValidationError):
        EvaluateRequest.model_validate({"load_weight_lb": 10, "checkpoints": [], "x": 1})


def test_unit_conversions_are_exact():
    assert meters_to_miles(1609.344) == pytest.approx(1.0)
    assert lb_to_kg(1) == pytest.approx(0.45359237)


def test_alert_fixtures_validate():
    from pathlib import Path

    from truckrisk_schemas import AlertsRequest, AlertsResponse

    fx = Path(__file__).resolve().parents[1] / "fixtures"
    AlertsRequest.model_validate_json((fx / "alerts_request.json").read_text())
    resp = AlertsResponse.model_validate_json((fx / "alerts_response.json").read_text())
    assert resp.coverage == "US" and resp.alerts[0].severity == "Severe"
