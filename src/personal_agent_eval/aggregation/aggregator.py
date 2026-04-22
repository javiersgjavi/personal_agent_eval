"""Aggregation over deterministic signals and judge outputs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from personal_agent_eval.aggregation.models import (
    DimensionScores,
    FinalEvaluationResult,
    HybridAggregationSummary,
    OverallAssessment,
    SecurityBlock,
)
from personal_agent_eval.config.evaluation_profile import (
    EvaluationProfileConfig,
)
from personal_agent_eval.config.test_config import DeterministicCheck, TestConfig
from personal_agent_eval.deterministic.models import (
    DeterministicCheckOutcome,
    DeterministicEvaluationResult,
)
from personal_agent_eval.judge.models import AggregatedJudgeResult, JudgeDimensions

DimensionName = Literal["task", "process", "autonomy", "closeness", "efficiency", "spark"]
DIMENSION_NAMES: tuple[DimensionName, ...] = (
    "task",
    "process",
    "autonomy",
    "closeness",
    "efficiency",
    "spark",
)

DEFAULT_DECLARATIVE_DIMENSIONS: dict[str, tuple[DimensionName, ...]] = {
    "final_response_present": ("process",),
    "tool_call_count": ("process", "efficiency"),
    "file_exists": ("task",),
    "file_contains": ("task",),
    "path_exists": ("task",),
    "status_is": ("process",),
    "output_artifact_present": ("task",),
}


class HybridAggregator:
    """Compute the final hybrid evaluation result for one run."""

    def aggregate(
        self,
        *,
        test_config: TestConfig,
        evaluation_profile: EvaluationProfileConfig,
        deterministic_result: DeterministicEvaluationResult,
        judge_result: AggregatedJudgeResult,
    ) -> FinalEvaluationResult:
        """Aggregate typed deterministic and judge outputs into the final result.

        V1 policy: the final score is taken directly from the judge's overall assessment when
        available. Per-dimension scores are preserved for observability, but are not blended into a
        weighted final score.
        """
        deterministic_dimensions, deterministic_warnings = _build_deterministic_dimensions(
            test_config=test_config,
            deterministic_result=deterministic_result,
        )
        judge_dimensions = _build_judge_dimensions(judge_result)
        judge_overall = _build_judge_overall(judge_result)

        warnings = [*judge_result.warnings, *deterministic_warnings]
        final_dimensions = judge_dimensions.model_copy(deep=True)
        if judge_overall is None:
            raise ValueError(
                "Final score cannot be computed because the judge did not provide an overall score."
            )
        final_score = judge_overall.score

        return FinalEvaluationResult(
            case_id=deterministic_result.case_id,
            run_id=deterministic_result.run_id,
            deterministic_dimensions=deterministic_dimensions,
            judge_dimensions=judge_dimensions,
            final_dimensions=final_dimensions,
            judge_overall=judge_overall,
            final_score=final_score,
            summary=HybridAggregationSummary(
                deterministic_passed_checks=deterministic_result.summary.passed_checks,
                deterministic_failed_checks=deterministic_result.summary.failed_checks,
                deterministic_error_checks=deterministic_result.summary.error_checks,
                judge_successful_iterations=judge_result.successful_iterations,
                judge_failed_iterations=judge_result.failed_iterations,
            ),
            security=SecurityBlock(),
            warnings=_deduplicate_preserving_order(warnings),
        )


def _build_deterministic_dimensions(
    *,
    test_config: TestConfig,
    deterministic_result: DeterministicEvaluationResult,
) -> tuple[DimensionScores, list[str]]:
    checks_by_id = {check.check_id: check for check in test_config.deterministic_checks}
    scored_outcomes: dict[DimensionName, list[float]] = defaultdict(list)
    warnings: list[str] = []

    for result in deterministic_result.checks:
        check = checks_by_id.get(result.check_id)
        if check is None:
            warnings.append(
                f"Deterministic check '{result.check_id}' was not present in the test config."
            )
            continue

        dimensions = _dimensions_for_check(check)
        if not dimensions:
            continue

        if result.outcome is DeterministicCheckOutcome.ERROR:
            warnings.append(
                f"Deterministic check '{result.check_id}' ended with an error and was excluded "
                "from dimension scoring."
            )
            continue

        numeric_outcome = 10.0 if result.passed else 0.0
        for dimension in dimensions:
            scored_outcomes[dimension].append(numeric_outcome)

    dimension_scores = {
        dimension: (
            sum(scored_outcomes[dimension]) / len(scored_outcomes[dimension])
            if scored_outcomes[dimension]
            else None
        )
        for dimension in DIMENSION_NAMES
    }
    return DimensionScores(**dimension_scores), warnings


def _dimensions_for_check(check: DeterministicCheck) -> tuple[DimensionName, ...]:
    if check.dimensions:
        return tuple(check.dimensions)
    if check.declarative is None:
        return ()
    return DEFAULT_DECLARATIVE_DIMENSIONS.get(check.declarative.kind, ())


def _build_judge_dimensions(judge_result: AggregatedJudgeResult) -> DimensionScores:
    if judge_result.dimensions is None:
        return DimensionScores()
    dimensions: JudgeDimensions = judge_result.dimensions
    return DimensionScores(
        task=dimensions.task,
        process=dimensions.process,
        autonomy=dimensions.autonomy,
        closeness=dimensions.closeness,
        efficiency=dimensions.efficiency,
        spark=dimensions.spark,
    )


def _build_judge_overall(judge_result: AggregatedJudgeResult) -> OverallAssessment | None:
    if judge_result.overall_score is None:
        return None
    return OverallAssessment(
        score=judge_result.overall_score,
        evidence=list(judge_result.overall_evidence),
    )


def _deduplicate_preserving_order(entries: Iterable[str]) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry not in seen:
            deduplicated.append(entry)
            seen.add(entry)
    return deduplicated
