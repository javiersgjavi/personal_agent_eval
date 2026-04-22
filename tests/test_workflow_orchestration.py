from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from helpers.docker_subprocess_stub import patch_openclaw_docker_run
from personal_agent_eval.config import load_evaluation_profile, load_run_profile
from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterAssistantMessage,
    OpenRouterChatResponse,
)
from personal_agent_eval.fingerprints import build_run_profile_fingerprint
from personal_agent_eval.judge.models import JudgeIterationStatus, RawJudgeRunResult
from personal_agent_eval.judge.system_prompt import resolve_judge_system_prompt_details
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
            prompt_payload=invocation.prompt_payload,
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
            prompt_payload=invocation.prompt_payload,
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


def test_run_eval_persists_resolved_judge_prompt_in_evaluation_manifest(tmp_path: Path) -> None:
    workspace_root = _build_workspace(tmp_path)
    workflow = WorkflowOrchestrator(
        storage_root=workspace_root,
        run_client_factory=FakeRunClient,
        judge_client_factory=FakeJudgeClient,
    )

    result = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "example_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "default.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )

    evaluation_fingerprint = result.results[0].evaluation_fingerprint
    assert evaluation_fingerprint is not None
    run_profile_fingerprint = build_run_profile_fingerprint(
        run_profile=load_run_profile(workspace_root / "configs" / "run_profiles" / "default.yaml")
    )
    evaluation_profile = load_evaluation_profile(
        workspace_root / "configs" / "evaluation_profiles" / "default.yaml"
    )
    expected_prompt = resolve_judge_system_prompt_details(evaluation_profile)
    storage = FilesystemStorage(workspace_root)

    manifest = storage.read_evaluation_manifest(
        "example_suite",
        run_profile_fingerprint,
        "default",
        evaluation_fingerprint,
    )

    assert manifest.judge_system_prompt_source == expected_prompt["source"]
    assert manifest.judge_system_prompt == expected_prompt["text"]
    prompt_user_path = storage.case_judge_prompt_user_path(
        "example_suite",
        run_profile_fingerprint,
        "default",
        evaluation_fingerprint,
        result.results[0].model_id,
        result.results[0].case_id,
        0,
    )
    prompt_debug_path = storage.case_judge_prompt_debug_path(
        "example_suite",
        run_profile_fingerprint,
        "default",
        evaluation_fingerprint,
        result.results[0].model_id,
        result.results[0].case_id,
        0,
    )
    summary_path = storage.case_evaluation_result_summary_path(
        "example_suite",
        run_profile_fingerprint,
        "default",
        evaluation_fingerprint,
        result.results[0].model_id,
        result.results[0].case_id,
        0,
    )
    assert prompt_user_path.is_file()
    assert prompt_debug_path.is_file()
    assert summary_path.is_file()
    prompt_payload = json.loads(prompt_user_path.read_text(encoding="utf-8"))
    assert prompt_payload["schema_version"] == 2
    assert "run_artifact" not in prompt_payload
    assert "judge_name" not in prompt_payload
    assert "judge_model" not in prompt_payload
    prompt_text = prompt_debug_path.read_text(encoding="utf-8")
    assert "SYSTEM PROMPT:" in prompt_text
    assert "USER PROMPT:" in prompt_text
    assert summary_path.read_text(encoding="utf-8").startswith("# Final Evaluation Summary")


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
    summary_path = storage.case_evaluation_result_summary_path(
        "example_suite",
        run_profile_fingerprint,
        "default",
        target.evaluation_fingerprint,
        target.model_id,
        target.case_id,
        0,
    )
    final_result_path.unlink()
    summary_path.unlink()

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
    assert summary_path.is_file()


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


def test_openclaw_workflow_run_executes_then_reuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_openclaw_docker_run(monkeypatch)
    workspace_root = _build_openclaw_workspace(tmp_path)
    workflow = WorkflowOrchestrator(storage_root=workspace_root)

    first = workflow.run(
        suite_path=workspace_root / "configs" / "suites" / "openclaw_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "openclaw.yaml",
    )
    second = workflow.run(
        suite_path=workspace_root / "configs" / "suites" / "openclaw_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "openclaw.yaml",
    )

    assert first.summary.model_case_pairs == 1
    assert first.summary.runs_executed == 1
    assert first.results[0].run_action is RunAction.EXECUTED
    assert first.results[0].run_status == "success"

    assert second.summary.runs_reused == 1
    assert second.results[0].run_action is RunAction.REUSED


def test_openclaw_workflow_report_finds_stored_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_openclaw_docker_run(monkeypatch)
    workspace_root = _build_openclaw_workspace(tmp_path)
    workflow = WorkflowOrchestrator(storage_root=workspace_root)
    workflow.run(
        suite_path=workspace_root / "configs" / "suites" / "openclaw_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "openclaw.yaml",
    )
    report = workflow.report(
        suite_path=workspace_root / "configs" / "suites" / "openclaw_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "openclaw.yaml",
        evaluation_profile_path=workspace_root / "configs" / "evaluation_profiles" / "default.yaml",
    )
    assert report.results[0].run_action is RunAction.REUSED
    assert report.results[0].run_status == "success"


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
    run_profile_fingerprint = build_run_profile_fingerprint(
        run_profile=load_run_profile(workspace_root / "configs" / "run_profiles" / "default.yaml")
    )
    evaluation_fingerprint = result.results[0].evaluation_fingerprint
    assert evaluation_fingerprint is not None
    storage = FilesystemStorage(workspace_root)
    summary_path = storage.case_evaluation_result_summary_path(
        "example_suite",
        run_profile_fingerprint,
        "default",
        evaluation_fingerprint,
        result.results[0].model_id,
        result.results[0].case_id,
        0,
    )
    assert summary_path.is_file()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "Final score: `not available`" in summary_text
    assert "Judge output:" in summary_text


def _build_openclaw_workspace(tmp_path: Path) -> Path:
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "config"
    workspace_root = tmp_path / "openclaw_workspace"
    shutil.copytree(fixture_root, workspace_root)

    case_dir = workspace_root / "configs" / "cases" / "openclaw_smoke"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "test.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: openclaw_smoke",
                "title: OpenClaw smoke workflow",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: user",
                "      content: Produce report.md in the workspace.",
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
                "expectations:",
                "  hard_expectations:",
                "    - text: Produces a workspace report file.",
                "deterministic_checks:",
                "  - check_id: oc-final-response",
                "    dimensions:",
                "      - task",
                "    declarative:",
                "      kind: final_response_present",
                "  - check_id: oc-report-md",
                "    dimensions:",
                "      - process",
                "    declarative:",
                "      kind: openclaw_workspace_file_present",
                "      relative_path: report.md",
                '      contains: "# Report"',
                "tags:",
                "  - smoke",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    suite_path = workspace_root / "configs" / "suites" / "openclaw_suite.yaml"
    suite_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "suite_id": "openclaw_suite",
                "title": "OpenClaw suite",
                "models": [
                    {
                        "model_id": "baseline_model",
                        "provider": "openai",
                        "model_name": "gpt-example",
                    },
                ],
                "case_selection": {"include_case_ids": ["openclaw_smoke"]},
                "metadata": {"owner": "qa"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return workspace_root


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
