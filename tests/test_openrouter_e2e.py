from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import yaml

from personal_agent_eval.artifacts import RunStatus
from personal_agent_eval.artifacts.run_artifact import FinalOutputTraceEvent
from personal_agent_eval.config import load_run_profile
from personal_agent_eval.fingerprints import build_run_profile_fingerprint
from personal_agent_eval.judge.models import JudgeOutputContract
from personal_agent_eval.storage import FilesystemStorage
from personal_agent_eval.workflow import EvaluationAction, RunAction, WorkflowOrchestrator

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "config"
RUN_E2E_ENV_VAR = "PERSONAL_AGENT_EVAL_RUN_OPENROUTER_E2E"
RUN_MODEL_ENV_VAR = "PERSONAL_AGENT_EVAL_OPENROUTER_E2E_RUN_MODEL"
JUDGE_MODEL_ENV_VAR = "PERSONAL_AGENT_EVAL_OPENROUTER_E2E_JUDGE_MODEL"
DEFAULT_E2E_MODEL = "openai/gpt-4o-mini"


def _require_openrouter_e2e_env() -> tuple[str, str]:
    if os.getenv(RUN_E2E_ENV_VAR) != "1":
        pytest.skip(f"Set {RUN_E2E_ENV_VAR}=1 to allow the real OpenRouter smoke test to run.")

    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("Set OPENROUTER_API_KEY to run the real OpenRouter smoke test.")

    run_model = os.getenv(RUN_MODEL_ENV_VAR, DEFAULT_E2E_MODEL)
    judge_model = os.getenv(JUDGE_MODEL_ENV_VAR, run_model)
    return run_model, judge_model


@pytest.mark.openrouter_e2e
def test_openrouter_smoke_run_eval_executes_real_provider_and_judge_requests(
    tmp_path: Path,
) -> None:
    run_model, judge_model = _require_openrouter_e2e_env()
    workspace_root = _build_workspace(
        tmp_path,
        run_model=run_model,
        judge_model=judge_model,
    )

    workflow = WorkflowOrchestrator(storage_root=workspace_root)
    result = workflow.run_eval(
        suite_path=workspace_root / "configs" / "suites" / "openrouter_full_e2e_suite.yaml",
        run_profile_path=workspace_root / "configs" / "run_profiles" / "openrouter_full_e2e.yaml",
        evaluation_profile_path=(
            workspace_root / "configs" / "evaluation_profiles" / "openrouter_full_e2e.yaml"
        ),
    )

    assert result.summary.model_case_pairs == 1
    assert result.summary.runs_executed == 1
    assert result.summary.evaluations_executed == 1
    assert len(result.results) == 1

    case_result = result.results[0]
    assert case_result.model_id == "openrouter_e2e_model"
    assert case_result.case_id == "example_case"
    assert case_result.run_action is RunAction.EXECUTED
    assert case_result.evaluation_action is EvaluationAction.EXECUTED
    assert case_result.evaluation_fingerprint is not None
    assert case_result.evaluation_status == "success"
    assert case_result.final_score is not None

    storage = FilesystemStorage(workspace_root)
    run_profile_fingerprint = build_run_profile_fingerprint(
        run_profile=load_run_profile(
            workspace_root / "configs" / "run_profiles" / "openrouter_full_e2e.yaml"
        )
    )
    artifact = storage.read_case_run(
        suite_id="openrouter_full_e2e_suite",
        run_profile_fingerprint=run_profile_fingerprint,
        model_id=case_result.model_id,
        case_id=case_result.case_id,
        repetition_index=0,
    )
    assert artifact.status is RunStatus.SUCCESS
    assert artifact.request.requested_model == run_model
    assert artifact.request.gateway == "openrouter"
    assert artifact.provider.gateway == "openrouter"
    assert artifact.provider.provider_model_id
    assert artifact.runner_metadata["attempt_count"] == 1
    final_event = artifact.trace[-1]
    assert isinstance(final_event, FinalOutputTraceEvent)
    assert final_event.content is not None
    assert final_event.content.strip()

    evaluation_fingerprint = case_result.evaluation_fingerprint
    assert evaluation_fingerprint is not None
    assert storage.has_case_judge_result(
        suite_id="openrouter_full_e2e_suite",
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id="openrouter_full_e2e",
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=case_result.model_id,
        case_id=case_result.case_id,
        repetition_index=0,
        run_fingerprint=case_result.run_fingerprint,
    )
    assert storage.has_case_final_result(
        suite_id="openrouter_full_e2e_suite",
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id="openrouter_full_e2e",
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=case_result.model_id,
        case_id=case_result.case_id,
        repetition_index=0,
        run_fingerprint=case_result.run_fingerprint,
    )

    judge_result = storage.read_case_judge_result(
        suite_id="openrouter_full_e2e_suite",
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id="openrouter_full_e2e",
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=case_result.model_id,
        case_id=case_result.case_id,
        repetition_index=0,
    )
    assert judge_result.judge_name == "openrouter_rubric_judge"
    assert judge_result.judge_model == judge_model
    assert judge_result.successful_iterations == 1
    assert judge_result.failed_iterations == 0
    assert judge_result.dimensions is not None
    assert judge_result.dimensions.task is not None
    assert judge_result.summary is not None
    assert judge_result.summary.strip()
    assert judge_result.raw_results
    assert judge_result.raw_results[0].parsed_response is not None
    judge_contract = JudgeOutputContract.model_validate(judge_result.raw_results[0].parsed_response)
    assert judge_contract.summary.strip()
    assert judge_contract.dimensions.task is not None

    final_result = storage.read_case_final_result(
        suite_id="openrouter_full_e2e_suite",
        run_profile_fingerprint=run_profile_fingerprint,
        evaluation_profile_id="openrouter_full_e2e",
        evaluation_fingerprint=evaluation_fingerprint,
        model_id=case_result.model_id,
        case_id=case_result.case_id,
        repetition_index=0,
    )
    assert final_result.case_id == case_result.case_id
    assert final_result.run_id == artifact.identity.run_id
    assert final_result.final_score is not None
    assert final_result.final_dimensions.task is not None


def _build_workspace(tmp_path: Path, *, run_model: str, judge_model: str) -> Path:
    workspace_root = tmp_path / "workspace"
    shutil.copytree(FIXTURE_ROOT, workspace_root)

    suite_payload = yaml.safe_load(
        (workspace_root / "configs" / "suites" / "example_suite.yaml").read_text(encoding="utf-8")
    )
    suite_payload["suite_id"] = "openrouter_full_e2e_suite"
    suite_payload["title"] = "OpenRouter full e2e suite"
    suite_payload["models"] = [
        {
            "model_id": "openrouter_e2e_model",
            "requested_model": run_model,
            "label": "OpenRouter e2e model",
        }
    ]
    (workspace_root / "configs" / "suites" / "openrouter_full_e2e_suite.yaml").write_text(
        yaml.safe_dump(suite_payload, sort_keys=False),
        encoding="utf-8",
    )

    run_profile_payload = yaml.safe_load(
        (workspace_root / "configs" / "run_profiles" / "default.yaml").read_text(encoding="utf-8")
    )
    run_profile_payload["run_profile_id"] = "openrouter_full_e2e"
    run_profile_payload["title"] = "OpenRouter full e2e profile"
    run_profile_payload["runner_defaults"] = {
        "timeout_seconds": 45,
        "max_tokens": 256,
        "retries": 0,
        "temperature": 0,
    }
    run_profile_payload["model_overrides"] = {}
    run_profile_payload["execution_policy"] = {
        "max_concurrency": 1,
        "fail_fast": True,
        "stop_on_runner_error": True,
    }
    (workspace_root / "configs" / "run_profiles" / "openrouter_full_e2e.yaml").write_text(
        yaml.safe_dump(run_profile_payload, sort_keys=False),
        encoding="utf-8",
    )

    evaluation_payload = yaml.safe_load(
        (workspace_root / "configs" / "evaluation_profiles" / "default.yaml").read_text(
            encoding="utf-8"
        )
    )
    evaluation_payload["evaluation_profile_id"] = "openrouter_full_e2e"
    evaluation_payload["title"] = "OpenRouter full e2e profile"
    evaluation_payload["judges"] = [
        {
            "judge_id": "openrouter_judge",
            "type": "llm_probe",
            "model": judge_model,
        }
    ]
    evaluation_payload["judge_runs"] = [
        {
            "judge_run_id": "openrouter_rubric_judge",
            "judge_id": "openrouter_judge",
            "repetitions": 1,
        }
    ]
    (workspace_root / "configs" / "evaluation_profiles" / "openrouter_full_e2e.yaml").write_text(
        yaml.safe_dump(evaluation_payload, sort_keys=False),
        encoding="utf-8",
    )

    return workspace_root
