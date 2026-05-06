"""Workflow orchestration for `pae run`, `pae eval`, and `pae run-eval`."""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Mapping
from pathlib import Path
from statistics import mean, median
from typing import Any, Protocol
from uuid import uuid4

from personal_agent_eval.aggregation import HybridAggregator
from personal_agent_eval.aggregation.models import DimensionScores, FinalEvaluationResult
from personal_agent_eval.artifacts import RunArtifact
from personal_agent_eval.catalog.discovery import CaseManifest, expand_suite
from personal_agent_eval.config import (
    EvaluationProfileConfig,
    RunProfileConfig,
    SuiteConfig,
    load_evaluation_profile,
    load_openclaw_agent,
    load_run_profile,
    load_suite_config,
)
from personal_agent_eval.config.suite_config import CaseSelection, ModelConfig
from personal_agent_eval.deterministic import DeterministicEvaluator
from personal_agent_eval.deterministic.models import DeterministicEvaluationResult
from personal_agent_eval.domains.llm_probe import OpenRouterClient, run_llm_probe_case
from personal_agent_eval.domains.openclaw import run_openclaw_case
from personal_agent_eval.domains.openclaw.runner import _OPENROUTER_PRICING_USD_PER_MILLION
from personal_agent_eval.domains.openclaw.workspace import materialize_openclaw_workspace
from personal_agent_eval.fingerprints import (
    RunFingerprintInput,
    build_evaluation_fingerprint_input,
    build_openclaw_agent_fingerprint_input,
    build_run_fingerprint_input,
    build_run_profile_fingerprint,
)
from personal_agent_eval.judge import JudgeOrchestrator, OpenRouterJudgeClient
from personal_agent_eval.judge.models import (
    AggregatedJudgeResult,
    JudgeDimensions,
    JudgeEvidence,
    JudgeIterationStatus,
)
from personal_agent_eval.judge.system_prompt import (
    resolve_judge_system_prompt_details,
    resolve_judge_system_prompt_text,
)
from personal_agent_eval.reporting.final_result_summary import render_failed_evaluation_markdown
from personal_agent_eval.storage import (
    EvaluationStorageManifest,
    FilesystemStorage,
    RunStorageManifest,
)
from personal_agent_eval.storage.report_paths import build_openclaw_workflow_evidence_summary
from personal_agent_eval.workflow.models import (
    EvaluationAction,
    RunAction,
    UsageSummary,
    WorkflowCaseResult,
    WorkflowResult,
    WorkflowSummary,
)

logger = logging.getLogger(__name__)


def _storage_fields_for_run_row(
    storage: FilesystemStorage,
    *,
    suite_id: str,
    run_profile_fingerprint: str,
    model_id: str,
    case_id: str,
    repetition_index: int,
    run_artifact: RunArtifact | None,
) -> dict[str, Any]:
    """Workspace-relative storage locations for reporting (OpenClaw + generic run bundle)."""
    if run_artifact is None:
        return {}
    rel = storage.run_case_storage_relative_paths(
        suite_id=suite_id,
        run_profile_fingerprint=run_profile_fingerprint,
        model_id=model_id,
        case_id=case_id,
        repetition_index=repetition_index,
    )
    return {
        "runner_type": run_artifact.identity.runner_type,
        "stored_run_artifact_path": rel["run_artifact"],
        "stored_run_fingerprint_input_path": rel["run_fingerprint_input"],
        "stored_run_artifacts_dir": rel["run_artifacts_dir"],
        "openclaw_evidence": build_openclaw_workflow_evidence_summary(storage.root, run_artifact),
    }


class WorkflowRunClientFactory(Protocol):
    """Factory for runner-facing chat completion clients."""

    def __call__(self) -> Any:
        """Return one client instance."""


class WorkflowJudgeClientFactory(Protocol):
    """Factory for judge-facing clients."""

    def __call__(self) -> Any:
        """Return one client instance."""


class WorkflowOrchestrator:
    """Execute `pae` run/eval workflows over suite models and cases."""

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
        run_profile_fingerprint = build_run_profile_fingerprint(run_profile=run_profile)

        logger.info("Loading stored report for suite '%s'", suite_config.suite_id)
        results: list[WorkflowCaseResult] = []
        evaluation_input = build_evaluation_fingerprint_input(evaluation_profile=evaluation_profile)
        for model in suite_config.models:
            for case_manifest in case_manifests:
                results.append(
                    self._report_model_case(
                        model=model,
                        case_manifest=case_manifest,
                        suite_config=suite_config,
                        run_profile=run_profile,
                        evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                        run_profile_fingerprint=run_profile_fingerprint,
                        evaluation_fingerprint=evaluation_input.fingerprint,
                        workspace_root=workspace_root,
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
        run_profile_fingerprint = build_run_profile_fingerprint(run_profile=run_profile)
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
                    run_profile_fingerprint=run_profile_fingerprint,
                    evaluation_profile=evaluation_profile,
                    case_manifest=case_manifest,
                    model=model,
                    workspace_root=workspace_root,
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
        run_profile_fingerprint: str,
        evaluation_profile: EvaluationProfileConfig | None,
        case_manifest: CaseManifest,
        model: ModelConfig,
        workspace_root: Path,
    ) -> WorkflowCaseResult:
        repetition_indexes = list(_run_repetition_indexes(run_profile))
        case_results = [
            self._process_model_case_repetition(
                command=command,
                suite_config=suite_config,
                run_profile=run_profile,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile=evaluation_profile,
                case_manifest=case_manifest,
                model=model,
                repetition_index=repetition_index,
                repetition_count=len(repetition_indexes),
                workspace_root=workspace_root,
            )
            for repetition_index in repetition_indexes
        ]
        if len(case_results) == 1:
            return case_results[0]
        return _aggregate_case_repetition_results(
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            case_results=case_results,
        )

    def _process_model_case_repetition(
        self,
        *,
        command: str,
        suite_config: SuiteConfig,
        run_profile: RunProfileConfig,
        run_profile_fingerprint: str,
        evaluation_profile: EvaluationProfileConfig | None,
        case_manifest: CaseManifest,
        model: ModelConfig,
        repetition_index: int,
        repetition_count: int,
        workspace_root: Path,
    ) -> WorkflowCaseResult:
        run_input = _build_run_fingerprint_input_for_workflow(
            workspace_root=workspace_root,
            suite_config=suite_config,
            case_manifest=case_manifest,
            run_profile=run_profile,
            model_selection=model,
            repetition_index=(None if repetition_count == 1 else repetition_index),
        )
        run_fingerprint = run_input.fingerprint
        self._ensure_run_space(
            suite_id=suite_config.suite_id,
            run_profile=run_profile,
            run_profile_fingerprint=run_profile_fingerprint,
            model=model,
            runner_type=case_manifest.config.runner.type,
        )

        if self._storage.has_reusable_case_run(
            suite_id=suite_config.suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        ):
            logger.info(
                "Reusing run for model '%s' case '%s' (%s, repetition %d/%d)",
                model.model_id,
                case_manifest.case_id,
                run_fingerprint,
                repetition_index + 1,
                repetition_count,
            )
            run_action = RunAction.REUSED
            run_artifact = self._storage.read_case_run(
                suite_id=suite_config.suite_id,
                run_profile_fingerprint=run_profile_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
            )
        else:
            logger.info(
                "Executing run for model '%s' case '%s' (%s, repetition %d/%d)",
                model.model_id,
                case_manifest.case_id,
                run_fingerprint,
                repetition_index + 1,
                repetition_count,
            )
            run_action = RunAction.EXECUTED
            run_artifact = self._execute_run(
                workspace_root=workspace_root,
                suite_id=suite_config.suite_id,
                suite_config=suite_config,
                case_manifest=case_manifest,
                run_profile=run_profile,
                model=model,
            )
            self._storage.write_case_run(
                suite_id=suite_config.suite_id,
                run_profile_id=run_profile.run_profile_id,
                run_profile_fingerprint=run_profile_fingerprint,
                model_id=model.model_id,
                repetition_index=repetition_index,
                run_fingerprint=run_fingerprint,
                artifact=run_artifact,
                fingerprint_input=run_input,
            )

        if command == "run" or evaluation_profile is None:
            run_u = _usage_from_run_artifact(run_artifact)
            return WorkflowCaseResult(
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                run_fingerprint=run_fingerprint,
                run_action=run_action,
                run_status=run_artifact.status.value,
                evaluation_action=EvaluationAction.SKIPPED,
                run_latency_seconds=_latency_from_run_artifact(run_artifact),
                run_usage=run_u,
                evaluation_usage=UsageSummary(),
                usage=run_u,
                warnings=_run_warnings(run_artifact),
                **_storage_fields_for_run_row(
                    self._storage,
                    suite_id=suite_config.suite_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    model_id=model.model_id,
                    case_id=case_manifest.case_id,
                    repetition_index=repetition_index,
                    run_artifact=run_artifact,
                ),
            )

        evaluation_input = build_evaluation_fingerprint_input(evaluation_profile=evaluation_profile)
        evaluation_fingerprint = evaluation_input.fingerprint
        self._ensure_evaluation_space(
            suite_id=suite_config.suite_id,
            run_profile=run_profile,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile=evaluation_profile,
            evaluation_input=evaluation_input,
        )

        deterministic_result = self._evaluate_deterministic(
            evaluation_profile=evaluation_profile,
            case_manifest=case_manifest,
            run_artifact=run_artifact,
        )
        judge_usage = UsageSummary()

        if self._storage.has_case_final_result(
            suite_id=suite_config.suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile.evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        ):
            logger.info(
                "Reusing final evaluation for model '%s' case '%s' (%s/%s)",
                model.model_id,
                case_manifest.case_id,
                evaluation_fingerprint,
                run_fingerprint,
            )
            final_result = self._storage.read_case_final_result(
                suite_id=suite_config.suite_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
            )
            if self._storage.has_case_judge_result(
                suite_id=suite_config.suite_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
                run_fingerprint=run_fingerprint,
            ):
                judge_result = self._storage.read_case_judge_result(
                    suite_id=suite_config.suite_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                    evaluation_fingerprint=evaluation_fingerprint,
                    model_id=model.model_id,
                    case_id=case_manifest.case_id,
                    repetition_index=repetition_index,
                )
                judge_usage = _usage_from_judge_result(judge_result)
            evaluation_action = EvaluationAction.REUSED
            evaluation_status = "success"
        elif self._storage.has_case_judge_result(
            suite_id=suite_config.suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile.evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        ):
            logger.info(
                "Recomputing final result for model '%s' case '%s' from stored judge result",
                model.model_id,
                case_manifest.case_id,
            )
            judge_result = self._storage.read_case_judge_result(
                suite_id=suite_config.suite_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
            )
            try:
                final_result = self._aggregate_final(
                    case_manifest=case_manifest,
                    evaluation_profile=evaluation_profile,
                    deterministic_result=deterministic_result,
                    judge_result=judge_result,
                )
            except Exception as exc:
                run_u = _usage_from_run_artifact(run_artifact)
                eval_u = _usage_from_judge_result(judge_result)
                warnings = _deduplicate(
                    [
                        *_run_warnings(run_artifact),
                        *judge_result.warnings,
                        (f"Unable to compute final evaluation result: {type(exc).__name__}: {exc}"),
                    ]
                )
                self._storage.write_case_summary_text(
                    suite_id=suite_config.suite_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                    evaluation_fingerprint=evaluation_fingerprint,
                    model_id=model.model_id,
                    case_id=case_manifest.case_id,
                    repetition_index=repetition_index,
                    content=render_failed_evaluation_markdown(
                        case_id=case_manifest.case_id,
                        run_id=run_artifact.identity.run_id,
                        run_status=run_artifact.status.value,
                        evaluation_status="failed",
                        deterministic_result=deterministic_result,
                        judge_result=judge_result,
                        warnings=warnings,
                    ),
                )
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
                    run_latency_seconds=_latency_from_run_artifact(run_artifact),
                    run_usage=run_u,
                    evaluation_usage=eval_u,
                    usage=_combine_usage(run_u, eval_u),
                    warnings=warnings,
                    **_storage_fields_for_run_row(
                        self._storage,
                        suite_id=suite_config.suite_id,
                        run_profile_fingerprint=run_profile_fingerprint,
                        model_id=model.model_id,
                        case_id=case_manifest.case_id,
                        repetition_index=repetition_index,
                        run_artifact=run_artifact,
                    ),
                )
            self._storage.write_case_final_result(
                suite_id=suite_config.suite_id,
                run_profile_id=run_profile.run_profile_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model.model_id,
                repetition_index=repetition_index,
                run_fingerprint=run_fingerprint,
                result=final_result,
                judge_result=judge_result,
            )
            judge_usage = _usage_from_judge_result(judge_result)
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
                suite_id=suite_config.suite_id,
                run_profile_id=run_profile.run_profile_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
                run_fingerprint=run_fingerprint,
                result=judge_result,
            )
            try:
                final_result = self._aggregate_final(
                    case_manifest=case_manifest,
                    evaluation_profile=evaluation_profile,
                    deterministic_result=deterministic_result,
                    judge_result=judge_result,
                )
            except Exception as exc:
                run_u = _usage_from_run_artifact(run_artifact)
                eval_u = _usage_from_judge_result(judge_result)
                warnings = _deduplicate(
                    [
                        *_run_warnings(run_artifact),
                        *judge_result.warnings,
                        (f"Unable to compute final evaluation result: {type(exc).__name__}: {exc}"),
                    ]
                )
                self._storage.write_case_summary_text(
                    suite_id=suite_config.suite_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                    evaluation_fingerprint=evaluation_fingerprint,
                    model_id=model.model_id,
                    case_id=case_manifest.case_id,
                    repetition_index=repetition_index,
                    content=render_failed_evaluation_markdown(
                        case_id=case_manifest.case_id,
                        run_id=run_artifact.identity.run_id,
                        run_status=run_artifact.status.value,
                        evaluation_status="failed",
                        deterministic_result=deterministic_result,
                        judge_result=judge_result,
                        warnings=warnings,
                    ),
                )
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
                    run_latency_seconds=_latency_from_run_artifact(run_artifact),
                    run_usage=run_u,
                    evaluation_usage=eval_u,
                    usage=_combine_usage(run_u, eval_u),
                    warnings=warnings,
                    **_storage_fields_for_run_row(
                        self._storage,
                        suite_id=suite_config.suite_id,
                        run_profile_fingerprint=run_profile_fingerprint,
                        model_id=model.model_id,
                        case_id=case_manifest.case_id,
                        repetition_index=repetition_index,
                        run_artifact=run_artifact,
                    ),
                )
            self._storage.write_case_final_result(
                suite_id=suite_config.suite_id,
                run_profile_id=run_profile.run_profile_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model.model_id,
                repetition_index=repetition_index,
                run_fingerprint=run_fingerprint,
                result=final_result,
                judge_result=judge_result,
            )
            judge_usage = _usage_from_judge_result(judge_result)
            evaluation_action = EvaluationAction.EXECUTED
            evaluation_status = "success"

        run_u = _usage_from_run_artifact(run_artifact)
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
            run_latency_seconds=_latency_from_run_artifact(run_artifact),
            run_usage=run_u,
            evaluation_usage=judge_usage,
            usage=_combine_usage(run_u, judge_usage),
            warnings=_deduplicate([*_run_warnings(run_artifact), *final_result.warnings]),
            **_storage_fields_for_run_row(
                self._storage,
                suite_id=suite_config.suite_id,
                run_profile_fingerprint=run_profile_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
                run_artifact=run_artifact,
            ),
        )

    def _report_model_case(
        self,
        *,
        suite_config: SuiteConfig,
        model: ModelConfig,
        case_manifest: CaseManifest,
        run_profile: RunProfileConfig,
        evaluation_profile_id: str,
        run_profile_fingerprint: str,
        evaluation_fingerprint: str,
        workspace_root: Path,
    ) -> WorkflowCaseResult:
        repetition_indexes = list(_run_repetition_indexes(run_profile))
        case_results = []
        for repetition_index in repetition_indexes:
            run_input = _build_run_fingerprint_input_for_workflow(
                workspace_root=workspace_root,
                suite_config=suite_config,
                case_manifest=case_manifest,
                run_profile=run_profile,
                model_selection=model,
                repetition_index=(None if len(repetition_indexes) == 1 else repetition_index),
            )
            case_results.append(
                self._report_model_case_repetition(
                    suite_id=suite_config.suite_id,
                    model=model,
                    case_manifest=case_manifest,
                    evaluation_profile_id=evaluation_profile_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    run_fingerprint=run_input.fingerprint,
                    evaluation_fingerprint=evaluation_fingerprint,
                    repetition_index=repetition_index,
                )
            )
        if len(case_results) == 1:
            return case_results[0]
        return _aggregate_case_repetition_results(
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            case_results=case_results,
        )

    def _report_model_case_repetition(
        self,
        *,
        suite_id: str,
        model: ModelConfig,
        case_manifest: CaseManifest,
        evaluation_profile_id: str,
        run_profile_fingerprint: str,
        run_fingerprint: str,
        evaluation_fingerprint: str,
        repetition_index: int,
    ) -> WorkflowCaseResult:
        if not self._storage.has_case_run(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        ):
            return WorkflowCaseResult(
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                run_fingerprint=run_fingerprint,
                evaluation_fingerprint=evaluation_fingerprint,
                run_action=RunAction.SKIPPED,
                evaluation_action=EvaluationAction.SKIPPED,
                run_status="missing",
                evaluation_status="missing",
                run_latency_seconds=None,
                run_usage=UsageSummary(),
                evaluation_usage=UsageSummary(),
                usage=UsageSummary(),
                warnings=["Run artifact is missing for this model/case pair."],
            )

        run_artifact = self._storage.read_case_run(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
        )
        if not self._storage.has_case_final_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        ):
            run_u = _usage_from_run_artifact(run_artifact)
            return WorkflowCaseResult(
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                run_fingerprint=run_fingerprint,
                evaluation_fingerprint=evaluation_fingerprint,
                run_action=RunAction.REUSED,
                evaluation_action=EvaluationAction.SKIPPED,
                run_status=run_artifact.status.value,
                evaluation_status="missing",
                run_latency_seconds=_latency_from_run_artifact(run_artifact),
                run_usage=run_u,
                evaluation_usage=UsageSummary(),
                usage=run_u,
                warnings=["Final evaluation result is missing for this model/case pair."],
                **_storage_fields_for_run_row(
                    self._storage,
                    suite_id=suite_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    model_id=model.model_id,
                    case_id=case_manifest.case_id,
                    repetition_index=repetition_index,
                    run_artifact=run_artifact,
                ),
            )

        judge_usage = UsageSummary()
        if self._storage.has_case_judge_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        ):
            judge_result = self._storage.read_case_judge_result(
                suite_id=suite_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
            )
            judge_usage = _usage_from_judge_result(judge_result)

        final_result = self._storage.read_case_final_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model.model_id,
            case_id=case_manifest.case_id,
            repetition_index=repetition_index,
        )
        run_u = _usage_from_run_artifact(run_artifact)
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
            run_latency_seconds=_latency_from_run_artifact(run_artifact),
            run_usage=run_u,
            evaluation_usage=judge_usage,
            usage=_combine_usage(run_u, judge_usage),
            warnings=_deduplicate([*_run_warnings(run_artifact), *final_result.warnings]),
            **_storage_fields_for_run_row(
                self._storage,
                suite_id=suite_id,
                run_profile_fingerprint=run_profile_fingerprint,
                model_id=model.model_id,
                case_id=case_manifest.case_id,
                repetition_index=repetition_index,
                run_artifact=run_artifact,
            ),
        )

    def _ensure_run_space(
        self,
        *,
        suite_id: str,
        run_profile: RunProfileConfig,
        run_profile_fingerprint: str,
        model: ModelConfig,
        runner_type: str,
    ) -> None:
        if not self._storage.has_run_manifest(suite_id, run_profile_fingerprint):
            self._storage.write_run_manifest(
                RunStorageManifest(
                    suite_id=suite_id,
                    run_profile_id=run_profile.run_profile_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    runner_type=runner_type,
                    run_repetitions=run_profile.execution_policy.run_repetitions,
                )
            )

    def _ensure_evaluation_space(
        self,
        *,
        suite_id: str,
        run_profile: RunProfileConfig,
        run_profile_fingerprint: str,
        evaluation_profile: EvaluationProfileConfig,
        evaluation_input: Any,
    ) -> None:
        evaluation_fingerprint = evaluation_input.fingerprint
        judge_system_prompt = resolve_judge_system_prompt_details(evaluation_profile)
        if not self._storage.has_evaluation_manifest(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile.evaluation_profile_id,
            evaluation_fingerprint,
        ):
            self._storage.write_evaluation_manifest(
                EvaluationStorageManifest(
                    suite_id=suite_id,
                    run_profile_id=run_profile.run_profile_id,
                    run_profile_fingerprint=run_profile_fingerprint,
                    evaluation_fingerprint=evaluation_fingerprint,
                    evaluation_profile_id=evaluation_profile.evaluation_profile_id,
                    aggregation_method=evaluation_profile.aggregation.method,
                    judge_system_prompt_source=judge_system_prompt["source"],
                    judge_system_prompt=judge_system_prompt["text"],
                )
            )
        if not self._storage.has_evaluation_fingerprint_input(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile.evaluation_profile_id,
            evaluation_fingerprint,
        ):
            self._storage.write_evaluation_fingerprint_input(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile.evaluation_profile_id,
                evaluation_input,
            )

    def _execute_run(
        self,
        *,
        workspace_root: Path,
        suite_id: str,
        suite_config: SuiteConfig,
        case_manifest: CaseManifest,
        run_profile: RunProfileConfig,
        model: ModelConfig,
    ) -> RunArtifact:
        run_id = f"run_{uuid4().hex}"
        if case_manifest.config.runner.type == "llm_probe":
            client = self._run_client_factory()
            return run_llm_probe_case(
                run_id=run_id,
                suite_id=suite_id,
                case_config=case_manifest.config,
                run_profile=run_profile,
                model_selection=model,
                client=client,
            )
        if case_manifest.config.runner.type == "openclaw":
            if run_profile.openclaw is None:
                raise ValueError("OpenClaw cases require run_profile.openclaw to be configured.")
            agent_id = _resolve_openclaw_agent_id_for_case(
                suite_config=suite_config,
                case_manifest=case_manifest,
                run_profile=run_profile,
            )
            agent_dir = workspace_root / "configs" / "agents" / agent_id
            agent_config = load_openclaw_agent(agent_dir)
            return run_openclaw_case(
                run_id=run_id,
                suite_id=suite_id,
                case_config=case_manifest.config,
                run_profile=run_profile,
                model_selection=model,
                agent_config=agent_config,
            )
        raise NotImplementedError(
            f"Runner '{case_manifest.config.runner.type}' is not supported in the workflow."
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
        judge_system_prompt = resolve_judge_system_prompt_text(evaluation_profile)
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
                    system_prompt=judge_system_prompt,
                    request_options=_resolve_judge_request_options(judge_config),
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


def _resolve_openclaw_agent_id_for_case(
    *,
    suite_config: SuiteConfig,
    case_manifest: CaseManifest,
    run_profile: RunProfileConfig,
) -> str:
    if run_profile.openclaw is None:
        raise ValueError("OpenClaw cases require run_profile.openclaw to be configured.")

    matches = [
        assignment.agent_id
        for assignment in suite_config.openclaw.agent_assignments
        if _openclaw_agent_assignment_matches_case(assignment.case_selection, case_manifest)
    ]
    if len(matches) > 1:
        agents = ", ".join(matches)
        raise ValueError(
            f"OpenClaw case '{case_manifest.case_id}' matches multiple "
            f"suite.openclaw.agent_assignments: {agents}."
        )
    if matches:
        return matches[0]
    return run_profile.openclaw.agent_id


def _openclaw_agent_assignment_matches_case(
    selection: CaseSelection,
    case_manifest: CaseManifest,
) -> bool:
    case_id = case_manifest.case_id
    case_tags = set(case_manifest.config.tags)

    if case_id in selection.exclude_case_ids:
        return False
    if case_tags & set(selection.exclude_tags):
        return False

    return case_id in selection.include_case_ids or bool(case_tags & set(selection.include_tags))


def _build_run_fingerprint_input_for_workflow(
    *,
    workspace_root: Path,
    suite_config: SuiteConfig,
    case_manifest: CaseManifest,
    run_profile: RunProfileConfig,
    model_selection: ModelConfig,
    repetition_index: int | None,
) -> RunFingerprintInput:
    """Match :func:`build_run_fingerprint_input` while resolving OpenClaw agent identity."""
    openclaw_agent_fingerprint: str | None = None
    test_config = case_manifest.config
    if test_config.runner.type == "openclaw":
        if run_profile.openclaw is None:
            raise ValueError("OpenClaw cases require run_profile.openclaw to be configured.")
        agent_id = _resolve_openclaw_agent_id_for_case(
            suite_config=suite_config,
            case_manifest=case_manifest,
            run_profile=run_profile,
        )
        agent_dir = workspace_root / "configs" / "agents" / agent_id
        agent_config = load_openclaw_agent(agent_dir)
        if agent_config.workspace_dir is None:
            raise ValueError("OpenClaw agent config must include a workspace directory.")
        with tempfile.TemporaryDirectory(prefix="pae-openclaw-fp-") as tmp:
            materialized = materialize_openclaw_workspace(
                template_dir=agent_config.workspace_dir,
                workspace_dir=Path(tmp) / "workspace",
            )
            openclaw_agent_fingerprint = build_openclaw_agent_fingerprint_input(
                agent_config=agent_config,
                workspace_manifest=materialized.manifest,
            ).fingerprint
    return build_run_fingerprint_input(
        test_config=test_config,
        run_profile=run_profile,
        model_selection=model_selection,
        repetition_index=repetition_index,
        openclaw_agent_fingerprint=openclaw_agent_fingerprint,
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
    run_cost = sum(result.run_usage.cost_usd for result in results)
    evaluation_cost = sum(result.evaluation_usage.cost_usd for result in results)
    total_cost = sum(result.usage.cost_usd for result in results)
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
        run_cost_usd=run_cost,
        evaluation_cost_usd=evaluation_cost,
        total_cost_usd=total_cost,
    )


def _resolve_judge_model(judge_config: Any) -> str:
    payload = judge_config.model_dump(mode="json")
    for key in ("model", "judge_model", "model_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return judge_config.judge_id


def _resolve_judge_request_options(judge_config: Any) -> dict[str, Any]:
    payload = judge_config.model_dump(mode="json")
    options = payload.get("request_options")
    if isinstance(options, dict):
        return dict(options)
    return {}


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


def _run_repetition_indexes(run_profile: RunProfileConfig) -> range:
    return range(run_profile.execution_policy.run_repetitions)


def _aggregate_case_repetition_results(
    *,
    model_id: str,
    case_id: str,
    case_results: list[WorkflowCaseResult],
) -> WorkflowCaseResult:
    first = case_results[0]
    final_scores = [item.final_score for item in case_results if item.final_score is not None]
    scored_dimensions = [
        item.final_dimensions for item in case_results if item.final_dimensions is not None
    ]
    aggregated_dimensions = None if not scored_dimensions else _mean_dimensions(scored_dimensions)
    warnings = _deduplicate(
        [
            *[warning for item in case_results for warning in item.warnings],
            (
                f"Aggregated {len(case_results)} run repetitions for model '{model_id}' "
                f"case '{case_id}'."
            ),
        ]
    )
    latencies = [
        item.run_latency_seconds for item in case_results if item.run_latency_seconds is not None
    ]
    return WorkflowCaseResult(
        model_id=model_id,
        case_id=case_id,
        run_fingerprint=first.run_fingerprint,
        evaluation_fingerprint=first.evaluation_fingerprint,
        run_action=_aggregate_run_action([item.run_action for item in case_results]),
        evaluation_action=_aggregate_evaluation_action(
            [item.evaluation_action for item in case_results]
        ),
        run_status=_aggregate_status([item.run_status for item in case_results]),
        evaluation_status=_aggregate_optional_status(
            [item.evaluation_status for item in case_results]
        ),
        final_score=(mean(final_scores) if final_scores else None),
        final_dimensions=aggregated_dimensions,
        run_latency_seconds=mean(latencies) if latencies else None,
        run_usage=_sum_usage_summaries([item.run_usage for item in case_results]),
        evaluation_usage=_sum_usage_summaries([item.evaluation_usage for item in case_results]),
        usage=_sum_usage_summaries([item.usage for item in case_results]),
        warnings=warnings,
    )


def _mean_dimensions(items: list[DimensionScores]) -> DimensionScores:
    names = ("task", "process", "autonomy", "closeness", "efficiency", "spark")
    payload: dict[str, float | None] = {}
    for name in names:
        values = [getattr(item, name) for item in items if getattr(item, name) is not None]
        payload[name] = mean(values) if values else None
    return DimensionScores(**payload)


def _aggregate_run_action(actions: list[RunAction]) -> RunAction:
    if any(action is RunAction.EXECUTED for action in actions):
        return RunAction.EXECUTED
    if any(action is RunAction.REUSED for action in actions):
        return RunAction.REUSED
    return RunAction.SKIPPED


def _aggregate_evaluation_action(actions: list[EvaluationAction]) -> EvaluationAction:
    if any(action is EvaluationAction.EXECUTED for action in actions):
        return EvaluationAction.EXECUTED
    if any(action is EvaluationAction.FINAL_RECOMPUTED for action in actions):
        return EvaluationAction.FINAL_RECOMPUTED
    if any(action is EvaluationAction.REUSED for action in actions):
        return EvaluationAction.REUSED
    return EvaluationAction.SKIPPED


def _aggregate_status(statuses: list[str]) -> str:
    return statuses[0] if len(set(statuses)) == 1 else "mixed"


def _aggregate_optional_status(statuses: list[str | None]) -> str | None:
    present_statuses = [status for status in statuses if status is not None]
    if not present_statuses:
        return None
    return present_statuses[0] if len(set(present_statuses)) == 1 else "mixed"


def _latency_from_run_artifact(run_artifact: RunArtifact) -> float | None:
    return run_artifact.timing.duration_seconds


def _usage_from_run_artifact(run_artifact: RunArtifact) -> UsageSummary:
    normalized = run_artifact.usage.normalized
    if run_artifact.usage.cost_usd is None and run_artifact.identity.runner_type == "openclaw":
        fallback = _usage_from_legacy_openclaw_trace(run_artifact)
        if fallback is not None:
            return fallback
    return UsageSummary(
        input_tokens=normalized.input_tokens or 0,
        output_tokens=normalized.output_tokens or 0,
        total_tokens=normalized.total_tokens or 0,
        reasoning_tokens=normalized.reasoning_tokens or 0,
        cached_input_tokens=normalized.cached_input_tokens or 0,
        cache_write_tokens=normalized.cache_write_tokens or 0,
        cost_usd=run_artifact.usage.cost_usd or 0.0,
    )


def _usage_from_legacy_openclaw_trace(run_artifact: RunArtifact) -> UsageSummary | None:
    requested_model = run_artifact.request.requested_model
    pricing = _OPENROUTER_PRICING_USD_PER_MILLION.get(requested_model)
    if pricing is None:
        return None
    usages: list[Mapping[str, Any]] = []
    for event in run_artifact.trace:
        if event.event_type != "final_output" or not hasattr(event, "content"):
            continue
        content = event.content
        if not isinstance(content, str) or '"agentMeta"' not in content:
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        usage = _extract_openclaw_agent_usage(payload)
        if usage is not None:
            usages.append(usage)
    if not usages:
        return None

    input_tokens = sum(_coerce_usage_int(item.get("input")) for item in usages)
    output_tokens = sum(_coerce_usage_int(item.get("output")) for item in usages)
    total_tokens = sum(_coerce_usage_int(item.get("total")) for item in usages)
    cached_input_tokens = sum(_coerce_usage_int(item.get("cacheRead")) for item in usages)
    cache_write_tokens = sum(_coerce_usage_int(item.get("cacheWrite")) for item in usages)
    cost = 0.0
    for item in usages:
        for usage_key in ("input", "output", "cacheRead", "cacheWrite"):
            tokens = _coerce_usage_int(item.get(usage_key))
            price = pricing.get(usage_key)
            if price is not None:
                cost += tokens * price / 1_000_000
    return UsageSummary(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost,
    )


def _extract_openclaw_agent_usage(payload: object) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    raw_meta = payload.get("meta")
    if not isinstance(raw_meta, Mapping):
        return None
    raw_agent_meta = raw_meta.get("agentMeta")
    if not isinstance(raw_agent_meta, Mapping):
        return None
    raw_usage = raw_agent_meta.get("usage")
    if not isinstance(raw_usage, Mapping):
        return None
    return raw_usage


def _usage_from_judge_result(judge_result: AggregatedJudgeResult) -> UsageSummary:
    return _sum_usage_summaries(
        [_usage_from_provider_payload(raw.usage) for raw in judge_result.raw_results]
    )


def _usage_from_provider_payload(payload: dict[str, Any]) -> UsageSummary:
    return UsageSummary(
        input_tokens=_coerce_usage_int(payload.get("input_tokens")),
        output_tokens=_coerce_usage_int(payload.get("output_tokens")),
        total_tokens=_coerce_usage_int(payload.get("total_tokens")),
        reasoning_tokens=_coerce_usage_int(payload.get("reasoning_tokens")),
        cached_input_tokens=_coerce_usage_int(payload.get("cached_input_tokens")),
        cache_write_tokens=_coerce_usage_int(payload.get("cache_write_tokens")),
        cost_usd=_coerce_usage_float(payload.get("cost")),
    )


def _combine_usage(left: UsageSummary, right: UsageSummary) -> UsageSummary:
    return _sum_usage_summaries([left, right])


def _sum_usage_summaries(items: list[UsageSummary]) -> UsageSummary:
    return UsageSummary(
        input_tokens=sum(item.input_tokens for item in items),
        output_tokens=sum(item.output_tokens for item in items),
        total_tokens=sum(item.total_tokens for item in items),
        reasoning_tokens=sum(item.reasoning_tokens for item in items),
        cached_input_tokens=sum(item.cached_input_tokens for item in items),
        cache_write_tokens=sum(item.cache_write_tokens for item in items),
        cost_usd=sum(item.cost_usd for item in items),
    )


def _coerce_usage_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _coerce_usage_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


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
