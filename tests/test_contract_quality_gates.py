from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from personal_agent_eval.aggregation.models import (
    DimensionResolution,
    DimensionResolutions,
    DimensionScores,
    FinalEvaluationResult,
    HybridAggregationSummary,
    SecurityBlock,
)
from personal_agent_eval.artifacts import (
    LlmExecutionParameters,
    ProviderMetadata,
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
)
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    NormalizedUsage,
    RunTiming,
    ToolCallTraceEvent,
    ToolResultTraceEvent,
    UsageMetadata,
)
from personal_agent_eval.config import (
    load_evaluation_profile,
    load_run_profile,
    load_suite_config,
    load_test_config,
)
from personal_agent_eval.config.test_config import TestConfig as CaseConfig
from personal_agent_eval.fingerprints import (
    EvaluationFingerprintInput,
    EvaluationFingerprintPayload,
    build_evaluation_fingerprint_input,
    build_run_fingerprint_input,
)
from personal_agent_eval.judge.models import (
    AggregatedJudgeResult,
    JudgeDimensions,
    JudgeEvidence,
    JudgeIterationStatus,
    NormalizedJudgeIterationResult,
    RawJudgeRunResult,
)
from personal_agent_eval.storage import EvaluationStorageManifest, FilesystemStorage

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"
CASE_FIXTURE = FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"


def test_v1_test_config_normalization_contract_is_stable() -> None:
    payload = {
        "schema_version": 1,
        "case_id": "quality_gate_case",
        "title": "Quality gate case",
        "runner": {"type": "llm_probe"},
        "input": {"messages": [{"role": "user", "content": "hello"}]},
        "deterministic_checks": [
            {
                "check_id": "check_ordering",
                "dimensions": ["spark", "task", "spark", "process"],
                "declarative": {"kind": "final_response_present"},
            }
        ],
        "tags": [" smoke ", "llm_probe", "smoke", "", "llm_probe"],
    }

    config = CaseConfig.model_validate(payload, context={"base_path": FIXTURES_ROOT})

    assert config.schema_version == 1
    assert config.tags == ["llm_probe", "smoke"]
    assert config.deterministic_checks[0].dimensions == ["process", "spark", "task"]


def test_v1_evaluation_profile_defaults_remain_frozen() -> None:
    evaluation_profile = load_evaluation_profile(
        FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
    )

    assert evaluation_profile.schema_version == 1
    assert evaluation_profile.aggregation.method == "median"
    assert evaluation_profile.final_aggregation.default_policy == "judge_only"
    assert evaluation_profile.final_aggregation.dimensions.task.policy == "weighted"
    assert evaluation_profile.final_aggregation.dimensions.autonomy.policy == "judge_only"


def test_v1_run_artifact_json_shape_remains_stable() -> None:
    artifact = _build_run_artifact(case_id="example_case", run_id="run_contract")

    payload = artifact.to_json_dict()

    assert set(payload) == {
        "identity",
        "status",
        "timing",
        "request",
        "provider",
        "usage",
        "trace",
        "output_artifacts",
        "error",
        "runner_metadata",
    }
    assert set(payload["identity"]) == {
        "schema_version",
        "run_id",
        "case_id",
        "suite_id",
        "run_profile_id",
        "runner_type",
    }
    assert [event["event_type"] for event in payload["trace"]] == [
        "message",
        "tool_call",
        "tool_result",
        "final_output",
    ]
    assert payload["status"] == "success"


def test_v1_final_evaluation_result_shape_remains_stable() -> None:
    result = _build_final_result(case_id="example_case", run_id="run_contract")

    payload = result.to_json_dict()

    assert set(payload) == {
        "schema_version",
        "case_id",
        "run_id",
        "deterministic_dimensions",
        "judge_dimensions",
        "final_dimensions",
        "dimension_resolutions",
        "final_score",
        "summary",
        "security",
        "warnings",
    }
    assert set(payload["final_dimensions"]) == {
        "task",
        "process",
        "autonomy",
        "closeness",
        "efficiency",
        "spark",
    }
    assert set(payload["dimension_resolutions"]) == {
        "task",
        "process",
        "autonomy",
        "closeness",
        "efficiency",
        "spark",
    }
    assert payload["summary"] == {
        "deterministic_passed_checks": 1,
        "deterministic_failed_checks": 0,
        "deterministic_error_checks": 0,
        "judge_successful_iterations": 1,
        "judge_failed_iterations": 0,
    }
    assert payload["security"]["verdict"] == "passed"


def test_run_fingerprint_changes_on_semantic_message_or_attachment_changes(
    tmp_path: Path,
) -> None:
    original_case = FIXTURES_ROOT / "configs" / "cases" / "example_case"
    changed_case = _copy_case_fixture(
        original_case=original_case,
        target_dir=tmp_path / "changed_case",
    )

    (changed_case / "messages.yaml").write_text(
        "- role: user\n  content: This content changed semantically.\n",
        encoding="utf-8",
    )
    (changed_case / "artifacts" / "prompt.txt").write_text(
        "The attachment content changed semantically.\n",
        encoding="utf-8",
    )

    original_test = load_test_config(original_case / "test.yaml")
    changed_test = load_test_config(changed_case / "test.yaml")
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "default.yaml")
    suite = load_suite_config(FIXTURES_ROOT / "configs" / "suites" / "example_suite.yaml")
    model_selection = suite.models[0]

    original_input = build_run_fingerprint_input(
        test_config=original_test,
        run_profile=run_profile,
        model_selection=model_selection,
    )
    changed_input = build_run_fingerprint_input(
        test_config=changed_test,
        run_profile=run_profile,
        model_selection=model_selection,
    )

    assert original_input.fingerprint != changed_input.fingerprint


def test_run_fingerprint_ignores_non_semantic_case_relocation_and_profile_naming(
    tmp_path: Path,
) -> None:
    original_case = FIXTURES_ROOT / "configs" / "cases" / "example_case"
    moved_case = _copy_case_fixture(
        original_case=original_case,
        target_dir=tmp_path / "moved_case",
    )
    original_test = load_test_config(original_case / "test.yaml")
    moved_test = load_test_config(moved_case / "test.yaml")
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "default.yaml")
    renamed_profile = run_profile.model_copy(
        update={"run_profile_id": "renamed_profile", "title": "Renamed profile"}
    )
    suite = load_suite_config(FIXTURES_ROOT / "configs" / "suites" / "example_suite.yaml")
    model_selection = suite.models[0]

    original_input = build_run_fingerprint_input(
        test_config=original_test,
        run_profile=run_profile,
        model_selection=model_selection,
    )
    moved_input = build_run_fingerprint_input(
        test_config=moved_test,
        run_profile=renamed_profile,
        model_selection=model_selection,
    )

    assert original_input.fingerprint == moved_input.fingerprint
    assert original_input.payload == moved_input.payload


def test_evaluation_fingerprint_reorder_vs_aggregation_change() -> None:
    evaluation_profile = load_evaluation_profile(
        FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
    )

    reordered = evaluation_profile.model_copy(
        update={
            "judges": list(reversed(evaluation_profile.judges)),
            "judge_runs": list(reversed(evaluation_profile.judge_runs)),
            "anchors": evaluation_profile.anchors.model_copy(
                update={"references": list(reversed(evaluation_profile.anchors.references))}
            ),
            "evaluation_profile_id": "renamed_profile",
            "title": "Renamed title",
        }
    )
    changed = evaluation_profile.model_copy(
        update={
            "final_aggregation": evaluation_profile.final_aggregation.model_copy(
                update={
                    "dimensions": evaluation_profile.final_aggregation.dimensions.model_copy(
                        update={
                            "task": (
                                evaluation_profile.final_aggregation.dimensions.task.model_copy(
                                    update={"judge_weight": 0.5, "deterministic_weight": 0.5}
                                )
                            )
                        }
                    )
                }
            )
        }
    )

    base_input = build_evaluation_fingerprint_input(evaluation_profile=evaluation_profile)
    reordered_input = build_evaluation_fingerprint_input(evaluation_profile=reordered)
    changed_input = build_evaluation_fingerprint_input(evaluation_profile=changed)

    assert base_input.fingerprint == reordered_input.fingerprint
    assert base_input.fingerprint != changed_input.fingerprint


def test_storage_layout_is_frozen_and_isolates_results_per_run_fingerprint(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    suite_id = "example_suite"
    run_profile_id = "default"
    run_profile_fingerprint = "d" * 64
    evaluation_profile_id = "judge_default"
    evaluation_fingerprint = "e" * 64
    first_run_fingerprint = "a" * 64
    second_run_fingerprint = "b" * 64
    first_model_name = "openai/gpt-example"
    second_model_name = "anthropic/other-model"
    case_id = "example_case"

    storage.write_evaluation_manifest(
        EvaluationStorageManifest(
            suite_id=suite_id,
            run_profile_id=run_profile_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_fingerprint=evaluation_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            aggregation_method="median",
            default_dimension_policy="judge_only",
            judge_system_prompt_source="path:prompts/judge_system_default.txt",
            judge_system_prompt="You are a strict evaluation judge.",
        )
    )
    storage.write_evaluation_fingerprint_input(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        EvaluationFingerprintInput(
            fingerprint=evaluation_fingerprint,
            payload=EvaluationFingerprintPayload(judge_aggregation={"method": "median"}),
        ),
    )

    first_result = _build_final_result(case_id=case_id, run_id="run_a", final_score=7.0)
    second_result = _build_final_result(case_id=case_id, run_id="run_b", final_score=8.5)
    judge_result = _build_judge_result()

    storage.write_case_judge_result(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id=evaluation_profile_id,
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=first_model_name,
        case_id=case_id,
        repetition_index=0,
        run_fingerprint=first_run_fingerprint,
        result=judge_result,
    )
    storage.write_case_final_result(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id=evaluation_profile_id,
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=first_model_name,
        repetition_index=0,
        run_fingerprint=first_run_fingerprint,
        result=first_result,
    )
    storage.write_case_judge_result(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id=evaluation_profile_id,
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=second_model_name,
        case_id=case_id,
        repetition_index=0,
        run_fingerprint=second_run_fingerprint,
        result=judge_result,
    )
    storage.write_case_final_result(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id=evaluation_profile_id,
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=second_model_name,
        repetition_index=0,
        run_fingerprint=second_run_fingerprint,
        result=second_result,
    )

    assert storage.case_judge_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        first_model_name,
        case_id,
        0,
    ) == (
        tmp_path
        / "outputs"
        / "evaluations"
        / "suit_example_suite"
        / "evaluation_profile_dddddd"
        / "eval_profile_judge_default_eeeeee"
        / "openai_gpt-example"
        / case_id
        / "raw_outputs"
        / "judge_1.json"
    )
    assert storage.case_final_result_path(
        suite_id,
        run_profile_fingerprint,
        evaluation_profile_id,
        evaluation_fingerprint,
        second_model_name,
        case_id,
        0,
    ) == (
        tmp_path
        / "outputs"
        / "evaluations"
        / "suit_example_suite"
        / "evaluation_profile_dddddd"
        / "eval_profile_judge_default_eeeeee"
        / "anthropic_other-model"
        / case_id
        / "raw_outputs"
        / "final_result_1.json"
    )
    assert (
        storage.read_case_final_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=first_model_name,
            case_id=case_id,
            repetition_index=0,
        ).final_score
        == 7.0
    )
    assert (
        storage.read_case_final_result(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=second_model_name,
            case_id=case_id,
            repetition_index=0,
        ).final_score
        == 8.5
    )


def _copy_case_fixture(*, original_case: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True)
    (target_dir / "artifacts").mkdir()
    (target_dir / "hooks").mkdir()
    (target_dir / "messages.yaml").write_text(
        (original_case / "messages.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (target_dir / "artifacts" / "prompt.txt").write_text(
        (original_case / "artifacts" / "prompt.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (target_dir / "hooks" / "custom_check.py").write_text(
        (original_case / "hooks" / "custom_check.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (target_dir / "test.yaml").write_text(
        (original_case / "test.yaml")
        .read_text(encoding="utf-8")
        .replace("case_id: example_case", f"case_id: {target_dir.name}"),
        encoding="utf-8",
    )
    return target_dir


def _build_run_artifact(*, case_id: str, run_id: str) -> RunArtifact:
    return RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id=run_id,
            case_id=case_id,
            suite_id="example_suite",
            run_profile_id="default",
            runner_type="llm_probe",
        ),
        status=RunStatus.SUCCESS,
        timing=RunTiming(
            queued_at=datetime(2026, 4, 17, 10, 0, tzinfo=UTC),
            started_at=datetime(2026, 4, 17, 10, 0, 1, tzinfo=UTC),
            completed_at=datetime(2026, 4, 17, 10, 0, 2, tzinfo=UTC),
            duration_seconds=1.0,
        ),
        request=RunRequestMetadata(
            requested_model="openai/gpt-example",
            gateway="openrouter",
            execution_parameters=LlmExecutionParameters(
                temperature=0.0,
                timeout_seconds=30.0,
                retries=5,
            ),
        ),
        provider=ProviderMetadata(
            gateway="openrouter",
            provider_name="openai",
            provider_model_id="gpt-example-2026-04-01",
        ),
        usage=UsageMetadata(
            normalized=NormalizedUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        ),
        trace=[
            MessageTraceEvent(sequence=0, event_type="message", role="user", content="hello"),
            ToolCallTraceEvent(
                sequence=1,
                event_type="tool_call",
                call_id="call_1",
                tool_name="shell",
                raw_arguments={"cmd": "echo ok"},
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
                content="done",
            ),
        ],
    )


def _build_final_result(
    *,
    case_id: str,
    run_id: str,
    final_score: float = 8.0,
) -> FinalEvaluationResult:
    task_resolution = DimensionResolution(
        policy="judge_only",
        source_used="judge",
        judge_score=8.0,
        deterministic_score=None,
        final_score=8.0,
    )
    process_resolution = DimensionResolution(
        policy="weighted",
        source_used="weighted",
        judge_score=6.0,
        deterministic_score=10.0,
        final_score=7.6,
    )
    return FinalEvaluationResult(
        case_id=case_id,
        run_id=run_id,
        deterministic_dimensions=DimensionScores(process=10.0),
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
            process=7.6,
            autonomy=7.5,
            closeness=6.5,
            efficiency=5.0,
            spark=6.0,
        ),
        dimension_resolutions=DimensionResolutions(
            task=task_resolution,
            process=process_resolution,
            autonomy=task_resolution,
            closeness=task_resolution,
            efficiency=task_resolution,
            spark=task_resolution,
        ),
        final_score=final_score,
        summary=HybridAggregationSummary(
            deterministic_passed_checks=1,
            deterministic_failed_checks=0,
            deterministic_error_checks=0,
            judge_successful_iterations=1,
            judge_failed_iterations=0,
        ),
        security=SecurityBlock(verdict="passed"),
    )


def _build_judge_result() -> AggregatedJudgeResult:
    dimensions = JudgeDimensions(
        task=8.0,
        process=6.0,
        autonomy=7.5,
        closeness=6.5,
        efficiency=5.0,
        spark=6.0,
    )
    evidence = JudgeEvidence(
        task=["Task evidence"],
        process=["Process evidence"],
        autonomy=["Autonomy evidence"],
        closeness=["Closeness evidence"],
        efficiency=["Efficiency evidence"],
        spark=["Spark evidence"],
    )
    iteration = NormalizedJudgeIterationResult(
        judge_name="primary_judge",
        judge_model="minimax/minimax-m2.7",
        repetition_index=0,
        status=JudgeIterationStatus.SUCCESS,
        dimensions=dimensions,
        summary="Looks good.",
        evidence=evidence,
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
        dimensions=dimensions,
        summary="Looks good.",
        evidence=evidence,
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
