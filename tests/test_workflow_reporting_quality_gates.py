from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from personal_agent_eval.cli import main
from personal_agent_eval.config import load_run_profile
from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterAssistantMessage,
    OpenRouterChatResponse,
)
from personal_agent_eval.fingerprints import build_run_profile_fingerprint
from personal_agent_eval.judge.models import JudgeIterationStatus, RawJudgeRunResult
from personal_agent_eval.storage import FilesystemStorage
from personal_agent_eval.workflow import EvaluationAction, RunAction, WorkflowOrchestrator


class CountingRunClient:
    def __init__(self, counter: dict[str, int]) -> None:
        self._counter = counter

    def create_chat_completion(
        self,
        chat_request: object,
        *,
        timeout_seconds: float | None = None,
    ) -> OpenRouterChatResponse:
        del chat_request, timeout_seconds
        self._counter["run_calls"] += 1
        return OpenRouterChatResponse(
            assistant_message=OpenRouterAssistantMessage(
                role="assistant",
                content="Minimal successful answer.",
            ),
            provider_name="mock-provider",
            provider_model_id="mock-provider/mock-model",
            finish_reason="stop",
            native_finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        )


class CountingJudgeClient:
    def __init__(self, counter: dict[str, int]) -> None:
        self._counter = counter

    def run_once(self, invocation: Any) -> RawJudgeRunResult:
        self._counter["judge_calls"] += 1
        parsed_response = {
            "summary": "The run completed correctly.",
            "dimensions": {
                "task": {"evidence": ["Produced the expected answer."], "score": 8.0},
                "process": {"evidence": ["The trace ended successfully."], "score": 7.0},
                "autonomy": {"evidence": ["No unnecessary escalation."], "score": 6.0},
                "closeness": {"evidence": ["The answer matched the task closely."], "score": 6.5},
                "efficiency": {"evidence": ["The run used a small number of turns."], "score": 7.5},
                "spark": {"evidence": ["The answer was acceptable."], "score": 5.5},
            },
            "overall": {"evidence": ["Overall: task mostly satisfied."], "score": 7.0},
        }
        return RawJudgeRunResult(
            raw_result_ref=invocation.raw_result_ref,
            judge_name=invocation.judge_name,
            judge_model=invocation.judge_model,
            repetition_index=invocation.repetition_index,
            attempt_index=invocation.attempt_index,
            status=JudgeIterationStatus.SUCCESS,
            request_messages=[dict(message) for message in invocation.messages],
            response_content=json.dumps(parsed_response),
            parsed_response=parsed_response,
        )


class FailingRunClient:
    def create_chat_completion(
        self,
        chat_request: object,
        *,
        timeout_seconds: float | None = None,
    ) -> OpenRouterChatResponse:
        del chat_request, timeout_seconds
        raise AssertionError("Run client should not be called in this scenario.")


class FailingJudgeClient:
    def run_once(self, invocation: Any) -> RawJudgeRunResult:
        del invocation
        raise AssertionError("Judge client should not be called in this scenario.")


def test_quality_gate_pae_run_does_not_evaluate(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    counters = {"run_calls": 0, "judge_calls": 0}
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient(counters),
        judge_client_factory=lambda: CountingJudgeClient(counters),
    )

    result = workflow.run(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
    )

    assert result.command == "run"
    assert result.summary.runs_executed == 2
    assert result.summary.evaluations_executed == 0
    assert counters == {"run_calls": 2, "judge_calls": 0}
    assert all(item.evaluation_action is EvaluationAction.SKIPPED for item in result.results)
    assert not (workspace_root / "outputs" / "evaluations").exists()


def test_quality_gate_pae_eval_reuses_runs_when_available(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    bootstrap = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient({"run_calls": 0, "judge_calls": 0}),
        judge_client_factory=lambda: CountingJudgeClient({"run_calls": 0, "judge_calls": 0}),
    )
    bootstrap.run(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
    )

    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FailingRunClient,
        judge_client_factory=lambda: CountingJudgeClient({"run_calls": 0, "judge_calls": 0}),
    )
    result = workflow.evaluate(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    assert result.command == "eval"
    assert result.summary.runs_executed == 0
    assert result.summary.runs_reused == 2
    assert result.summary.evaluations_executed == 2
    assert all(item.run_action is RunAction.REUSED for item in result.results)
    assert all(item.evaluation_action is EvaluationAction.EXECUTED for item in result.results)


def test_quality_gate_run_repetitions_aggregate_case_results(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    run_profile_path = workspace_root / "configs" / "run_profiles" / "default.yaml"
    run_profile_payload = yaml.safe_load(run_profile_path.read_text(encoding="utf-8"))
    run_profile_payload["execution_policy"]["run_repetitions"] = 3
    run_profile_path.write_text(
        yaml.safe_dump(run_profile_payload, sort_keys=False),
        encoding="utf-8",
    )

    evaluation_profile_path = workspace_root / "configs" / "evaluation_profiles" / "default.yaml"
    evaluation_profile_payload = yaml.safe_load(evaluation_profile_path.read_text(encoding="utf-8"))
    evaluation_profile_payload["judge_runs"][0]["repetitions"] = 1
    evaluation_profile_path.write_text(
        yaml.safe_dump(evaluation_profile_payload, sort_keys=False),
        encoding="utf-8",
    )

    counters = {"run_calls": 0, "judge_calls": 0}
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient(counters),
        judge_client_factory=lambda: CountingJudgeClient(counters),
    )
    result = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=run_profile_path,
        evaluation_profile_path=evaluation_profile_path,
    )

    assert counters == {"run_calls": 6, "judge_calls": 6}
    assert result.summary.model_case_pairs == 2
    assert result.summary.runs_executed == 2
    assert result.summary.evaluations_executed == 2
    assert all(item.final_score is not None for item in result.results)
    assert all(
        any("Aggregated 3 run repetitions" in warning for warning in item.warnings)
        for item in result.results
    )


def test_quality_gate_run_eval_performs_only_missing_work(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient({"run_calls": 0, "judge_calls": 0}),
        judge_client_factory=lambda: CountingJudgeClient({"run_calls": 0, "judge_calls": 0}),
    )
    initial = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    first = initial.results[0]
    second = initial.results[1]
    assert first.evaluation_fingerprint is not None
    assert second.evaluation_fingerprint is not None

    storage = FilesystemStorage(workspace_root)
    run_profile_fingerprint = build_run_profile_fingerprint(
        run_profile=load_run_profile(workspace_root / "configs" / "run_profiles" / "default.yaml")
    )
    storage.case_run_path(
        "example_suite",
        run_profile_fingerprint,
        second.model_id,
        second.case_id,
        0,
    ).unlink()
    storage.case_final_result_path(
        "example_suite",
        run_profile_fingerprint,
        "default",
        first.evaluation_fingerprint,
        first.model_id,
        first.case_id,
        0,
    ).unlink()

    counters = {"run_calls": 0, "judge_calls": 0}
    rerun_workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient(counters),
        judge_client_factory=lambda: CountingJudgeClient(counters),
    )
    result = rerun_workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    assert counters == {"run_calls": 1, "judge_calls": 0}
    assert result.summary.runs_executed == 1
    assert result.summary.runs_reused == 1
    assert result.summary.evaluations_executed == 0
    assert result.summary.final_results_recomputed == 1

    recomputed = next(
        item
        for item in result.results
        if item.model_id == first.model_id and item.case_id == first.case_id
    )
    rerun = next(
        item
        for item in result.results
        if item.model_id == second.model_id and item.case_id == second.case_id
    )
    assert recomputed.run_action is RunAction.REUSED
    assert recomputed.evaluation_action is EvaluationAction.FINAL_RECOMPUTED
    assert rerun.run_action is RunAction.EXECUTED
    assert rerun.evaluation_action is EvaluationAction.REUSED


def test_quality_gate_adding_model_to_suite_executes_only_new_model(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    suite_path = workspace_root / "configs" / "suites" / "example_suite.yaml"
    suite_payload = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    suite_payload["models"] = [suite_payload["models"][0]]
    suite_path.write_text(yaml.safe_dump(suite_payload, sort_keys=False), encoding="utf-8")

    bootstrap_counters = {"run_calls": 0, "judge_calls": 0}
    bootstrap = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient(bootstrap_counters),
        judge_client_factory=lambda: CountingJudgeClient(bootstrap_counters),
    )
    initial = bootstrap.run_eval(
        suite_path=suite_path,
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    assert bootstrap_counters == {"run_calls": 1, "judge_calls": 3}
    assert {item.model_id for item in initial.results} == {"baseline_model"}

    suite_payload["models"].append(
        {
            "model_id": "cheap_model",
            "provider": "minimax",
            "model_name": "minimax-m2.7",
        }
    )
    suite_path.write_text(yaml.safe_dump(suite_payload, sort_keys=False), encoding="utf-8")

    counters = {"run_calls": 0, "judge_calls": 0}
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient(counters),
        judge_client_factory=lambda: CountingJudgeClient(counters),
    )
    result = workflow.run_eval(
        suite_path=suite_path,
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    assert counters == {"run_calls": 1, "judge_calls": 3}
    assert result.summary.model_case_pairs == 2
    assert result.summary.runs_executed == 1
    assert result.summary.runs_reused == 1
    assert result.summary.evaluations_executed == 1
    assert result.summary.evaluations_reused == 1

    reused = next(item for item in result.results if item.model_id == "baseline_model")
    added = next(item for item in result.results if item.model_id == "cheap_model")
    assert reused.run_action is RunAction.REUSED
    assert reused.evaluation_action is EvaluationAction.REUSED
    assert added.run_action is RunAction.EXECUTED
    assert added.evaluation_action is EvaluationAction.EXECUTED

    run_profile_fingerprint = build_run_profile_fingerprint(
        run_profile=load_run_profile(workspace_root / "configs" / "run_profiles" / "default.yaml")
    )
    storage = FilesystemStorage(workspace_root)
    assert storage.case_run_path(
        "example_suite",
        run_profile_fingerprint,
        "cheap_model",
        added.case_id,
        0,
    ).exists()


def test_quality_gate_pae_report_does_not_execute_new_work_and_keeps_visibility(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = _build_workspace(tmp_path)
    bootstrap = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient({"run_calls": 0, "judge_calls": 0}),
        judge_client_factory=lambda: CountingJudgeClient({"run_calls": 0, "judge_calls": 0}),
    )
    bootstrap.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    runtime = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FailingRunClient,
        judge_client_factory=FailingJudgeClient,
    )
    exit_code = main(
        [
            "report",
            "--suite",
            str(workspace_root / "configs" / "suites" / "example_suite.yaml"),
            "--run-profile",
            str(workspace_root / "configs" / "run_profiles" / "default.yaml"),
            "--evaluation-profile",
            str(workspace_root / "configs" / "evaluation_profiles" / "default.yaml"),
        ],
        runtime=runtime,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Case Results" in output
    assert "Model Summary" in output
    assert "Model Comparison" in output
    assert "baseline_model" in output
    assert "cheap_model" in output
    assert "example_case" in output


def test_quality_gate_json_output_is_stable_and_per_model_per_case(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = _build_workspace(tmp_path)
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient({"run_calls": 0, "judge_calls": 0}),
        judge_client_factory=lambda: CountingJudgeClient({"run_calls": 0, "judge_calls": 0}),
    )

    exit_code = main(
        [
            "run-eval",
            "--suite",
            str(workspace_root / "configs" / "suites" / "example_suite.yaml"),
            "--run-profile",
            str(workspace_root / "configs" / "run_profiles" / "default.yaml"),
            "--evaluation-profile",
            str(workspace_root / "configs" / "evaluation_profiles" / "default.yaml"),
            "--output",
            "json",
        ],
        runtime=workflow,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["suite_id"] == "example_suite"
    assert payload["run_profile_id"] == "default"
    assert payload["evaluation_profile_id"] == "default"
    assert len(payload["case_results"]) == 2
    assert {item["model_id"] for item in payload["case_results"]} == {
        "baseline_model",
        "cheap_model",
    }
    assert {item["case_id"] for item in payload["case_results"]} == {"example_case"}
    assert len(payload["model_summaries"]) == 2
    assert all("average_final_score" in item for item in payload["model_summaries"])


def test_e2e_fresh_run_eval_from_empty_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = _build_workspace(tmp_path)
    counters = {"run_calls": 0, "judge_calls": 0}
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient(counters),
        judge_client_factory=lambda: CountingJudgeClient(counters),
    )

    exit_code = main(
        [
            "run-eval",
            "--suite",
            str(workspace_root / "configs" / "suites" / "example_suite.yaml"),
            "--run-profile",
            str(workspace_root / "configs" / "run_profiles" / "default.yaml"),
            "--evaluation-profile",
            str(workspace_root / "configs" / "evaluation_profiles" / "default.yaml"),
            "--output",
            "json",
        ],
        runtime=workflow,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["case_results"]
    assert counters == {"run_calls": 2, "judge_calls": 6}
    assert {item["run_action"] for item in payload["case_results"]} == {"executed"}
    assert {item["evaluation_action"] for item in payload["case_results"]} == {"executed"}
    assert {item["case_id"] for item in payload["case_results"]} == {"example_case"}
    assert {item["model_id"] for item in payload["case_results"]} == {
        "baseline_model",
        "cheap_model",
    }


def test_e2e_second_run_eval_full_reuse(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = _build_workspace(tmp_path)
    bootstrap = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient({"run_calls": 0, "judge_calls": 0}),
        judge_client_factory=lambda: CountingJudgeClient({"run_calls": 0, "judge_calls": 0}),
    )
    main(
        [
            "run-eval",
            "--suite",
            str(workspace_root / "configs" / "suites" / "example_suite.yaml"),
            "--run-profile",
            str(workspace_root / "configs" / "run_profiles" / "default.yaml"),
            "--evaluation-profile",
            str(workspace_root / "configs" / "evaluation_profiles" / "default.yaml"),
            "--output",
            "json",
        ],
        runtime=bootstrap,
    )
    capsys.readouterr()

    runtime = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FailingRunClient,
        judge_client_factory=FailingJudgeClient,
    )
    exit_code = main(
        [
            "run-eval",
            "--suite",
            str(workspace_root / "configs" / "suites" / "example_suite.yaml"),
            "--run-profile",
            str(workspace_root / "configs" / "run_profiles" / "default.yaml"),
            "--evaluation-profile",
            str(workspace_root / "configs" / "evaluation_profiles" / "default.yaml"),
            "--output",
            "json",
        ],
        runtime=runtime,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {item["run_action"] for item in payload["case_results"]} == {"reused"}
    assert {item["evaluation_action"] for item in payload["case_results"]} == {"reused"}
    summary_models = {item["model_id"] for item in payload["model_summaries"]}
    assert summary_models == {"baseline_model", "cheap_model"}


def test_e2e_same_run_different_evaluation_profile_re_evaluates_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace_root = _build_workspace(tmp_path)
    bootstrap = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient({"run_calls": 0, "judge_calls": 0}),
        judge_client_factory=lambda: CountingJudgeClient({"run_calls": 0, "judge_calls": 0}),
    )
    main(
        [
            "run-eval",
            "--suite",
            str(workspace_root / "configs" / "suites" / "example_suite.yaml"),
            "--run-profile",
            str(workspace_root / "configs" / "run_profiles" / "default.yaml"),
            "--evaluation-profile",
            str(workspace_root / "configs" / "evaluation_profiles" / "default.yaml"),
            "--output",
            "json",
        ],
        runtime=bootstrap,
    )
    capsys.readouterr()

    alternate_eval = workspace_root / "configs" / "evaluation_profiles" / "alternate.yaml"
    alternate_payload = yaml.safe_load(
        (workspace_root / "configs" / "evaluation_profiles" / "default.yaml").read_text(
            encoding="utf-8"
        )
    )
    alternate_payload["evaluation_profile_id"] = "alternate"
    alternate_payload["final_aggregation"]["dimensions"]["task"]["judge_weight"] = 0.9
    alternate_payload["final_aggregation"]["dimensions"]["task"]["deterministic_weight"] = 0.1
    alternate_eval.write_text(
        yaml.safe_dump(alternate_payload, sort_keys=False),
        encoding="utf-8",
    )

    counters = {"run_calls": 0, "judge_calls": 0}
    runtime = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=lambda: CountingRunClient(counters),
        judge_client_factory=lambda: CountingJudgeClient(counters),
    )
    exit_code = main(
        [
            "eval",
            "--suite",
            str(workspace_root / "configs" / "suites" / "example_suite.yaml"),
            "--run-profile",
            str(workspace_root / "configs" / "run_profiles" / "default.yaml"),
            "--evaluation-profile",
            str(alternate_eval),
            "--output",
            "json",
        ],
        runtime=runtime,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert counters == {"run_calls": 0, "judge_calls": 6}
    assert {item["run_action"] for item in payload["case_results"]} == {"reused"}
    assert {item["evaluation_action"] for item in payload["case_results"]} == {"executed"}


def _build_workspace(tmp_path: Path) -> Path:
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "config"
    workspace_root = tmp_path / "workspace"
    shutil.copytree(fixture_root, workspace_root)

    suite_path = workspace_root / "configs" / "suites" / "example_suite.yaml"
    suite_payload = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    suite_payload["models"] = [
        {
            "model_id": "baseline_model",
            "provider": "openai",
            "model_name": "gpt-example",
        },
        {
            "model_id": "cheap_model",
            "provider": "minimax",
            "model_name": "minimax-m2.7",
        },
    ]
    suite_path.write_text(yaml.safe_dump(suite_payload, sort_keys=False), encoding="utf-8")
    return workspace_root
