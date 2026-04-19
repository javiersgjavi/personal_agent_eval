from __future__ import annotations

import pytest

from personal_agent_eval.serialization.json_floats import round_floats_for_json


def test_round_floats_trims_binary_float_noise_for_scores() -> None:
    payload = {"final_score": 7.380000000000002}
    out = round_floats_for_json(payload)
    assert out["final_score"] == 7.38


def test_round_floats_preserves_cost_precision() -> None:
    payload = {"cost_usd": 0.004927612345}
    out = round_floats_for_json(payload)
    assert out["cost_usd"] == pytest.approx(0.004928, abs=1e-9)


def test_round_floats_nested_dimensions() -> None:
    payload = {
        "final_dimensions": {
            "task": 8.000000000000002,
            "process": 8.2,
        }
    }
    out = round_floats_for_json(payload)
    assert out["final_dimensions"]["task"] == 8.0
    assert out["final_dimensions"]["process"] == 8.2
