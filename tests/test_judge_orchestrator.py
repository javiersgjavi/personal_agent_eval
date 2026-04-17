from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from personal_agent_eval.artifacts import (
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
)
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    TraceEvent,
)
from personal_agent_eval.config.test_config import load_test_config
from personal_agent_eval.judge import (
    JudgeIterationStatus,
    JudgeOrchestrator,
    RawJudgeRunResult,
    build_judge_messages,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


@dataclass
class FakeJudgeClient:
    results: list[RawJudgeRunResult]

    def run_once(self, invocation: object) -> RawJudgeRunResult:
        return self.results.pop(0)


def _build_artifact() -> RunArtifact:
    trace: list[TraceEvent] = [
        MessageTraceEvent(
            sequence=0,
            event_type="message",
            role="user",
            content="Please complete the task.",
        ),
        FinalOutputTraceEvent(
            sequence=1,
            event_type="final_output",
            content="Task completed with a concise answer.",
        ),
    ]
    return RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="run-judge-001",
            case_id="example_case",
            suite_id="example_suite",
            run_profile_id="default",
            runner_type="llm_probe",
        ),
        status=RunStatus.SUCCESS,
        request=RunRequestMetadata(requested_model="openai/gpt-5-mini"),
        trace=trace,
    )


def _build_raw_result(
    *,
    repetition_index: int,
    attempt_index: int,
    status: JudgeIterationStatus,
    content: str | None = None,
    parsed_response: dict[str, object] | None = None,
    error_message: str | None = None,
) -> RawJudgeRunResult:
    return RawJudgeRunResult(
        raw_result_ref=f"rubric_judge:repetition:{repetition_index}:attempt:{attempt_index}",
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        repetition_index=repetition_index,
        attempt_index=attempt_index,
        status=status,
        request_messages=[{"role": "user", "content": "payload"}],
        response_content=content,
        parsed_response=parsed_response,
        error_message=error_message,
    )


def _valid_contract(
    *,
    task: float = 4.0,
    process: float = 3.0,
    autonomy: float = 4.0,
    closeness: float = 5.0,
    efficiency: float = 2.0,
    spark: float = 3.0,
    empty_evidence_dimension: str | None = None,
) -> dict[str, object]:
    evidence = {
        "task": ["Completed the task."],
        "process": ["Followed a clear process."],
        "autonomy": ["Did not need extra guidance."],
        "closeness": ["Stayed close to the request."],
        "efficiency": ["Could be shorter."],
        "spark": ["Included one useful touch."],
    }
    if empty_evidence_dimension is not None:
        evidence[empty_evidence_dimension] = []
    return {
        "dimensions": {
            "task": task,
            "process": process,
            "autonomy": autonomy,
            "closeness": closeness,
            "efficiency": efficiency,
            "spark": spark,
        },
        "summary": "Helpful overall result.",
        "evidence": evidence,
    }


def test_build_judge_messages_includes_case_artifact_and_deterministic_summary() -> None:
    config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )

    messages = build_judge_messages(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=_build_artifact(),
        deterministic_summary={"passed": True, "failed_checks": 0},
    )

    assert len(messages) == 2
    assert "strict evaluation judge" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["judge_name"] == "rubric_judge"
    assert payload["dimensions"] == [
        "task",
        "process",
        "autonomy",
        "closeness",
        "efficiency",
        "spark",
    ]
    assert payload["case_context"]["case_id"] == "example_case"
    assert payload["run_artifact"]["identity"]["run_id"] == "run-judge-001"
    assert payload["deterministic_summary"] == {"passed": True, "failed_checks": 0}


def test_orchestrator_records_successful_iteration_and_aggregation() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(),
                )
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
    )

    assert result.successful_iterations == 1
    assert result.failed_iterations == 0
    assert result.used_repetition_indices == [0]
    assert result.excluded_repetition_indices == []
    assert result.dimensions is not None
    assert result.dimensions.task == 4.0
    assert result.iteration_results[0].status is JudgeIterationStatus.SUCCESS


def test_orchestrator_retries_then_succeeds() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.PROVIDER_ERROR,
                    error_message="Temporary upstream failure.",
                ),
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=1,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=5.0),
                ),
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
        max_retries=1,
    )

    assert result.successful_iterations == 1
    assert len(result.raw_results) == 2
    assert result.iteration_results[0].status is JudgeIterationStatus.SUCCESS
    assert any("succeeded after 1 retry attempt" in warning for warning in result.warnings)


def test_orchestrator_retries_then_keeps_failed_repetition_visible() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.TIMED_OUT,
                    error_message="Timed out.",
                ),
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=1,
                    status=JudgeIterationStatus.PROVIDER_ERROR,
                    error_message="Still unavailable.",
                ),
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
        max_retries=1,
    )

    assert result.successful_iterations == 0
    assert result.failed_iterations == 1
    assert result.used_repetition_indices == []
    assert result.excluded_repetition_indices == [0]
    assert result.iteration_results[0].status is JudgeIterationStatus.FAILED
    assert any("failed after 2 total attempts" in warning for warning in result.warnings)


def test_orchestrator_marks_structurally_invalid_output() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    content="{not-json",
                )
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
    )

    assert result.iteration_results[0].status is JudgeIterationStatus.INVALID_OUTPUT
    assert result.successful_iterations == 0
    assert result.failed_iterations == 1


def test_orchestrator_keeps_success_with_incomplete_evidence_warning() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(empty_evidence_dimension="spark"),
                )
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
    )

    assert result.iteration_results[0].status is JudgeIterationStatus.SUCCESS
    assert any("evidence for dimension 'spark'" in warning.lower() for warning in result.warnings)


def test_orchestrator_aggregates_successful_iterations_only_with_median() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=1.0, efficiency=1.0),
                ),
                _build_raw_result(
                    repetition_index=1,
                    attempt_index=0,
                    status=JudgeIterationStatus.PROVIDER_ERROR,
                    error_message="Provider error.",
                ),
                _build_raw_result(
                    repetition_index=2,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=5.0, efficiency=3.0),
                ),
                _build_raw_result(
                    repetition_index=3,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=3.0, efficiency=5.0),
                ),
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=4,
    )

    assert result.successful_iterations == 3
    assert result.failed_iterations == 1
    assert result.used_repetition_indices == [0, 2, 3]
    assert result.excluded_repetition_indices == [1]
    assert result.dimensions is not None
    assert result.dimensions.task == 3.0
    assert result.dimensions.efficiency == 3.0
