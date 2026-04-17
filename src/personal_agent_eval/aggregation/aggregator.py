"""Hybrid aggregation over deterministic and judge outputs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from personal_agent_eval.aggregation.models import (
    DimensionResolution,
    DimensionResolutions,
    DimensionScores,
    FinalEvaluationResult,
    HybridAggregationSummary,
    SecurityBlock,
)
from personal_agent_eval.config.evaluation_profile import (
    EvaluationProfileConfig,
    FinalDimensionAggregationConfig,
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
        """Aggregate typed deterministic and judge outputs into the final result."""
        deterministic_dimensions, deterministic_warnings = _build_deterministic_dimensions(
            test_config=test_config,
            deterministic_result=deterministic_result,
        )
        judge_dimensions = _build_judge_dimensions(judge_result)

        final_dimension_values: dict[DimensionName, float | None] = {}
        resolution_payload: dict[DimensionName, DimensionResolution] = {}
        warnings = [*judge_result.warnings, *deterministic_warnings]

        for dimension in DIMENSION_NAMES:
            policy = _policy_for_dimension(
                evaluation_profile=evaluation_profile,
                dimension=dimension,
            )
            deterministic_score = getattr(deterministic_dimensions, dimension)
            judge_score = getattr(judge_dimensions, dimension)

            final_score, resolution, dimension_warnings = _resolve_dimension(
                dimension=dimension,
                policy=policy,
                deterministic_score=deterministic_score,
                judge_score=judge_score,
            )
            final_dimension_values[dimension] = final_score
            resolution_payload[dimension] = resolution
            warnings.extend(dimension_warnings)

        final_dimensions = DimensionScores(**final_dimension_values)
        final_score = _compute_final_score(
            final_dimensions=final_dimensions,
            evaluation_profile=evaluation_profile,
        )

        return FinalEvaluationResult(
            case_id=deterministic_result.case_id,
            run_id=deterministic_result.run_id,
            deterministic_dimensions=deterministic_dimensions,
            judge_dimensions=judge_dimensions,
            final_dimensions=final_dimensions,
            dimension_resolutions=DimensionResolutions(**resolution_payload),
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


def _policy_for_dimension(
    *,
    evaluation_profile: EvaluationProfileConfig,
    dimension: DimensionName,
) -> FinalDimensionAggregationConfig:
    return getattr(evaluation_profile.final_aggregation.dimensions, dimension)


def _resolve_dimension(
    *,
    dimension: DimensionName,
    policy: FinalDimensionAggregationConfig,
    deterministic_score: float | None,
    judge_score: float | None,
) -> tuple[float | None, DimensionResolution, list[str]]:
    warnings: list[str] = []
    source_used: Literal["judge", "deterministic", "weighted", "missing"] = "missing"
    final_score: float | None = None

    if policy.policy == "judge_only":
        final_score = judge_score
        source_used = "judge" if judge_score is not None else "missing"
    elif policy.policy == "deterministic_only":
        if deterministic_score is None:
            final_score = judge_score
            source_used = "judge" if judge_score is not None else "missing"
            warnings.append(
                f"Deterministic score missing for '{dimension}'; judge score used as fallback."
            )
        else:
            final_score = deterministic_score
            source_used = "deterministic"
    else:
        if deterministic_score is None:
            final_score = judge_score
            source_used = "judge" if judge_score is not None else "missing"
            warnings.append(
                f"Deterministic score missing for '{dimension}'; judge score used as fallback."
            )
        elif judge_score is None:
            final_score = deterministic_score
            source_used = "deterministic"
            warnings.append(
                f"Judge score missing for '{dimension}'; deterministic score used as fallback."
            )
        else:
            if policy.judge_weight is None or policy.deterministic_weight is None:
                raise ValueError(
                    f"Weighted policy for '{dimension}' requires both judge and deterministic "
                    "weights."
                )
            judge_weight = policy.judge_weight
            deterministic_weight = policy.deterministic_weight
            total_weight = judge_weight + deterministic_weight
            final_score = (
                (judge_score * judge_weight) + (deterministic_score * deterministic_weight)
            ) / total_weight
            source_used = "weighted"

    resolution = DimensionResolution(
        policy=policy.policy,
        source_used=source_used,
        judge_score=judge_score,
        deterministic_score=deterministic_score,
        final_score=final_score,
    )
    return final_score, resolution, warnings


def _compute_final_score(
    *,
    final_dimensions: DimensionScores,
    evaluation_profile: EvaluationProfileConfig,
) -> float:
    weights = evaluation_profile.final_aggregation.final_score_weights
    weighted_sum = 0.0
    total_weight = 0.0

    for dimension in DIMENSION_NAMES:
        score = getattr(final_dimensions, dimension)
        weight = getattr(weights, dimension)
        if score is None or weight <= 0:
            continue
        weighted_sum += score * weight
        total_weight += weight

    if total_weight == 0:
        raise ValueError("Final score cannot be computed because no weighted dimensions exist.")
    return weighted_sum / total_weight


def _deduplicate_preserving_order(entries: Iterable[str]) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry not in seen:
            deduplicated.append(entry)
            seen.add(entry)
    return deduplicated
