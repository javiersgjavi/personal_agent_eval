from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from personal_agent_eval.artifacts import (
    ProviderMetadata,
    RunArtifact,
    RunArtifactIdentity,
    RunError,
    RunRequestMetadata,
    RunStatus,
    ToolCallTraceEvent,
)
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    LlmExecutionParameters,
    MessageTraceEvent,
    NormalizedUsage,
    OutputArtifactRef,
    RunTiming,
    ToolResultTraceEvent,
    UsageMetadata,
)


def build_identity() -> RunArtifactIdentity:
    return RunArtifactIdentity(
        schema_version=1,
        run_id="run-0001",
        case_id="example_case",
        suite_id="example_suite",
        run_profile_id="default",
        runner_type="llm_probe",
    )


def build_request() -> RunRequestMetadata:
    return RunRequestMetadata(
        requested_model="openai/gpt-5-mini",
        gateway="openrouter",
        execution_parameters=LlmExecutionParameters(
            temperature=0.2,
            top_p=0.95,
            max_tokens=512,
            seed=7,
            max_turns=12,
            timeout_seconds=30.0,
            retries=2,
            tool_choice={"type": "auto"},
        ),
        metadata={"request_origin": "suite_runner"},
    )


def build_provider() -> ProviderMetadata:
    return ProviderMetadata(
        gateway="openrouter",
        provider_name="openai",
        provider_model_id="openai/gpt-5-mini-2026-04-01",
        request_id="req_123",
        response_id="resp_456",
        finish_reason="stop",
        native_finish_reason="end_turn",
        metadata={"region": "us"},
    )


def build_success_artifact() -> RunArtifact:
    return RunArtifact(
        identity=build_identity(),
        status=RunStatus.SUCCESS,
        timing=RunTiming(
            queued_at=datetime(2026, 4, 17, 10, 0, tzinfo=UTC),
            started_at=datetime(2026, 4, 17, 10, 0, 1, tzinfo=UTC),
            completed_at=datetime(2026, 4, 17, 10, 0, 3, tzinfo=UTC),
            duration_seconds=2.0,
        ),
        request=build_request(),
        provider=build_provider(),
        usage=UsageMetadata(
            normalized=NormalizedUsage(
                input_tokens=120,
                output_tokens=48,
                total_tokens=168,
                reasoning_tokens=16,
                cached_input_tokens=8,
                cache_write_tokens=5,
            ),
            cost_usd=0.002345,
            raw_provider_usage={"prompt_tokens": 120, "completion_tokens": 48, "cost": "0.002345"},
        ),
        trace=[
            MessageTraceEvent(
                sequence=0,
                event_type="message",
                role="user",
                content="Run the check.",
            ),
            ToolCallTraceEvent(
                sequence=1,
                event_type="tool_call",
                call_id="call_1",
                tool_name="shell",
                raw_arguments={"cmd": "echo ok"},
                parsed_arguments={"cmd": "echo ok"},
            ),
            ToolResultTraceEvent(
                sequence=2,
                event_type="tool_result",
                call_id="call_1",
                status="success",
                output={"stdout": "ok"},
            ),
            FinalOutputTraceEvent(
                sequence=3,
                event_type="final_output",
                content="Completed successfully.",
            ),
        ],
        output_artifacts=[
            OutputArtifactRef(
                artifact_id="transcript",
                artifact_type="trace_json",
                uri="file:///tmp/run-0001/trace.json",
                media_type="application/json",
                byte_size=512,
                sha256="abc123",
                metadata={"retention": "ephemeral"},
            )
        ],
        runner_metadata={"conversation_id": "conv_1"},
    )


def test_run_artifact_serializes_to_json_ready_dict() -> None:
    artifact = build_success_artifact()

    payload: dict[str, Any] = artifact.to_json_dict()

    assert payload["identity"]["schema_version"] == 1
    assert payload["status"] == "success"
    assert payload["request"]["requested_model"] == "openai/gpt-5-mini"
    assert payload["request"]["gateway"] == "openrouter"
    assert payload["provider"]["provider_name"] == "openai"
    assert payload["provider"]["provider_model_id"] == "openai/gpt-5-mini-2026-04-01"
    assert payload["provider"]["request_id"] == "req_123"
    assert payload["provider"]["response_id"] == "resp_456"
    assert payload["provider"]["finish_reason"] == "stop"
    assert payload["provider"]["native_finish_reason"] == "end_turn"
    assert payload["usage"]["normalized"]["total_tokens"] == 168
    assert payload["usage"]["normalized"]["cache_write_tokens"] == 5
    assert payload["usage"]["cost_usd"] == 0.002345
    assert payload["usage"]["raw_provider_usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 48,
        "cost": "0.002345",
    }
    assert payload["trace"][1]["event_type"] == "tool_call"
    assert payload["trace"][1]["call_id"] == "call_1"
    assert payload["trace"][1]["tool_name"] == "shell"
    assert payload["trace"][1]["raw_arguments"] == {"cmd": "echo ok"}
    assert payload["trace"][1]["parsed_arguments"] == {"cmd": "echo ok"}


def test_run_status_values_match_v1_contract() -> None:
    assert {status.value for status in RunStatus} == {
        "success",
        "failed",
        "timed_out",
        "invalid",
        "provider_error",
    }


def test_run_artifact_preserves_sequential_event_order() -> None:
    artifact = build_success_artifact()

    assert [event.sequence for event in artifact.trace] == [0, 1, 2, 3]


def test_run_artifact_rejects_non_contiguous_trace_sequence() -> None:
    with pytest.raises(ValidationError, match="Trace event sequences must be contiguous"):
        RunArtifact(
            identity=build_identity(),
            status=RunStatus.SUCCESS,
            request=build_request(),
            trace=[
                MessageTraceEvent(
                    sequence=0,
                    event_type="message",
                    role="user",
                    content="first",
                ),
                FinalOutputTraceEvent(
                    sequence=2,
                    event_type="final_output",
                    content="second",
                ),
            ],
        )


def test_run_artifact_requires_error_for_non_success_status() -> None:
    with pytest.raises(ValidationError, match="Non-successful runs must include an error object"):
        RunArtifact(
            identity=build_identity(),
            status=RunStatus.PROVIDER_ERROR,
            request=build_request(),
        )


def test_run_artifact_rejects_error_for_success_status() -> None:
    with pytest.raises(ValidationError, match="Successful runs cannot include an error object"):
        RunArtifact(
            identity=build_identity(),
            status=RunStatus.SUCCESS,
            request=build_request(),
            error=RunError(code="unexpected", message="should not be present"),
        )


def test_run_artifact_supports_explicit_error_structure() -> None:
    artifact = RunArtifact(
        identity=build_identity(),
        status=RunStatus.TIMED_OUT,
        request=build_request(),
        error=RunError(
            code="timeout",
            message="The runner exceeded the configured timeout.",
            error_type="runner_timeout",
            retryable=False,
            provider_code="deadline_exceeded",
            metadata={"timeout_seconds": 30.0},
        ),
    )

    assert artifact.error is not None
    assert artifact.error.code == "timeout"
    assert artifact.error.provider_code == "deadline_exceeded"
    assert artifact.error.metadata["timeout_seconds"] == 30.0


def test_run_timing_rejects_invalid_timestamp_order() -> None:
    with pytest.raises(ValidationError, match="'completed_at' must be greater"):
        RunTiming(
            started_at=datetime(2026, 4, 17, 10, 0, 1, tzinfo=UTC),
            completed_at=datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC),
        )
