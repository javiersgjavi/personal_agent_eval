from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent_eval.artifacts import (
    OutputArtifactRef,
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
    ToolCallTraceEvent,
    TraceEvent,
)
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
)
from personal_agent_eval.config.test_config import load_test_config
from personal_agent_eval.deterministic import (
    DeterministicCheckOutcome,
    DeterministicEvaluator,
    evaluate_deterministic_checks,
    evaluate_test_config_deterministic_checks,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def build_artifact(
    *,
    status: RunStatus = RunStatus.SUCCESS,
    final_output: str | None = "Completed successfully.",
) -> RunArtifact:
    trace: list[TraceEvent] = [
        MessageTraceEvent(
            sequence=0,
            event_type="message",
            role="user",
            content="Run the task.",
        ),
        ToolCallTraceEvent(
            sequence=1,
            event_type="tool_call",
            call_id="call_1",
            tool_name="shell",
            raw_arguments={"cmd": "echo ok"},
        ),
    ]
    if final_output is not None:
        trace.append(
            FinalOutputTraceEvent(
                sequence=2,
                event_type="final_output",
                content=final_output,
            )
        )

    return RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="run-0001",
            case_id="example_case",
            suite_id="example_suite",
            run_profile_id="default",
            runner_type="llm_probe",
        ),
        status=status,
        request=RunRequestMetadata(requested_model="openai/gpt-5-mini"),
        trace=trace,
        output_artifacts=[
            OutputArtifactRef(
                artifact_id="transcript",
                artifact_type="trace_json",
                uri="file:///tmp/run-0001/trace.json",
            )
        ],
    )


def test_evaluator_runs_standard_checks_from_test_config_fixture() -> None:
    config = load_test_config(FIXTURES_ROOT / "cases" / "example_case" / "test.yaml")
    artifact = build_artifact()

    result = evaluate_test_config_deterministic_checks(config, artifact)

    assert result.passed is True
    assert result.summary.total_checks == 2
    assert result.summary.passed_checks == 2
    assert result.summary.failed_checks == 0
    assert result.summary.error_checks == 0
    assert result.checks[0].check_id == "final-response-present"
    assert result.checks[0].outcome is DeterministicCheckOutcome.PASSED
    assert result.checks[1].source == "python_hook"
    assert result.checks[1].outputs["final_output_count"] == 1


def test_evaluator_supports_standard_v1_checks_with_filesystem_paths(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    result_file = output_dir / "result.txt"
    result_file.write_text("deterministic summary\n", encoding="utf-8")
    config_path = tmp_path / "test.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: example_case",
                "title: Deterministic checks",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages: []",
                "deterministic_checks:",
                "  - check_id: response_present",
                "    declarative:",
                "      kind: final_response_present",
                "  - check_id: one_tool_call",
                "    declarative:",
                "      kind: tool_call_count",
                "      count: 1",
                "  - check_id: status_success",
                "    declarative:",
                "      kind: status_is",
                "      status: success",
                "  - check_id: result_file_exists",
                "    declarative:",
                "      kind: file_exists",
                "      path: outputs/result.txt",
                "  - check_id: result_file_contains",
                "    declarative:",
                "      kind: file_contains",
                "      path: outputs/result.txt",
                "      text: summary",
                "  - check_id: output_dir_exists",
                "    declarative:",
                "      kind: path_exists",
                "      path: outputs",
                "  - check_id: transcript_artifact_present",
                "    declarative:",
                "      kind: output_artifact_present",
                "      artifact_id: transcript",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = load_test_config(config_path)

    result = evaluate_test_config_deterministic_checks(config, build_artifact())

    assert result.passed is True
    assert [check.outcome for check in result.checks] == [
        DeterministicCheckOutcome.PASSED,
        DeterministicCheckOutcome.PASSED,
        DeterministicCheckOutcome.PASSED,
        DeterministicCheckOutcome.PASSED,
        DeterministicCheckOutcome.PASSED,
        DeterministicCheckOutcome.PASSED,
        DeterministicCheckOutcome.PASSED,
    ]


def test_evaluator_records_failed_check_outputs() -> None:
    config = load_test_config(FIXTURES_ROOT / "cases" / "example_case" / "test.yaml")
    artifact = build_artifact(final_output=None)

    result = evaluate_test_config_deterministic_checks(config, artifact)

    assert result.passed is False
    assert result.summary.failed_checks == 2
    assert result.checks[0].outcome is DeterministicCheckOutcome.FAILED
    assert result.checks[0].outputs["final_output_count"] == 0


def test_evaluator_supports_import_path_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "hook_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "hooks.py").write_text(
        "\n".join(
            [
                "from personal_agent_eval.artifacts import RunArtifact",
                "from personal_agent_eval.deterministic import DeterministicHookContext",
                "",
                "def imported_check(artifact: RunArtifact, context: DeterministicHookContext):",
                "    return {",
                "        'passed': artifact.status.value == 'success',",
                "        'metadata': {'check_id': context.check_id},",
                "    }",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    config_path = tmp_path / "test.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: example_case",
                "title: Import hook",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages: []",
                "deterministic_checks:",
                "  - check_id: imported_hook",
                "    python_hook:",
                "      import_path: hook_pkg.hooks",
                "      callable_name: imported_check",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = load_test_config(config_path)

    result = evaluate_test_config_deterministic_checks(config, build_artifact())

    assert result.passed is True
    assert result.checks[0].metadata["check_id"] == "imported_hook"


def test_evaluator_can_disable_local_python_hooks() -> None:
    config = load_test_config(FIXTURES_ROOT / "cases" / "example_case" / "test.yaml")
    evaluator = DeterministicEvaluator(allow_local_python_hooks=False)

    result = evaluator.evaluate_test_config(config, build_artifact())

    assert result.passed is False
    assert result.summary.passed_checks == 1
    assert result.summary.error_checks == 1
    assert result.checks[1].outcome is DeterministicCheckOutcome.ERROR
    assert "disabled" in (result.checks[1].message or "")


def test_evaluate_deterministic_checks_accepts_explicit_list() -> None:
    config = load_test_config(FIXTURES_ROOT / "cases" / "example_case" / "test.yaml")

    result = evaluate_deterministic_checks(
        config.deterministic_checks,
        build_artifact(),
        case_source_path=config.source_path,
    )

    assert result.case_id == "example_case"
    assert result.run_id == "run-0001"
    assert len(result.checks) == 2
