from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent_eval.aggregation import HybridAggregator
from personal_agent_eval.config import load_evaluation_profile, load_test_config
from personal_agent_eval.deterministic.models import (
    DeterministicCheckOutcome,
    DeterministicCheckResult,
    DeterministicEvaluationResult,
    DeterministicEvaluationSummary,
)
from personal_agent_eval.judge.models import (
    AggregatedJudgeResult,
    JudgeDimensions,
    JudgeEvidence,
    JudgeIterationStatus,
    NormalizedJudgeIterationResult,
    RawJudgeRunResult,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_hybrid_aggregation_keeps_sources_separate_and_computes_final_score() -> None:
    test_config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )
    evaluation_profile = load_evaluation_profile(
        FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
    )

    deterministic_result = DeterministicEvaluationResult(
        case_id="example_case",
        run_id="run_001",
        passed=False,
        summary=DeterministicEvaluationSummary(
            total_checks=2,
            passed_checks=1,
            failed_checks=1,
            error_checks=0,
        ),
        checks=[
            DeterministicCheckResult(
                check_id="final-response-present",
                kind="final_response_present",
                source="declarative",
                outcome=DeterministicCheckOutcome.PASSED,
                passed=True,
            ),
            DeterministicCheckResult(
                check_id="local-python-hook",
                kind="python_hook",
                source="python_hook",
                outcome=DeterministicCheckOutcome.FAILED,
                passed=False,
            ),
        ],
    )
    judge_result = _build_judge_result(
        dimensions=JudgeDimensions(
            task=8.0,
            process=6.0,
            autonomy=7.5,
            closeness=6.5,
            efficiency=5.0,
            spark=6.0,
        ),
        overall_score=6.8,
    )

    result = HybridAggregator().aggregate(
        test_config=test_config,
        evaluation_profile=evaluation_profile,
        deterministic_result=deterministic_result,
        judge_result=judge_result,
    )

    assert result.deterministic_dimensions.task == 0.0
    assert result.deterministic_dimensions.process == 10.0
    assert result.judge_dimensions.task == 8.0
    assert result.judge_dimensions.process == 6.0
    assert result.final_dimensions.task == 8.0
    assert result.final_dimensions.process == 6.0
    assert result.final_dimensions.autonomy == 7.5
    assert result.judge_overall is not None
    assert result.judge_overall.score == 6.8
    assert result.final_score == pytest.approx(6.8)
    assert result.dimension_resolutions.task.policy == "judge_only"
    assert result.dimension_resolutions.task.source_used == "judge"
    assert result.dimension_resolutions.autonomy.policy == "judge_only"
    assert result.security.verdict == "not_evaluated"
    assert result.warnings == []


def test_hybrid_aggregation_falls_back_to_judge_when_deterministic_signal_is_missing() -> None:
    test_config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )
    evaluation_profile = load_evaluation_profile(
        FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
    )

    deterministic_result = DeterministicEvaluationResult(
        case_id="example_case",
        run_id="run_002",
        passed=True,
        summary=DeterministicEvaluationSummary(
            total_checks=1,
            passed_checks=1,
            failed_checks=0,
            error_checks=0,
        ),
        checks=[
            DeterministicCheckResult(
                check_id="final-response-present",
                kind="final_response_present",
                source="declarative",
                outcome=DeterministicCheckOutcome.PASSED,
                passed=True,
            )
        ],
    )
    judge_result = _build_judge_result(
        dimensions=JudgeDimensions(
            task=7.0,
            process=6.5,
            autonomy=7.0,
            closeness=6.0,
            efficiency=5.5,
            spark=5.0,
        ),
        overall_score=7.0,
        warnings=["Excluded non-successful repetitions from aggregation: 2."],
    )

    result = HybridAggregator().aggregate(
        test_config=test_config,
        evaluation_profile=evaluation_profile,
        deterministic_result=deterministic_result,
        judge_result=judge_result,
    )

    assert result.deterministic_dimensions.task is None
    assert result.final_dimensions.task == 7.0
    assert result.dimension_resolutions.task.source_used == "judge"
    assert "Excluded non-successful repetitions from aggregation: 2." in result.warnings


def test_hybrid_aggregation_respects_deterministic_only_policy_with_judge_fallback() -> None:
    test_config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )
    base_profile = load_evaluation_profile(
        FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
    )
    evaluation_profile = base_profile.model_copy(
        update={
            "final_aggregation": base_profile.final_aggregation.model_copy(
                update={
                    "dimensions": base_profile.final_aggregation.dimensions.model_copy(
                        update={
                            "efficiency": (
                                base_profile.final_aggregation.dimensions.efficiency.model_copy(
                                    update={"policy": "deterministic_only"}
                                )
                            ),
                        }
                    )
                }
            )
        }
    )

    deterministic_result = DeterministicEvaluationResult(
        case_id="example_case",
        run_id="run_003",
        passed=True,
        summary=DeterministicEvaluationSummary(
            total_checks=1,
            passed_checks=1,
            failed_checks=0,
            error_checks=0,
        ),
        checks=[
            DeterministicCheckResult(
                check_id="final-response-present",
                kind="final_response_present",
                source="declarative",
                outcome=DeterministicCheckOutcome.PASSED,
                passed=True,
            )
        ],
    )
    judge_result = _build_judge_result(
        dimensions=JudgeDimensions(
            task=8.0,
            process=6.0,
            autonomy=7.5,
            closeness=6.5,
            efficiency=4.0,
            spark=6.0,
        ),
        overall_score=6.0,
    )

    result = HybridAggregator().aggregate(
        test_config=test_config,
        evaluation_profile=evaluation_profile,
        deterministic_result=deterministic_result,
        judge_result=judge_result,
    )

    assert result.final_dimensions.efficiency == 4.0
    assert result.dimension_resolutions.efficiency.policy == "judge_only"
    assert result.dimension_resolutions.efficiency.source_used == "judge"


def _build_judge_result(
    *,
    dimensions: JudgeDimensions,
    overall_score: float,
    warnings: list[str] | None = None,
) -> AggregatedJudgeResult:
    success_iteration = NormalizedJudgeIterationResult(
        judge_name="primary_judge",
        judge_model="minimax/minimax-m2.7",
        repetition_index=0,
        status=JudgeIterationStatus.SUCCESS,
        dimensions=dimensions,
        summary="The result is acceptable.",
        evidence=JudgeEvidence(
            task=["Task evidence"],
            process=["Process evidence"],
            autonomy=["Autonomy evidence"],
            closeness=["Closeness evidence"],
            efficiency=["Efficiency evidence"],
            spark=["Spark evidence"],
        ),
        overall_score=overall_score,
        overall_evidence=["Overall evidence"],
        raw_result_ref="raw_001",
    )
    return AggregatedJudgeResult(
        judge_name="primary_judge",
        judge_model="minimax/minimax-m2.7",
        configured_repetitions=1,
        successful_iterations=1,
        failed_iterations=0,
        used_repetition_indices=[0],
        excluded_repetition_indices=[],
        warnings=warnings or [],
        dimensions=dimensions,
        summary="The result is acceptable.",
        evidence=success_iteration.evidence,
        overall_score=overall_score,
        overall_evidence=["Overall evidence"],
        iteration_results=[success_iteration],
        raw_results=[
            RawJudgeRunResult(
                raw_result_ref="raw_001",
                judge_name="primary_judge",
                judge_model="minimax/minimax-m2.7",
                repetition_index=0,
                attempt_index=0,
                status=JudgeIterationStatus.SUCCESS,
                response_content="{}",
            )
        ],
    )
