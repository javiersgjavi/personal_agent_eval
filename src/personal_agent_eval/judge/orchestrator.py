"""Judge prompt construction, normalization, retries, and aggregation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from statistics import median
from typing import Any, Protocol, cast

from pydantic import ValidationError

from personal_agent_eval.artifacts import RunArtifact
from personal_agent_eval.config.test_config import TestConfig
from personal_agent_eval.judge.models import (
    AggregatedJudgeResult,
    JudgeDimensions,
    JudgeEvidence,
    JudgeIterationStatus,
    JudgeOutputContract,
    NormalizedJudgeIterationResult,
    RawJudgeRunResult,
)
from personal_agent_eval.judge.openrouter import JudgeInvocation


class JudgeClient(Protocol):
    """Client interface for one judge attempt."""

    def run_once(self, invocation: JudgeInvocation) -> RawJudgeRunResult:
        """Execute one provider call."""


class JudgeOrchestrator:
    """Run one judge over N logical repetitions with retry handling."""

    def __init__(self, client: JudgeClient) -> None:
        self._client = client

    def evaluate(
        self,
        *,
        judge_name: str,
        judge_model: str,
        test_config: TestConfig,
        run_artifact: RunArtifact,
        repetitions: int,
        deterministic_summary: Mapping[str, Any] | None = None,
        max_retries: int = 0,
        timeout_seconds: float | None = None,
    ) -> AggregatedJudgeResult:
        """Run the judge repeatedly and aggregate successful iterations."""
        if repetitions < 1:
            raise ValueError("'repetitions' must be greater than or equal to 1.")
        if max_retries < 0:
            raise ValueError("'max_retries' must be greater than or equal to 0.")

        base_messages = build_judge_messages(
            judge_name=judge_name,
            judge_model=judge_model,
            test_config=test_config,
            run_artifact=run_artifact,
            deterministic_summary=deterministic_summary,
        )

        raw_results: list[RawJudgeRunResult] = []
        iteration_results: list[NormalizedJudgeIterationResult] = []

        for repetition_index in range(repetitions):
            result = self._run_repetition(
                judge_name=judge_name,
                judge_model=judge_model,
                repetition_index=repetition_index,
                base_messages=base_messages,
                raw_results=raw_results,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
            )
            iteration_results.append(result)

        return aggregate_judge_results(
            judge_name=judge_name,
            judge_model=judge_model,
            iteration_results=iteration_results,
            raw_results=raw_results,
        )

    def _run_repetition(
        self,
        *,
        judge_name: str,
        judge_model: str,
        repetition_index: int,
        base_messages: tuple[dict[str, str], ...],
        raw_results: list[RawJudgeRunResult],
        max_retries: int,
        timeout_seconds: float | None,
    ) -> NormalizedJudgeIterationResult:
        warnings: list[str] = []
        attempt_statuses: list[JudgeIterationStatus] = []
        last_raw_result_ref: str | None = None

        for attempt_index in range(max_retries + 1):
            invocation = JudgeInvocation(
                judge_name=judge_name,
                judge_model=judge_model,
                repetition_index=repetition_index,
                attempt_index=attempt_index,
                messages=base_messages,
                timeout_seconds=timeout_seconds,
            )
            raw_result = self._client.run_once(invocation)
            raw_results.append(raw_result)
            last_raw_result_ref = raw_result.raw_result_ref
            attempt_statuses.append(raw_result.status)

            if raw_result.status is JudgeIterationStatus.SUCCESS:
                normalized = self._normalize_success(raw_result=raw_result)
                if normalized.status is JudgeIterationStatus.SUCCESS:
                    if attempt_index > 0:
                        warnings.append(
                            f"Iteration succeeded after {attempt_index} retry "
                            f"{'attempt' if attempt_index == 1 else 'attempts'}."
                        )
                    return normalized.model_copy(
                        update={"warnings": [*warnings, *normalized.warnings]}
                    )

                warnings.extend(normalized.warnings)
                if attempt_index < max_retries:
                    warnings.append(
                        "Retrying iteration after invalid judge output."
                    )
                    continue
                return normalized

            warnings.append(
                f"Attempt {attempt_index + 1} ended with status '{raw_result.status.value}'."
            )
            if attempt_index < max_retries:
                warnings.append(
                    f"Retrying repetition {repetition_index} after "
                    f"'{raw_result.status.value}'."
                )
                continue

            return NormalizedJudgeIterationResult(
                judge_name=judge_name,
                judge_model=judge_model,
                repetition_index=repetition_index,
                status=self._final_failure_status(attempt_statuses),
                warnings=[
                    *warnings,
                    (
                        f"Repetition {repetition_index} failed after "
                        f"{max_retries + 1} total attempt"
                        f"{'' if max_retries == 0 else 's'}."
                    ),
                ],
                raw_result_ref=last_raw_result_ref,
            )

        raise AssertionError("Expected repetition loop to return a normalized result.")

    def _normalize_success(
        self,
        *,
        raw_result: RawJudgeRunResult,
    ) -> NormalizedJudgeIterationResult:
        payload: object
        if raw_result.parsed_response is not None:
            payload = raw_result.parsed_response
        elif raw_result.response_content is not None:
            try:
                payload = json.loads(raw_result.response_content)
            except json.JSONDecodeError as exc:
                return NormalizedJudgeIterationResult(
                    judge_name=raw_result.judge_name,
                    judge_model=raw_result.judge_model,
                    repetition_index=raw_result.repetition_index,
                    status=JudgeIterationStatus.INVALID_OUTPUT,
                    warnings=[f"Judge output was not valid JSON: {exc.msg}."],
                    raw_result_ref=raw_result.raw_result_ref,
                )
        else:
            return NormalizedJudgeIterationResult(
                judge_name=raw_result.judge_name,
                judge_model=raw_result.judge_model,
                repetition_index=raw_result.repetition_index,
                status=JudgeIterationStatus.INVALID_OUTPUT,
                warnings=["Judge response did not include any content."],
                raw_result_ref=raw_result.raw_result_ref,
            )

        try:
            parsed = JudgeOutputContract.model_validate(payload)
        except ValidationError as exc:
            first_error = exc.errors()[0]["msg"]
            return NormalizedJudgeIterationResult(
                judge_name=raw_result.judge_name,
                judge_model=raw_result.judge_model,
                repetition_index=raw_result.repetition_index,
                status=JudgeIterationStatus.INVALID_OUTPUT,
                warnings=[f"Judge output did not satisfy the JSON contract: {first_error}"],
                raw_result_ref=raw_result.raw_result_ref,
            )

        warnings = _collect_evidence_warnings(parsed.evidence)
        return NormalizedJudgeIterationResult(
            judge_name=raw_result.judge_name,
            judge_model=raw_result.judge_model,
            repetition_index=raw_result.repetition_index,
            status=JudgeIterationStatus.SUCCESS,
            dimensions=parsed.dimensions,
            summary=parsed.summary,
            evidence=parsed.evidence,
            warnings=warnings,
            raw_result_ref=raw_result.raw_result_ref,
        )

    def _final_failure_status(
        self,
        attempt_statuses: list[JudgeIterationStatus],
    ) -> JudgeIterationStatus:
        unique_statuses = set(attempt_statuses)
        if len(unique_statuses) == 1:
            return attempt_statuses[-1]
        return JudgeIterationStatus.FAILED


def build_judge_messages(
    *,
    judge_name: str,
    judge_model: str,
    test_config: TestConfig,
    run_artifact: RunArtifact,
    deterministic_summary: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], ...]:
    """Build the strict JSON prompt contract for one judge."""
    deterministic_payload = None
    if deterministic_summary is not None:
        deterministic_payload = dict(deterministic_summary)

    case_payload = test_config.model_dump(mode="json")
    case_payload["source_path"] = (
        str(test_config.source_path) if test_config.source_path is not None else None
    )

    user_payload = {
        "judge_name": judge_name,
        "judge_model": judge_model,
        "dimensions": [
            "task",
            "process",
            "autonomy",
            "closeness",
            "efficiency",
            "spark",
        ],
        "case_context": case_payload,
        "run_artifact": run_artifact.to_json_dict(),
        "deterministic_summary": deterministic_payload,
    }

    system_message = {
        "role": "system",
        "content": (
            "You are a strict evaluation judge. Return only valid JSON with the exact top-level "
            "keys `dimensions`, `summary`, and `evidence`. `dimensions` must contain the six "
            "dimension scores `task`, `process`, `autonomy`, `closeness`, `efficiency`, and "
            "`spark`. `evidence` must contain those same six keys with arrays of strings. Do not "
            "wrap the JSON in markdown."
        ),
    }
    user_message = {
        "role": "user",
        "content": json.dumps(user_payload, indent=2, sort_keys=True),
    }
    return (system_message, user_message)


def aggregate_judge_results(
    *,
    judge_name: str,
    judge_model: str,
    iteration_results: list[NormalizedJudgeIterationResult],
    raw_results: list[RawJudgeRunResult],
) -> AggregatedJudgeResult:
    """Aggregate successful judge iterations with median scoring."""
    successful = [
        result
        for result in iteration_results
        if result.status is JudgeIterationStatus.SUCCESS
    ]
    used_repetition_indices = [result.repetition_index for result in successful]
    excluded_repetition_indices = [
        result.repetition_index
        for result in iteration_results
        if result.status is not JudgeIterationStatus.SUCCESS
    ]

    dimensions: JudgeDimensions | None = None
    summary: str | None = None
    evidence: JudgeEvidence | None = None
    warnings: list[str] = []

    if successful:
        dimensions = JudgeDimensions(
            task=_median_dimension(successful, "task"),
            process=_median_dimension(successful, "process"),
            autonomy=_median_dimension(successful, "autonomy"),
            closeness=_median_dimension(successful, "closeness"),
            efficiency=_median_dimension(successful, "efficiency"),
            spark=_median_dimension(successful, "spark"),
        )
        summary = "\n".join(
            f"[repetition {result.repetition_index}] {result.summary}" for result in successful
        )
        evidence = JudgeEvidence(
            task=_merge_evidence(successful, "task"),
            process=_merge_evidence(successful, "process"),
            autonomy=_merge_evidence(successful, "autonomy"),
            closeness=_merge_evidence(successful, "closeness"),
            efficiency=_merge_evidence(successful, "efficiency"),
            spark=_merge_evidence(successful, "spark"),
        )

    if excluded_repetition_indices:
        warnings.append(
            "Excluded non-successful repetitions from aggregation: "
            + ", ".join(str(index) for index in excluded_repetition_indices)
            + "."
        )

    for result in iteration_results:
        for warning in result.warnings:
            warnings.append(f"[repetition {result.repetition_index}] {warning}")

    return AggregatedJudgeResult(
        judge_name=judge_name,
        judge_model=judge_model,
        configured_repetitions=len(iteration_results),
        successful_iterations=len(successful),
        failed_iterations=len(iteration_results) - len(successful),
        used_repetition_indices=used_repetition_indices,
        excluded_repetition_indices=excluded_repetition_indices,
        warnings=warnings,
        dimensions=dimensions,
        summary=summary,
        evidence=evidence,
        iteration_results=iteration_results,
        raw_results=raw_results,
    )


def _median_dimension(
    results: list[NormalizedJudgeIterationResult],
    field_name: str,
) -> float:
    values = [
        getattr(cast(JudgeDimensions, result.dimensions), field_name)
        for result in results
    ]
    return float(median(values))


def _merge_evidence(
    results: list[NormalizedJudgeIterationResult],
    field_name: str,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for result in results:
        entries = getattr(cast(JudgeEvidence, result.evidence), field_name)
        for entry in entries:
            if entry not in seen:
                merged.append(entry)
                seen.add(entry)
    return merged


def _collect_evidence_warnings(evidence: JudgeEvidence) -> list[str]:
    warnings: list[str] = []
    for field_name in ("task", "process", "autonomy", "closeness", "efficiency", "spark"):
        entries = getattr(evidence, field_name)
        non_empty_entries = [entry for entry in entries if entry.strip()]
        if not non_empty_entries:
            warnings.append(
                f"Evidence for dimension '{field_name}' was present but incomplete."
            )
    return warnings
