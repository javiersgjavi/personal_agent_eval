from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from personal_agent_eval.config import load_run_profile
from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterAssistantMessage,
    OpenRouterChatResponse,
)
from personal_agent_eval.fingerprints import build_run_profile_fingerprint
from personal_agent_eval.judge.models import JudgeIterationStatus, RawJudgeRunResult
from personal_agent_eval.storage import FilesystemStorage
from personal_agent_eval.workflow import EvaluationAction, RunAction, WorkflowOrchestrator


class FakeRunClient:
    def create_chat_completion(
        self,
        chat_request: object,
        *,
        timeout_seconds: float | None = None,
    ) -> OpenRouterChatResponse:
        del chat_request, timeout_seconds
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


class FakeJudgeClient:
    def run_once(self, invocation: Any) -> RawJudgeRunResult:
        parsed_response = {
            "dimensions": {
                "task": 8.0,
                "process": 7.0,
                "autonomy": 6.0,
                "closeness": 6.5,
                "efficiency": 7.5,
                "spark": 5.5,
            },
            "summary": "The run completed correctly.",
            "evidence": {
                "task": ["Produced the expected answer."],
                "process": ["The trace ended successfully."],
                "autonomy": ["No unnecessary escalation."],
                "closeness": ["The answer matched the task closely."],
                "efficiency": ["The run used a small number of turns."],
                "spark": ["The answer was acceptable."],
            },
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


class AlwaysInvalidJudgeClient:
    def run_once(self, invocation: Any) -> RawJudgeRunResult:
        return RawJudgeRunResult(
            raw_result_ref=invocation.raw_result_ref,
            judge_name=invocation.judge_name,
            judge_model=invocation.judge_model,
            repetition_index=invocation.repetition_index,
            attempt_index=invocation.attempt_index,
            status=JudgeIterationStatus.SUCCESS,
            request_messages=[dict(message) for message in invocation.messages],
            response_content="not json",
            parsed_response=None,
        )


def test_run_eval_executes_then_reuses_all(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FakeRunClient,
        judge_client_factory=FakeJudgeClient,
    )

    first = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )
    second = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    assert first.summary.model_case_pairs == 2
    assert first.summary.runs_executed == 2
    assert first.summary.evaluations_executed == 2
    assert all(result.run_action is RunAction.EXECUTED for result in first.results)
    assert all(result.evaluation_action is EvaluationAction.EXECUTED for result in first.results)
    assert all(result.final_score is not None for result in first.results)

    assert second.summary.runs_reused == 2
    assert second.summary.evaluations_reused == 2
    assert all(result.run_action is RunAction.REUSED for result in second.results)
    assert all(result.evaluation_action is EvaluationAction.REUSED for result in second.results)


def test_eval_recomputes_only_missing_final_result(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FakeRunClient,
        judge_client_factory=FakeJudgeClient,
    )

    initial = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )
    target = initial.results[0]
    assert target.evaluation_fingerprint is not None
    storage = FilesystemStorage(workspace_root)
    run_profile_fingerprint = build_run_profile_fingerprint(
        run_profile=load_run_profile(workspace_root / "configs" / "run_profiles" / "default.yaml")
    )
    final_result_path = storage.case_final_result_path(
        "example_suite",
        run_profile_fingerprint,
        "default",
        target.evaluation_fingerprint,
        target.model_id,
        target.case_id,
        0,
    )
    final_result_path.unlink()

    result = workflow.evaluate(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    recomputed = next(
        item
        for item in result.results
        if item.case_id == target.case_id and item.model_id == target.model_id
    )
    untouched = next(
        item
        for item in result.results
        if item.case_id == target.case_id and item.model_id != target.model_id
    )
    assert recomputed.run_action is RunAction.REUSED
    assert recomputed.evaluation_action is EvaluationAction.FINAL_RECOMPUTED
    assert untouched.evaluation_action is EvaluationAction.REUSED


def test_report_reads_existing_artifacts_without_reexecution(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FakeRunClient,
        judge_client_factory=FakeJudgeClient,
    )

    workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )
    report = workflow.report(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    assert report.command == "report"
    assert report.summary.runs_reused == 2
    assert report.summary.evaluations_reused == 2
    assert all(result.run_action is RunAction.REUSED for result in report.results)
    assert all(result.evaluation_action is EvaluationAction.REUSED for result in report.results)
    assert all(result.final_dimensions is not None for result in report.results)


def test_run_eval_marks_evaluation_failed_when_judge_produces_no_successful_iterations(
    tmp_path: Path,
) -> None:
    workspace_root = _build_workspace(tmp_path)
    case_path = workspace_root / "configs" / "cases" / "example_case" / "test.yaml"
    case_payload = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    case_payload["deterministic_checks"] = []
    case_path.write_text(yaml.safe_dump(case_payload, sort_keys=False), encoding="utf-8")

    eval_path = workspace_root / "configs" / "evaluation_profiles" / "default.yaml"
    eval_payload = yaml.safe_load(eval_path.read_text(encoding="utf-8"))
    eval_payload["final_aggregation"]["dimensions"] = {}
    eval_path.write_text(yaml.safe_dump(eval_payload, sort_keys=False), encoding="utf-8")

    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FakeRunClient,
        judge_client_factory=AlwaysInvalidJudgeClient,
    )

    result = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    assert result.summary.model_case_pairs == 2
    assert result.summary.evaluations_executed == 2
    assert all(item.evaluation_action is EvaluationAction.EXECUTED for item in result.results)
    assert all(item.evaluation_status == "failed" for item in result.results)
    assert all(item.final_score is None for item in result.results)


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
