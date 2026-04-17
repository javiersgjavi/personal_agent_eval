from __future__ import annotations

from pathlib import Path
from typing import cast

from personal_agent_eval.aggregation.models import (
    DimensionResolution,
    DimensionResolutions,
    DimensionScores,
    FinalEvaluationResult,
    HybridAggregationSummary,
)
from personal_agent_eval.artifacts.run_artifact import (
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
)
from personal_agent_eval.fingerprints import (
    EvaluationFingerprintInput,
    EvaluationFingerprintPayload,
    RunFingerprintInput,
    RunFingerprintPayload,
)
from personal_agent_eval.judge.models import (
    AggregatedJudgeResult,
    JudgeDimensions,
    JudgeEvidence,
    JudgeIterationStatus,
    NormalizedJudgeIterationResult,
    RawJudgeRunResult,
)
from personal_agent_eval.storage import (
    EvaluationStorageManifest,
    FilesystemStorage,
    RunStorageManifest,
)


def test_storage_derives_v1_paths() -> None:
    storage = FilesystemStorage("/tmp/personal-agent-eval")

    assert storage.run_manifest_path("run-fp") == Path(
        "/tmp/personal-agent-eval/runs/run-fp/manifest.json"
    )
    assert storage.run_fingerprint_input_path("run-fp") == Path(
        "/tmp/personal-agent-eval/runs/run-fp/fingerprint_input.json"
    )
    assert storage.case_run_path("run-fp", "example_case") == Path(
        "/tmp/personal-agent-eval/runs/run-fp/cases/example_case/run.json"
    )
    assert storage.evaluation_manifest_path("eval-fp") == Path(
        "/tmp/personal-agent-eval/evaluations/eval-fp/manifest.json"
    )
    assert storage.evaluation_fingerprint_input_path("eval-fp") == Path(
        "/tmp/personal-agent-eval/evaluations/eval-fp/fingerprint_input.json"
    )
    assert storage.case_judge_path_for_run("eval-fp", "run-fp", "example_case") == Path(
        "/tmp/personal-agent-eval/evaluations/eval-fp/runs/run-fp/cases/example_case/judge.json"
    )
    assert storage.case_final_result_path_for_run("eval-fp", "run-fp", "example_case") == Path(
        "/tmp/personal-agent-eval/evaluations/eval-fp/runs/run-fp/cases/example_case/final_result.json"
    )


def test_storage_round_trips_run_space_files(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    run_fingerprint = "a" * 64

    manifest = RunStorageManifest(
        run_fingerprint=run_fingerprint,
        runner_type="llm_probe",
        suite_id="example_suite",
        run_profile_id="default",
        model_id="minimax/minimax-m2.7",
    )
    fingerprint_input = RunFingerprintInput(
        fingerprint=run_fingerprint,
        payload=RunFingerprintPayload(
            runner_type="llm_probe",
            requested_model="minimax/minimax-m2.7",
        ),
    )
    run_artifact = RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="run_001",
            case_id="example_case",
            suite_id="example_suite",
            run_profile_id="default",
            runner_type="llm_probe",
        ),
        status=RunStatus.SUCCESS,
        request=RunRequestMetadata(requested_model="minimax/minimax-m2.7"),
    )

    storage.write_run_manifest(manifest)
    storage.write_run_fingerprint_input(fingerprint_input)
    storage.write_case_run(run_fingerprint, run_artifact)

    assert storage.has_run_manifest(run_fingerprint) is True
    assert storage.has_run_fingerprint_input(run_fingerprint) is True
    assert storage.has_case_run(run_fingerprint, "example_case") is True
    assert storage.read_run_manifest(run_fingerprint) == manifest
    assert storage.read_run_fingerprint_input(run_fingerprint) == fingerprint_input
    assert storage.read_case_run(run_fingerprint, "example_case") == run_artifact


def test_storage_round_trips_evaluation_space_files(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    evaluation_fingerprint = "b" * 64
    run_fingerprint = "a" * 64

    manifest = EvaluationStorageManifest(
        evaluation_fingerprint=evaluation_fingerprint,
        evaluation_profile_id="default",
        aggregation_method="median",
        default_dimension_policy="judge_only",
    )
    fingerprint_input = EvaluationFingerprintInput(
        fingerprint=evaluation_fingerprint,
        payload=EvaluationFingerprintPayload(
            judge_aggregation={"method": "median"},
        ),
    )
    judge_result = _build_judge_result()
    final_result = _build_final_result()

    storage.write_evaluation_manifest(manifest)
    storage.write_evaluation_fingerprint_input(fingerprint_input)
    storage.write_case_judge_result(
        evaluation_fingerprint,
        run_fingerprint,
        final_result.case_id,
        judge_result,
    )
    storage.write_case_final_result(evaluation_fingerprint, run_fingerprint, final_result)

    assert storage.has_evaluation_manifest(evaluation_fingerprint) is True
    assert storage.has_evaluation_fingerprint_input(evaluation_fingerprint) is True
    assert (
        storage.has_case_judge_result(
            evaluation_fingerprint,
            run_fingerprint,
            final_result.case_id,
        )
        is True
    )
    assert (
        storage.has_case_final_result(
            evaluation_fingerprint,
            run_fingerprint,
            final_result.case_id,
        )
        is True
    )
    assert storage.read_evaluation_manifest(evaluation_fingerprint) == manifest
    assert (
        storage.read_evaluation_fingerprint_input(evaluation_fingerprint)
        == fingerprint_input
    )
    assert (
        storage.read_case_judge_result(
            evaluation_fingerprint,
            run_fingerprint,
            final_result.case_id,
        )
        == judge_result
    )
    assert (
        storage.read_case_final_result(
            evaluation_fingerprint,
            run_fingerprint,
            final_result.case_id,
        )
        == final_result
    )


def test_storage_rejects_mismatched_fingerprint_input_kind(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    record = EvaluationFingerprintInput(
        fingerprint="c" * 64,
        payload=EvaluationFingerprintPayload(),
    )

    try:
        storage.write_run_fingerprint_input(cast(RunFingerprintInput, record))
    except ValueError as exc:
        assert "RunFingerprintInput" in str(exc)
    else:
        raise AssertionError("Expected write_run_fingerprint_input() to reject mismatched kind.")


def _build_judge_result() -> AggregatedJudgeResult:
    iteration = NormalizedJudgeIterationResult(
        judge_name="primary_judge",
        judge_model="minimax/minimax-m2.7",
        repetition_index=0,
        status=JudgeIterationStatus.SUCCESS,
        dimensions=JudgeDimensions(
            task=8.0,
            process=6.0,
            autonomy=7.5,
            closeness=6.5,
            efficiency=5.0,
            spark=6.0,
        ),
        summary="The result is acceptable.",
        evidence=JudgeEvidence(
            task=["Task evidence"],
            process=["Process evidence"],
            autonomy=["Autonomy evidence"],
            closeness=["Closeness evidence"],
            efficiency=["Efficiency evidence"],
            spark=["Spark evidence"],
        ),
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
        dimensions=iteration.dimensions,
        summary="The result is acceptable.",
        evidence=iteration.evidence,
        iteration_results=[iteration],
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


def _build_final_result() -> FinalEvaluationResult:
    resolution = DimensionResolution(
        policy="judge_only",
        source_used="judge",
        judge_score=8.0,
        final_score=8.0,
    )
    return FinalEvaluationResult(
        case_id="example_case",
        run_id="run_001",
        deterministic_dimensions=DimensionScores(),
        judge_dimensions=DimensionScores(
            task=8.0,
            process=6.0,
            autonomy=7.5,
            closeness=6.5,
            efficiency=5.0,
            spark=6.0,
        ),
        final_dimensions=DimensionScores(
            task=8.0,
            process=6.0,
            autonomy=7.5,
            closeness=6.5,
            efficiency=5.0,
            spark=6.0,
        ),
        dimension_resolutions=DimensionResolutions(
            task=resolution,
            process=resolution,
            autonomy=resolution,
            closeness=resolution,
            efficiency=resolution,
            spark=resolution,
        ),
        final_score=6.5,
        summary=HybridAggregationSummary(
            deterministic_passed_checks=0,
            deterministic_failed_checks=0,
            deterministic_error_checks=0,
            judge_successful_iterations=1,
            judge_failed_iterations=0,
        ),
    )
