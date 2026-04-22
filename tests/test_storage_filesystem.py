from __future__ import annotations

from pathlib import Path
from typing import cast

from personal_agent_eval.aggregation.models import (
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
    suite_id = "example_suite"
    run_profile_fingerprint = "a" * 64
    evaluation_profile_id = "judge_default"
    evaluation_fingerprint = "b" * 64
    model_name = "example/model"

    assert storage.run_manifest_path(suite_id, run_profile_fingerprint) == Path(
        "/tmp/personal-agent-eval/outputs/runs/suit_example_suite/run_profile_aaaaaa/manifest.json"
    )
    assert storage.case_run_path(
        suite_id,
        run_profile_fingerprint,
        model_name,
        "example_case",
        0,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/runs/suit_example_suite/run_profile_aaaaaa/example_model/example_case/run_1.json"
    )
    assert storage.case_run_fingerprint_input_path(
        suite_id,
        run_profile_fingerprint,
        model_name,
        "example_case",
        1,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/runs/suit_example_suite/run_profile_aaaaaa/example_model/example_case/run_2.fingerprint_input.json"
    )
    assert storage.evaluation_manifest_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/evaluations/suit_example_suite/evaluation_profile_aaaaaa/eval_profile_judge_default_bbbbbb/manifest.json"
    )
    assert storage.evaluation_fingerprint_input_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/evaluations/suit_example_suite/evaluation_profile_aaaaaa/eval_profile_judge_default_bbbbbb/fingerprint_input.json"
    )
    assert storage.case_judge_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        model_name,
        "example_case",
        0,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/evaluations/suit_example_suite/evaluation_profile_aaaaaa/eval_profile_judge_default_bbbbbb/example_model/example_case/raw_outputs/judge_1.json"
    )
    assert storage.case_final_result_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        model_name,
        "example_case",
        1,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/evaluations/suit_example_suite/evaluation_profile_aaaaaa/eval_profile_judge_default_bbbbbb/example_model/example_case/raw_outputs/final_result_2.json"
    )
    assert storage.case_judge_prompt_user_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        model_name,
        "example_case",
        0,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/evaluations/suit_example_suite/evaluation_profile_aaaaaa/eval_profile_judge_default_bbbbbb/example_model/example_case/raw_outputs/judge_1.prompt.user.json"
    )
    assert storage.case_judge_prompt_debug_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        model_name,
        "example_case",
        0,
    ) == Path(
        "/tmp/personal-agent-eval/outputs/evaluations/suit_example_suite/evaluation_profile_aaaaaa/eval_profile_judge_default_bbbbbb/example_model/example_case/judge_1.prompt.debug.md"
    )


def test_storage_round_trips_run_space_files(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    suite_id = "example_suite"
    run_profile_id = "default"
    run_profile_fingerprint = "d" * 64
    run_fingerprint = "a" * 64
    model_name = "minimax/minimax-m2.7"

    manifest = RunStorageManifest(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        runner_type="llm_probe",
        run_repetitions=2,
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
            suite_id=suite_id,
            run_profile_id=run_profile_id,
            runner_type="llm_probe",
        ),
        status=RunStatus.SUCCESS,
        request=RunRequestMetadata(requested_model="minimax/minimax-m2.7"),
    )

    storage.write_run_manifest(manifest)
    storage.write_case_run(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        model_id=model_name,
        repetition_index=0,
        run_fingerprint=run_fingerprint,
        artifact=run_artifact,
        fingerprint_input=fingerprint_input,
    )

    assert storage.has_run_manifest(suite_id, run_profile_fingerprint) is True
    assert (
        storage.has_case_run(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            model_id=model_name,
            case_id="example_case",
            repetition_index=0,
            run_fingerprint=run_fingerprint,
        )
        is True
    )
    assert storage.read_run_manifest(suite_id, run_profile_fingerprint) == manifest
    assert (
        storage.read_case_run(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            model_id=model_name,
            case_id="example_case",
            repetition_index=0,
        )
        == run_artifact
    )


def test_storage_round_trips_evaluation_space_files(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    suite_id = "example_suite"
    run_profile_id = "default"
    run_profile_fingerprint = "d" * 64
    evaluation_profile_id = "judge_default"
    evaluation_fingerprint = "b" * 64
    run_fingerprint = "a" * 64
    model_name = "minimax/minimax-m2.7"

    manifest = EvaluationStorageManifest(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_fingerprint=evaluation_fingerprint,
        evaluation_profile_id=evaluation_profile_id,
        aggregation_method="median",
        judge_system_prompt_source="path:prompts/judge_system_default.md",
        judge_system_prompt="You are a strict evaluation judge.",
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
    storage.write_evaluation_fingerprint_input(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        fingerprint_input,
    )
    storage.write_case_judge_result(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id=evaluation_profile_id,
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=model_name,
        case_id=final_result.case_id,
        repetition_index=0,
        run_fingerprint=run_fingerprint,
        result=judge_result,
    )
    storage.write_case_final_result(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id=evaluation_profile_id,
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=model_name,
        repetition_index=0,
        run_fingerprint=run_fingerprint,
        result=final_result,
        judge_result=judge_result,
    )

    assert (
        storage.has_evaluation_manifest(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
        )
        is True
    )
    assert (
        storage.has_evaluation_fingerprint_input(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
        )
        is True
    )
    assert (
        storage.has_case_judge_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model_name,
            case_id=final_result.case_id,
            repetition_index=0,
            run_fingerprint=run_fingerprint,
        )
        is True
    )
    assert (
        storage.has_case_final_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model_name,
            case_id=final_result.case_id,
            repetition_index=0,
            run_fingerprint=run_fingerprint,
        )
        is True
    )
    assert (
        storage.read_evaluation_manifest(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
        )
        == manifest
    )
    assert (
        storage.read_case_judge_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model_name,
            case_id=final_result.case_id,
            repetition_index=0,
        )
        == judge_result
    )
    assert (
        storage.case_judge_prompt_user_path(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
            model_name,
            "example_case",
            0,
        )
        .read_text(encoding="utf-8")
        .startswith('{\n  "evaluation_target":')
    )
    assert (
        storage.case_judge_prompt_debug_path(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
            model_name,
            "example_case",
            0,
        )
        .read_text(encoding="utf-8")
        .startswith("SYSTEM PROMPT:\n")
    )
    summary_text = storage.case_evaluation_result_summary_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        model_name,
        "example_case",
        0,
    ).read_text(encoding="utf-8")
    assert summary_text.startswith("# Final Evaluation Summary")
    assert "## Judge Assessment" in summary_text
    assert "## Judge Assessment\n\n- Summary:" in summary_text
    assert "The result is acceptable." in summary_text
    assert "`task`: Task evidence" in summary_text
    assert "Resolution Notes" not in summary_text
    judge_json = storage.case_judge_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        model_name,
        "example_case",
        0,
    ).read_text(encoding="utf-8")
    assert judge_json.index('"dimensions"') < judge_json.index('"summary"')
    assert judge_json.index('"summary"') < judge_json.index('"evidence"')
    assert "\\u20ac" not in judge_json
    assert (
        storage.read_case_final_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model_name,
            case_id=final_result.case_id,
            repetition_index=0,
        )
        == final_result
    )


def test_storage_rejects_mismatched_fingerprint_input_kind(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    suite_id = "example_suite"
    run_profile_id = "default"
    run_profile_fingerprint = "d" * 64
    record = EvaluationFingerprintInput(
        fingerprint="c" * 64,
        payload=EvaluationFingerprintPayload(),
    )
    artifact = RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="run_001",
            case_id="example_case",
            suite_id=suite_id,
            run_profile_id=run_profile_id,
            runner_type="llm_probe",
        ),
        status=RunStatus.SUCCESS,
        request=RunRequestMetadata(requested_model="minimax/minimax-m2.7"),
    )

    try:
        storage.write_case_run(
            suite_id=suite_id,
            run_profile_id=run_profile_id,
            run_profile_fingerprint=run_profile_fingerprint,
            model_id="example_model",
            repetition_index=0,
            run_fingerprint="a" * 64,
            artifact=artifact,
            fingerprint_input=cast(RunFingerprintInput, record),
        )
    except ValueError as exc:
        assert "RunFingerprintInput" in str(exc)
    else:
        raise AssertionError("Expected write_case_run() to reject mismatched kind.")


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
        overall_score=6.5,
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
        dimensions=iteration.dimensions,
        summary="The result is acceptable.",
        evidence=iteration.evidence,
        overall_score=6.5,
        overall_evidence=["Overall evidence"],
        iteration_results=[iteration],
        raw_results=[
            RawJudgeRunResult(
                raw_result_ref="raw_001",
                judge_name="primary_judge",
                judge_model="minimax/minimax-m2.7",
                repetition_index=0,
                attempt_index=0,
                status=JudgeIterationStatus.SUCCESS,
                request_messages=[
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": "EVALUATION TARGET\nDimensions: task"},
                ],
                prompt_payload={"schema_version": 2, "evaluation_target": {"dimensions": ["task"]}},
                response_content="{}",
            )
        ],
    )


def _build_final_result() -> FinalEvaluationResult:
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
        judge_overall={"score": 6.5, "evidence": ["Overall evidence"]},
        final_score=6.5,
        summary=HybridAggregationSummary(
            deterministic_passed_checks=0,
            deterministic_failed_checks=0,
            deterministic_error_checks=0,
            judge_successful_iterations=1,
            judge_failed_iterations=0,
        ),
    )
