from __future__ import annotations

import json
import os
from pathlib import Path
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
        self.calls.append(("run", {"suite_path": suite_path, "run_profile_path": run_profile_path}))
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
            "configs/suites/example_suite.yaml",
            "--run-profile",
            "configs/run_profiles/default.yaml",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert runtime.calls == [
        (
            "run",
            {
                "suite_path": "configs/suites/example_suite.yaml",
                "run_profile_path": "configs/run_profiles/default.yaml",
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
            "configs/suites/example_suite.yaml",
            "--run-profile",
            "configs/run_profiles/default.yaml",
            "--evaluation-profile",
            "configs/evaluation_profiles/default.yaml",
            "--output",
            "json",
            "--no-chart",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert runtime.calls[0][0] == "eval"
    payload = json.loads(capsys.readouterr().out)
    assert payload["suite_id"] == "example_suite"
    assert payload["case_results"][0]["final_score"] == 7.0


def test_cli_writes_default_chart_to_evaluation_profile_subdir(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """eval/report/run-eval emit a chart by default unless --no-chart is passed."""
    captured_paths: list[Path] = []

    def _fake_render(_report: object, path: Path, **_kwargs: object) -> Path:
        captured_paths.append(path)
        return path

    monkeypatch.setattr(
        "personal_agent_eval.reporting.score_cost_chart.render_score_cost_chart_png",
        _fake_render,
    )
    runtime = FakeRuntime()

    exit_code = main(
        [
            "report",
            "--suite",
            "configs/suites/example_suite.yaml",
            "--run-profile",
            "configs/run_profiles/default.yaml",
            "--evaluation-profile",
            "configs/evaluation_profiles/default.yaml",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert captured_paths == [Path("/tmp/workspace/outputs/charts/default/score_cost.png")]
    assert "Chart written to:" in capsys.readouterr().err


def test_cli_routes_report_command_to_runtime(capsys: pytest.CaptureFixture[str]) -> None:
    runtime = FakeRuntime()

    exit_code = main(
        [
            "report",
            "--suite",
            "configs/suites/example_suite.yaml",
            "--run-profile",
            "configs/run_profiles/default.yaml",
            "--evaluation-profile",
            "configs/evaluation_profiles/default.yaml",
            "--no-chart",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert runtime.calls[0][0] == "report"
    output = capsys.readouterr().out
    assert "Model Summary" in output
    assert "example_case" in output


def test_cli_resolves_ids_from_conventional_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()
    (tmp_path / "configs" / "suites").mkdir(parents=True)
    (tmp_path / "configs" / "run_profiles").mkdir(parents=True)
    (tmp_path / "configs" / "evaluation_profiles").mkdir(parents=True)
    (tmp_path / "configs" / "suites" / "example_suite.yaml").write_text(
        "suite_id: example_suite\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "run_profiles" / "default.yaml").write_text(
        "run_profile_id: default\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "evaluation_profiles" / "judge.yaml").write_text(
        "evaluation_profile_id: judge\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "run-eval",
            "--suite",
            "example_suite",
            "--run-profile",
            "default",
            "--evaluation-profile",
            "judge",
            "--no-chart",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert runtime.calls == [
        (
            "run-eval",
            {
                "suite_path": str(
                    (tmp_path / "configs" / "suites" / "example_suite.yaml").resolve()
                ),
                "run_profile_path": str(
                    (tmp_path / "configs" / "run_profiles" / "default.yaml").resolve()
                ),
                "evaluation_profile_path": str(
                    (tmp_path / "configs" / "evaluation_profiles" / "judge.yaml").resolve()
                ),
            },
        )
    ]
    assert "Case Results" in capsys.readouterr().out


def test_cli_loads_openrouter_api_key_from_workspace_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()
    (tmp_path / "configs" / "suites").mkdir(parents=True)
    (tmp_path / "configs" / "run_profiles").mkdir(parents=True)
    (tmp_path / "configs" / "evaluation_profiles").mkdir(parents=True)
    (tmp_path / "configs" / "suites" / "example_suite.yaml").write_text(
        "suite_id: example_suite\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "run_profiles" / "default.yaml").write_text(
        "run_profile_id: default\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "evaluation_profiles" / "judge.yaml").write_text(
        "evaluation_profile_id: judge\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=test-from-dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = main(
        [
            "run-eval",
            "--suite",
            "example_suite",
            "--run-profile",
            "default",
            "--evaluation-profile",
            "judge",
            "--no-chart",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert os.environ["OPENROUTER_API_KEY"] == "test-from-dotenv"
    assert "Case Results" in capsys.readouterr().out


def test_cli_loads_openrouter_api_key_from_repo_root_dotenv_when_workspace_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()
    # Simulate a repository root with .git and a shared `.env`.
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=test-from-repo-root\n",
        encoding="utf-8",
    )

    # Simulate a nested workspace (e.g. fixtures) that has configs but no `.env`.
    workspace = tmp_path / "nested_workspace"
    (workspace / "configs" / "suites").mkdir(parents=True)
    (workspace / "configs" / "run_profiles").mkdir(parents=True)
    (workspace / "configs" / "evaluation_profiles").mkdir(parents=True)
    (workspace / "configs" / "suites" / "example_suite.yaml").write_text(
        "suite_id: example_suite\n",
        encoding="utf-8",
    )
    (workspace / "configs" / "run_profiles" / "default.yaml").write_text(
        "run_profile_id: default\n",
        encoding="utf-8",
    )
    (workspace / "configs" / "evaluation_profiles" / "judge.yaml").write_text(
        "evaluation_profile_id: judge\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = main(
        [
            "run-eval",
            "--suite",
            "example_suite",
            "--run-profile",
            "default",
            "--evaluation-profile",
            "judge",
            "--no-chart",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert os.environ["OPENROUTER_API_KEY"] == "test-from-repo-root"
    assert "Case Results" in capsys.readouterr().out


def test_cli_prefers_repo_root_dotenv_over_workspace_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=test-from-repo-root\n",
        encoding="utf-8",
    )

    workspace = tmp_path / "nested_workspace"
    (workspace / "configs" / "suites").mkdir(parents=True)
    (workspace / "configs" / "run_profiles").mkdir(parents=True)
    (workspace / "configs" / "evaluation_profiles").mkdir(parents=True)
    (workspace / "configs" / "suites" / "example_suite.yaml").write_text(
        "suite_id: example_suite\n",
        encoding="utf-8",
    )
    (workspace / "configs" / "run_profiles" / "default.yaml").write_text(
        "run_profile_id: default\n",
        encoding="utf-8",
    )
    (workspace / "configs" / "evaluation_profiles" / "judge.yaml").write_text(
        "evaluation_profile_id: judge\n",
        encoding="utf-8",
    )
    (workspace / ".env").write_text(
        "OPENROUTER_API_KEY=test-from-workspace\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = main(
        [
            "run-eval",
            "--suite",
            "example_suite",
            "--run-profile",
            "default",
            "--evaluation-profile",
            "judge",
            "--no-chart",
        ],
        runtime=cast(CliRuntime, runtime),
    )

    assert exit_code == 0
    assert os.environ["OPENROUTER_API_KEY"] == "test-from-repo-root"
    assert "Case Results" in capsys.readouterr().out


def test_cli_reports_clear_error_for_unknown_suite_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime()
    (tmp_path / "configs" / "suites").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "run",
                "--suite",
                "missing_suite",
                "--run-profile",
                "default",
            ],
            runtime=cast(CliRuntime, runtime),
        )

    assert exc_info.value.code == 2
    assert "Could not resolve suite 'missing_suite'" in capsys.readouterr().err


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
                    EvaluationAction.SKIPPED if command == "run" else EvaluationAction.REUSED
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
