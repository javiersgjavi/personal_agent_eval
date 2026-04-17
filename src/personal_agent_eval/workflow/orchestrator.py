"""Workflow orchestration for `pae run`, `pae eval`, and `pae run-eval`."""

from __future__ import annotations

import logging
from pathlib import Path
from statistics import median
from typing import Any, Protocol
from uuid import uuid4

from personal_agent_eval.aggregation import HybridAggregator
from personal_agent_eval.aggregation.models import FinalEvaluationResult
from personal_agent_eval.artifacts import RunArtifact
from personal_agent_eval.catalog.discovery import CaseManifest, expand_suite
from personal_agent_eval.config import (
    EvaluationProfileConfig,
    RunProfileConfig,
    SuiteConfig,
    load_evaluation_profile,
    load_run_profile,
    load_suite_config,
)
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.deterministic import DeterministicEvaluator
from personal_agent_eval.deterministic.models import DeterministicEvaluationResult
from personal_agent_eval.domains.llm_probe import OpenRouterClient, run_llm_probe_case
from personal_agent_eval.fingerprints import (
    build_evaluation_fingerprint_input,
    build_run_fingerprint_input,
)
from personal_agent_eval.judge import JudgeOrchestrator, OpenRouterJudgeClient
from personal_agent_eval.judge.models import (
    AggregatedJudgeResult,
    JudgeDimensions,
    JudgeEvidence,
    JudgeIterationStatus,
)
from personal_agent_eval.storage import (
    EvaluationStorageManifest,
    FilesystemStorage,
    RunStorageManifest,
)
from personal_agent_eval.workflow.models import (
    EvaluationAction,
    RunAction,
    WorkflowCaseResult,
    WorkflowResult,
    WorkflowSummary,
)

logger = logging.getLogger(__name__)


class WorkflowRunClientFactory(Protocol):
    """Factory for runner-facing chat completion clients."""

    def __call__(self) -> Any:
        """Return one client instance."""


class WorkflowJudgeClientFactory(Protocol):
    """Factory for judge-facing clients."""

    def __call__(self) -> Any:
        """Return one client instance."""


class WorkflowOrchestrator:
    """Execute the V1 run/eval workflow over suite models and cases."""

    def __init__(
        self,
        *,
        storage_root: str | Path,
        run_client_factory: WorkflowRunClientFactory | None = None,
        judge_client_factory: WorkflowJudgeClientFactory | None = None,
    ) -> None:
        self._storage = FilesystemStorage(storage_root)
        self._run_client_factory = run_client_factory or OpenRouterClient
        self._judge_client_factory = judge_client_factory or OpenRouterJudgeClient

    def run(
        self,
        *,
        suite_path: str | Path,
        run_profile_path: str | Path,
    ) -> WorkflowResult:
        """Execute only missing runs for the selected suite."""
        return self._execute(
            command="run",
            suite_path=suite_path,
            run_profile_path=run_profile_path,
            evaluation_profile_path=None,
        )

    def evaluate(
        self,
        *,
        suite_path: str | Path,
        run_profile_path: str | Path,
        evaluation_profile_path: str | Path,
    ) -> WorkflowResult:
        """Execute missing runs and missing evaluation artifacts."""
        return self._execute(
            command="eval",
            suite_path=suite_path,
            run_profile_path=run_profile_path,
            evaluation_profile_path=evaluation_profile_path,
        )

    def run_eval(
        self,
        *,
        suite_path: str | Path,
        run_profile_path: str | Path,
        evaluation_profile_path: str | Path,
    ) -> WorkflowResult:
        """Execute the full run and evaluation workflow."""
        return self._execute(
            command="run-eval",
            suite_path=suite_path,
            run_profile_path=run_profile_path,
            evaluation_profile_path=evaluation_profile_path,
        )

    def report(
        self,
        *,
        suite_path: str | Path,
        run_profile_path: str | Path,
        evaluation_profile_path: str | Path,
    ) -> WorkflowResult:
        """Build a workflow-shaped report view from previously stored artifacts only."""
        suite_config = load_suite_config(suite_path)
        run_profile = load_run_profile(run_profile_path)
        evaluation_profile = load_evaluation_profile(evaluation_profile_path)
        workspace_root = _workspace_root_from_suite_path(suite_config.source_path)
        case_manifests = expand_suite(workspace_root, suite_config.suite_id)

        logger.info("Loading stored report for suite '%s'", suite_config.suite_id)
        results: list[WorkflowCaseResult] = []
        for model in suite_config.models:
            for case_manifest in case_manifests:
                run_input = build_run_fingerprint_input(
                    test_config=case_manifest.config,
                    run_profile=run_profile,
                    model_selection=model,
                )
                evaluation_input = build_evaluation_fingerprint_input(
                    evaluation_profile=evaluation_profile
                )
                results.append(
                    self._report_model_case(
                        model=model,
                        case_manifest=case_manifest,
                        run_fingerprint=run_input.fingerprint,
                        evaluation_fingerprint=evaluation_input.fingerprint,
                    )
                )

        return WorkflowResult(
            command="report",
            workspace_root=str(workspace_root),
            suite_id=suite_config.suite_id,
            run_profile_id=run_profile.run_profile_id,
            evaluation_profile_id=evaluation_profile.evaluation_profile_id,
            results=results,
            summary=_build_summary(
                models_requested=len(suite_config.models),
                cases_requested=len(case_manifests),
                results=results,
            ),
        )

    def _execute(
        self,
        *,
        command: str,
        suite_path: str | Path,
        run_profile_path: str | Path,
        evaluation_profile_path: str | Path | None,
    ) -> WorkflowResult:
        suite_config = load_suite_config(suite_path)
        run_profile = load_run_profile(run_profile_path)
        evaluation_profile = (
            load_evaluation_profile(evaluation_profile_path)
            if evaluation_profile_path is not None
            else None
        )
        workspace_root = _workspace_root_from_suite_path(suite_config.source_path)
        case_manifests = expand_suite(workspace_root, suite_config.suite_id)

        logger.info("Loading suite '%s' from %s", suite_config.suite_id, suite_config.source_path)
        logger.info("Expanded suite '%s' to %d cases", suite_config.suite_id, len(case_manifests))

        results: list[WorkflowCaseResult] = []

        for model in suite_config.models:
            logger.info("Starting workflow for model '%s'", model.model_id)
            for case_manifest in case_manifests:
                result = self._process_model_case(
                    command=command,
                    suite_config=suite_config,
                    run_profile=run_profile,
                    evaluation_profile=evaluation_profile,
                    case_manifest=case_manifest,
                    model=model,
                )
                results.append(result)

        summary = _build_summary(
            models_requested=len(suite_config.models),
            cases_requested=len(case_manifests),
            results=results,
        )
        return WorkflowResult(
            command=command,
            workspace_root=str(workspace_root),
            suite_id=suite_config.suite_id,
            run_profile_id=run_profile.run_profile_id,
            evaluation_profile_id=(
                None if evaluation_profile is None else evaluation_profile.evaluation_profile_id
            ),
            results=results,
            summary=summary,
        )

    def _process_model_case(
        self,
        *,
        command: str,
        suite_config: SuiteConfig,
        run_profile: RunProfileConfig,
        evaluation_profile: EvaluationProfileConfig | None,
        case_manifest: CaseManifest,
        model: ModelConfig,
    ) -> WorkflowCaseResult:
        run_input = build_run_fingerprint_input(
            test_config=case_manifest.config,
            run_profile=run_profile,
            model_selection=model,
        )
        run_fingerprint = run_input.fingerprint
        self._ensure_run_space(
            run_fingerprint=run_fingerprint,
            suite_id=suite_config.suite_id,
            run_profile=run_profile,
            model=model,
            runner_type=case_manifest.config.runner.type,
            run_input=run_input,
        )

        if self._storage.has_case_run(run_fingerprint, case_manifest.case_id):
            logger.info(
                "Reusing run for model '%s' case '%s' (%s)",
                model.model_id,
                case_manifest.case_id,
                run_fingerprint,
            )
            run_action = RunAction.REUSED
            run_artifact = self._storage.read_case_run(run_fingerprint, case_manifest.case_id)
        else:
            logger.info(
                "Executing run for model '%s' case '%s' (%s)",
                model.model_id,
                case_manifest.case_id,
                run_fingerprint,
            )
            run_action = RunAction.EXECUTED
            run_artifact = self._execute_run(
                suite_id=suite_config.suite_id,
                case_manifest=case_manifest,
                run_profile=run_profile,
                model=model,
            )
            self._storage.write_case_run(run_fingerprint, run_artifact)

        if command == "run" or evaluation_profile is None:
            return WorkflowCaseResult(
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                run_fingerprint=run_fingerprint,
                run_action=run_action,
                run_status=run_artifact.status.value,
                evaluation_action=EvaluationAction.SKIPPED,
                warnings=_run_warnings(run_artifact),
            )

        evaluation_input = build_evaluation_fingerprint_input(evaluation_profile=evaluation_profile)
        evaluation_fingerprint = evaluation_input.fingerprint
        self._ensure_evaluation_space(
            evaluation_fingerprint=evaluation_fingerprint,
            evaluation_profile=evaluation_profile,
            evaluation_input=evaluation_input,
        )

        deterministic_result = self._evaluate_deterministic(
            evaluation_profile=evaluation_profile,
            case_manifest=case_manifest,
            run_artifact=run_artifact,
        )

        if self._storage.has_case_final_result(
            evaluation_fingerprint,
            run_fingerprint,
            case_manifest.case_id,
        ):
            logger.info(
                "Reusing final evaluation for model '%s' case '%s' (%s/%s)",
                model.model_id,
                case_manifest.case_id,
                evaluation_fingerprint,
                run_fingerprint,
            )
            final_result = self._storage.read_case_final_result(
                evaluation_fingerprint,
                run_fingerprint,
                case_manifest.case_id,
            )
            evaluation_action = EvaluationAction.REUSED
            evaluation_status = "success"
        elif self._storage.has_case_judge_result(
            evaluation_fingerprint,
            run_fingerprint,
            case_manifest.case_id,
        ):
            logger.info(
                "Recomputing final result for model '%s' case '%s' from stored judge result",
                model.model_id,
                case_manifest.case_id,
            )
            judge_result = self._storage.read_case_judge_result(
                evaluation_fingerprint,
                run_fingerprint,
                case_manifest.case_id,
            )
            try:
                final_result = self._aggregate_final(
                    case_manifest=case_manifest,
                    evaluation_profile=evaluation_profile,
                    deterministic_result=deterministic_result,
                    judge_result=judge_result,
                )
            except Exception as exc:
                return WorkflowCaseResult(
                    model_id=model.model_id,
                    case_id=case_manifest.case_id,
                    run_fingerprint=run_fingerprint,
                    evaluation_fingerprint=evaluation_fingerprint,
                    run_action=run_action,
                    evaluation_action=EvaluationAction.FINAL_RECOMPUTED,
                    run_status=run_artifact.status.value,
                    evaluation_status="failed",
                    final_score=None,
                    final_dimensions=None,
                    warnings=_deduplicate(
                        [
                            *_run_warnings(run_artifact),
                            (
                                "Unable to recompute final evaluation result: "
                                f"{type(exc).__name__}: {exc}"
                            ),
                        ]
                    ),
                )
            self._storage.write_case_final_result(
                evaluation_fingerprint,
                run_fingerprint,
                final_result,
            )
            evaluation_action = EvaluationAction.FINAL_RECOMPUTED
            evaluation_status = "success"
        else:
            logger.info(
                "Executing judge pipeline for model '%s' case '%s' (%s/%s)",
                model.model_id,
                case_manifest.case_id,
                evaluation_fingerprint,
                run_fingerprint,
            )
            judge_result = self._evaluate_judges(
                evaluation_profile=evaluation_profile,
                case_manifest=case_manifest,
                run_artifact=run_artifact,
                deterministic_result=deterministic_result,
            )
            self._storage.write_case_judge_result(
                evaluation_fingerprint,
                run_fingerprint,
                case_manifest.case_id,
                judge_result,
            )
            try:
                final_result = self._aggregate_final(
                    case_manifest=case_manifest,
                    evaluation_profile=evaluation_profile,
                    deterministic_result=deterministic_result,
                    judge_result=judge_result,
                )
            except Exception as exc:
                return WorkflowCaseResult(
                    model_id=model.model_id,
                    case_id=case_manifest.case_id,
                    run_fingerprint=run_fingerprint,
                    evaluation_fingerprint=evaluation_fingerprint,
                    run_action=run_action,
                    evaluation_action=EvaluationAction.EXECUTED,
                    run_status=run_artifact.status.value,
                    evaluation_status="failed",
                    final_score=None,
                    final_dimensions=None,
                    warnings=_deduplicate(
                        [
                            *_run_warnings(run_artifact),
                            *judge_result.warnings,
                            (
                                "Unable to compute final evaluation result: "
                                f"{type(exc).__name__}: {exc}"
                            ),
                        ]
                    ),
                )
            self._storage.write_case_final_result(
                evaluation_fingerprint,
                run_fingerprint,
                final_result,
            )
            evaluation_action = EvaluationAction.EXECUTED
            evaluation_status = "success"

        return WorkflowCaseResult(
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            run_fingerprint=run_fingerprint,
            evaluation_fingerprint=evaluation_fingerprint,
            run_action=run_action,
            evaluation_action=evaluation_action,
            run_status=run_artifact.status.value,
            evaluation_status=evaluation_status,
            final_score=final_result.final_score,
            final_dimensions=final_result.final_dimensions,
            warnings=_deduplicate([*_run_warnings(run_artifact), *final_result.warnings]),
        )

    def _report_model_case(
        self,
        *,
        model: ModelConfig,
        case_manifest: CaseManifest,
        run_fingerprint: str,
        evaluation_fingerprint: str,
    ) -> WorkflowCaseResult:
        if not self._storage.has_case_run(run_fingerprint, case_manifest.case_id):
            return WorkflowCaseResult(
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                run_fingerprint=run_fingerprint,
                evaluation_fingerprint=evaluation_fingerprint,
                run_action=RunAction.SKIPPED,
                evaluation_action=EvaluationAction.SKIPPED,
                run_status="missing",
                evaluation_status="missing",
                warnings=["Run artifact is missing for this model/case pair."],
            )

        run_artifact = self._storage.read_case_run(run_fingerprint, case_manifest.case_id)
        if not self._storage.has_case_final_result(
            evaluation_fingerprint,
            run_fingerprint,
            case_manifest.case_id,
        ):
            return WorkflowCaseResult(
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                run_fingerprint=run_fingerprint,
                evaluation_fingerprint=evaluation_fingerprint,
                run_action=RunAction.REUSED,
                evaluation_action=EvaluationAction.SKIPPED,
                run_status=run_artifact.status.value,
                evaluation_status="missing",
                warnings=["Final evaluation result is missing for this model/case pair."],
            )

        final_result = self._storage.read_case_final_result(
            evaluation_fingerprint,
            run_fingerprint,
            case_manifest.case_id,
        )
        return WorkflowCaseResult(
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            run_fingerprint=run_fingerprint,
            evaluation_fingerprint=evaluation_fingerprint,
            run_action=RunAction.REUSED,
            evaluation_action=EvaluationAction.REUSED,
            run_status=run_artifact.status.value,
            evaluation_status="success",
            final_score=final_result.final_score,
            final_dimensions=final_result.final_dimensions,
            warnings=_deduplicate([*_run_warnings(run_artifact), *final_result.warnings]),
        )

    def _ensure_run_space(
        self,
        *,
        run_fingerprint: str,
        suite_id: str,
        run_profile: RunProfileConfig,
        model: ModelConfig,
        runner_type: str,
        run_input: Any,
    ) -> None:
        if not self._storage.has_run_manifest(run_fingerprint):
            self._storage.write_run_manifest(
                RunStorageManifest(
                    run_fingerprint=run_fingerprint,
                    runner_type=runner_type,
                    suite_id=suite_id,
                    run_profile_id=run_profile.run_profile_id,
                    model_id=model.model_id,
                )
            )
        if not self._storage.has_run_fingerprint_input(run_fingerprint):
            self._storage.write_run_fingerprint_input(run_input)

    def _ensure_evaluation_space(
        self,
        *,
        evaluation_fingerprint: str,
        evaluation_profile: EvaluationProfileConfig,
        evaluation_input: Any,
    ) -> None:
        if not self._storage.has_evaluation_manifest(evaluation_fingerprint):
            self._storage.write_evaluation_manifest(
                EvaluationStorageManifest(
                    evaluation_fingerprint=evaluation_fingerprint,
                    evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                    aggregation_method=evaluation_profile.aggregation.method,
                    default_dimension_policy=evaluation_profile.final_aggregation.default_policy,
                )
            )
        if not self._storage.has_evaluation_fingerprint_input(evaluation_fingerprint):
            self._storage.write_evaluation_fingerprint_input(evaluation_input)

    def _execute_run(
        self,
        *,
        suite_id: str,
        case_manifest: CaseManifest,
        run_profile: RunProfileConfig,
        model: ModelConfig,
    ) -> RunArtifact:
        if case_manifest.config.runner.type != "llm_probe":
            raise NotImplementedError(
                f"Runner '{case_manifest.config.runner.type}' is not supported in V1 workflow."
            )
        client = self._run_client_factory()
        return run_llm_probe_case(
            run_id=f"run_{uuid4().hex}",
            suite_id=suite_id,
            case_config=case_manifest.config,
            run_profile=run_profile,
            model_selection=model,
            client=client,
        )

    def _evaluate_deterministic(
        self,
        *,
        evaluation_profile: EvaluationProfileConfig,
        case_manifest: CaseManifest,
        run_artifact: RunArtifact,
    ) -> DeterministicEvaluationResult:
        evaluator = DeterministicEvaluator(
            allow_local_python_hooks=evaluation_profile.security_policy.allow_local_python_hooks
        )
        return evaluator.evaluate_test_config(case_manifest.config, run_artifact)

    def _evaluate_judges(
        self,
        *,
        evaluation_profile: EvaluationProfileConfig,
        case_manifest: CaseManifest,
        run_artifact: RunArtifact,
        deterministic_result: DeterministicEvaluationResult,
    ) -> AggregatedJudgeResult:
        judge_lookup = {judge.judge_id: judge for judge in evaluation_profile.judges}
        judge_client = self._judge_client_factory()
        orchestrator = JudgeOrchestrator(judge_client)
        individual_results: list[AggregatedJudgeResult] = []

        for judge_run in evaluation_profile.judge_runs:
            judge_config = judge_lookup.get(judge_run.judge_id)
            if judge_config is None:
                raise ValueError(f"Judge run references unknown judge_id '{judge_run.judge_id}'.")

            judge_name = judge_run.judge_run_id
            judge_model = _resolve_judge_model(judge_config)
            logger.info(
                "Running judge '%s' with model '%s' for case '%s'",
                judge_name,
                judge_model,
                case_manifest.case_id,
            )
            individual_results.append(
                orchestrator.evaluate(
                    judge_name=judge_name,
                    judge_model=judge_model,
                    test_config=case_manifest.config,
                    run_artifact=run_artifact,
                    repetitions=judge_run.repetitions,
                    deterministic_summary=deterministic_result.summary.model_dump(mode="json"),
                    max_retries=5,
                )
            )

        if not individual_results:
            raise ValueError("Evaluation profile must define at least one judge_run.")
        if len(individual_results) == 1:
            return individual_results[0]
        return _combine_aggregated_judges(individual_results)

    def _aggregate_final(
        self,
        *,
        case_manifest: CaseManifest,
        evaluation_profile: EvaluationProfileConfig,
        deterministic_result: DeterministicEvaluationResult,
        judge_result: AggregatedJudgeResult,
    ) -> FinalEvaluationResult:
        aggregator = HybridAggregator()
        return aggregator.aggregate(
            test_config=case_manifest.config,
            evaluation_profile=evaluation_profile,
            deterministic_result=deterministic_result,
            judge_result=judge_result,
        )


def _workspace_root_from_suite_path(suite_path: Path | None) -> Path:
    if suite_path is None:
        return Path.cwd().resolve()
    resolved_suite = suite_path.expanduser().resolve()
    if resolved_suite.parent.parent.name == "configs":
        return resolved_suite.parent.parent.parent
    return resolved_suite.parent.parent


def _build_summary(
    *,
    models_requested: int,
    cases_requested: int,
    results: list[WorkflowCaseResult],
) -> WorkflowSummary:
    return WorkflowSummary(
        models_requested=models_requested,
        cases_requested=cases_requested,
        model_case_pairs=len(results),
        runs_executed=sum(result.run_action is RunAction.EXECUTED for result in results),
        runs_reused=sum(result.run_action is RunAction.REUSED for result in results),
        evaluations_executed=sum(
            result.evaluation_action is EvaluationAction.EXECUTED for result in results
        ),
        evaluations_reused=sum(
            result.evaluation_action is EvaluationAction.REUSED for result in results
        ),
        final_results_recomputed=sum(
            result.evaluation_action is EvaluationAction.FINAL_RECOMPUTED for result in results
        ),
    )


def _resolve_judge_model(judge_config: Any) -> str:
    payload = judge_config.model_dump(mode="json")
    for key in ("model", "judge_model", "model_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return judge_config.judge_id


def _combine_aggregated_judges(judge_results: list[AggregatedJudgeResult]) -> AggregatedJudgeResult:
    flattened_iterations = []
    flattened_raw_results = []
    warnings: list[str] = []
    judge_summaries: list[str] = []
    dimension_sources = []
    evidence = {
        name: [] for name in ("task", "process", "autonomy", "closeness", "efficiency", "spark")
    }

    repetition_offset = 0
    for result in judge_results:
        index_map: dict[int, int] = {}
        for iteration in result.iteration_results:
            new_index = repetition_offset
            repetition_offset += 1
            index_map[iteration.repetition_index] = new_index
            flattened_iterations.append(
                iteration.model_copy(update={"repetition_index": new_index})
            )
        for raw in result.raw_results:
            flattened_raw_results.append(
                raw.model_copy(
                    update={
                        "repetition_index": index_map.get(
                            raw.repetition_index,
                            raw.repetition_index,
                        )
                    }
                )
            )
        warnings.extend(result.warnings)
        if result.summary:
            judge_summaries.append(f"[{result.judge_name}] {result.summary}")
        if result.dimensions is not None:
            dimension_sources.append(result.dimensions)
        if result.evidence is not None:
            for field_name in evidence:
                evidence[field_name].extend(getattr(result.evidence, field_name))

    successful_indices = [
        iteration.repetition_index
        for iteration in flattened_iterations
        if iteration.status is JudgeIterationStatus.SUCCESS
    ]
    failed_indices = [
        iteration.repetition_index
        for iteration in flattened_iterations
        if iteration.status is not JudgeIterationStatus.SUCCESS
    ]

    dimensions = None
    merged_evidence = None
    if dimension_sources:
        dimensions = JudgeDimensions(
            task=median(source.task for source in dimension_sources),
            process=median(source.process for source in dimension_sources),
            autonomy=median(source.autonomy for source in dimension_sources),
            closeness=median(source.closeness for source in dimension_sources),
            efficiency=median(source.efficiency for source in dimension_sources),
            spark=median(source.spark for source in dimension_sources),
        )
        merged_evidence = JudgeEvidence(**evidence)

    return AggregatedJudgeResult(
        judge_name="composite_judge",
        judge_model="multiple",
        configured_repetitions=len(flattened_iterations),
        successful_iterations=len(successful_indices),
        failed_iterations=len(failed_indices),
        used_repetition_indices=successful_indices,
        excluded_repetition_indices=failed_indices,
        warnings=_deduplicate(warnings),
        dimensions=dimensions,
        summary="\n".join(judge_summaries) if judge_summaries else None,
        evidence=merged_evidence,
        iteration_results=flattened_iterations,
        raw_results=flattened_raw_results,
    )


def _run_warnings(run_artifact: RunArtifact) -> list[str]:
    warnings = []
    if run_artifact.error is not None:
        warnings.append(run_artifact.error.message)
    return warnings


def _deduplicate(entries: list[str]) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry not in seen:
            deduplicated.append(entry)
            seen.add(entry)
    return deduplicated
