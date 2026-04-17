from __future__ import annotations

import json
from typing import cast

import pytest

from personal_agent_eval.aggregation.models import DimensionScores
from personal_agent_eval.cli import CliRuntime, main
from personal_agent_eval.workflow import (
    EvaluationAction,
    RunAction,
    WorkflowCaseResult,
    WorkflowResult,
    WorkflowSummary,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def run(self, *, suite_path: str, run_profile_path: str) -> WorkflowResult:
        self.calls.append(
            ("run", {"suite_path": suite_path, "run_profile_path": run_profile_path})
        )
        return _workflow_result("run")

    def evaluate(
        self,
        *,
        suite_path: str,
        run_profile_path: str,
        evaluation_profile_path: str,
    ) -> WorkflowResult:
        self.calls.append(
            (
                "eval",
                {
                    "suite_path": suite_path,
                    "run_profile_path": run_profile_path,
                    "evaluation_profile_path": evaluation_profile_path,
                },
            )
        )
        return _workflow_result("eval")

    def run_eval(
        self,
        *,
        suite_path: str,
        run_profile_path: str,
        evaluation_profile_path: str,
    ) -> WorkflowResult:
        self.calls.append(
            (
                "run-eval",
                {
                    "suite_path": suite_path,
                    "run_profile_path": run_profile_path,
                    "evaluation_profile_path": evaluation_profile_path,
                },
            )
        )
        return _workflow_result("run-eval")

    def report(
        self,
        *,
        suite_path: str,
        run_profile_path: str,
        evaluation_profile_path: str,
    ) -> WorkflowResult:
        self.calls.append(
            (
                "report",
                {
                    "suite_path": suite_path,
                    "run_profile_path": run_profile_path,
                    "evaluation_profile_path": evaluation_profile_path,
                },
            )
        )
        return _workflow_result("report")


def test_cli_routes_run_command_to_runtime_and_renders_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()

    exit_code = main(
        [
            "run",
            "--suite",
            "suites/example_suite.yaml",
            "--run-profile",
            "run_profiles/default.yaml",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert runtime.calls == [
        (
            "run",
            {
                "suite_path": "suites/example_suite.yaml",
                "run_profile_path": "run_profiles/default.yaml",
            },
        )
    ]
    output = capsys.readouterr().out
    assert "Case Results" in output
    assert "baseline_model" in output


def test_cli_routes_eval_command_to_runtime_and_renders_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()

    exit_code = main(
        [
            "eval",
            "--suite",
            "suites/example_suite.yaml",
            "--run-profile",
            "run_profiles/default.yaml",
            "--evaluation-profile",
            "evaluation_profiles/default.yaml",
            "--output",
            "json",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert runtime.calls[0][0] == "eval"
    payload = json.loads(capsys.readouterr().out)
    assert payload["suite_id"] == "example_suite"
    assert payload["case_results"][0]["final_score"] == 7.0


def test_cli_routes_report_command_to_runtime(capsys: pytest.CaptureFixture[str]) -> None:
    runtime = FakeRuntime()

    exit_code = main(
        [
            "report",
            "--suite",
            "suites/example_suite.yaml",
            "--run-profile",
            "run_profiles/default.yaml",
            "--evaluation-profile",
            "evaluation_profiles/default.yaml",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert runtime.calls[0][0] == "report"
    output = capsys.readouterr().out
    assert "Model Summary" in output
    assert "example_case" in output


def _workflow_result(command: str) -> WorkflowResult:
    return WorkflowResult(
        command=command,
        workspace_root="/tmp/workspace",
        suite_id="example_suite",
        run_profile_id="default",
        evaluation_profile_id="default" if command != "run" else None,
        results=[
            WorkflowCaseResult(
                model_id="baseline_model",
                case_id="example_case",
                run_fingerprint="a" * 64,
                evaluation_fingerprint=None if command == "run" else "b" * 64,
                run_action=RunAction.REUSED,
                evaluation_action=(
                    EvaluationAction.SKIPPED
                    if command == "run"
                    else EvaluationAction.REUSED
                ),
                run_status="success",
                evaluation_status=None if command == "run" else "success",
                final_score=None if command == "run" else 7.0,
                final_dimensions=(
                    None
                    if command == "run"
                    else DimensionScores(
                        task=7.0,
                        process=7.0,
                        autonomy=7.0,
                        closeness=7.0,
                        efficiency=7.0,
                        spark=7.0,
                    )
                ),
            )
        ],
        summary=WorkflowSummary(
            models_requested=1,
            cases_requested=1,
            model_case_pairs=1,
            runs_executed=0,
            runs_reused=1,
            evaluations_executed=0,
            evaluations_reused=0 if command == "run" else 1,
            final_results_recomputed=0,
        ),
    )
