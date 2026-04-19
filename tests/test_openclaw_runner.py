from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from personal_agent_eval.artifacts import parse_openclaw_run_evidence
from personal_agent_eval.config import load_openclaw_agent, load_run_profile, load_test_config
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import TestConfig as CaseConfig
from personal_agent_eval.domains.openclaw import (
    OpenClawCommandResult,
    OpenClawExecutor,
    run_openclaw_case,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


class FakeOpenClawExecutor(OpenClawExecutor):
    def validate_config(
        self,
        *,
        config_path: Path,
        env: Mapping[str, str],
    ) -> OpenClawCommandResult:
        del config_path, env
        return OpenClawCommandResult(returncode=0, stdout='{"ok":true}\n')

    def run_agent(
        self,
        *,
        agent_id: str,
        message: str,
        config_path: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> OpenClawCommandResult:
        del agent_id, env, timeout_seconds
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        workspace_dir = Path(payload["agents"]["defaults"]["workspace"])
        (workspace_dir / "report.md").write_text(
            f"# Report\n\n{message[:32]}\n",
            encoding="utf-8",
        )
        return OpenClawCommandResult(
            returncode=0,
            stdout=json.dumps({"content": "Generated report.md"}),
            stderr="mock log output\n",
        )


class InvalidConfigExecutor(OpenClawExecutor):
    def validate_config(
        self,
        *,
        config_path: Path,
        env: Mapping[str, str],
    ) -> OpenClawCommandResult:
        del config_path, env
        return OpenClawCommandResult(returncode=1, stderr="invalid config\n")

    def run_agent(
        self,
        *,
        agent_id: str,
        message: str,
        config_path: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> OpenClawCommandResult:
        raise AssertionError("run_agent() should not be called after validation failure.")


def test_run_openclaw_case_success_captures_external_evidence(tmp_path: Path) -> None:
    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_openclaw_1",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        executor=FakeOpenClawExecutor(),
        runtime_root=tmp_path / "runtime",
    )

    evidence = parse_openclaw_run_evidence(artifact.runner_metadata)
    assert artifact.status.value == "success"
    assert artifact.request.gateway == "openclaw"
    assert artifact.request.execution_parameters.timeout_seconds == 300.0
    assert evidence is not None
    assert evidence.agent_id == "support_agent"
    assert evidence.generated_openclaw_config is not None
    assert evidence.raw_session_trace is not None
    assert evidence.openclaw_logs is not None
    assert evidence.workspace_snapshot is not None
    assert evidence.workspace_diff is not None
    assert len(artifact.output_artifacts) == 1
    assert len(evidence.key_output_artifacts) == 1

    generated_config_path = Path(evidence.generated_openclaw_config.uri.removeprefix("file://"))
    raw_trace_path = Path(evidence.raw_session_trace.uri.removeprefix("file://"))
    log_path = Path(evidence.openclaw_logs.uri.removeprefix("file://"))
    diff_path = Path(evidence.workspace_diff.uri.removeprefix("file://"))
    key_output_path = Path(artifact.output_artifacts[0].uri.removeprefix("file://"))

    assert generated_config_path.is_file()
    assert (
        raw_trace_path.read_text(encoding="utf-8").strip()
        == '{"content": "Generated report.md"}'
    )
    assert "run_agent" in log_path.read_text(encoding="utf-8")
    assert "report.md" in diff_path.read_text(encoding="utf-8")
    assert key_output_path.read_text(encoding="utf-8").startswith("# Report")
    assert artifact.trace[-1].event_type == "final_output"


def test_run_openclaw_case_invalid_config_still_records_evidence(tmp_path: Path) -> None:
    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_openclaw_invalid",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        executor=InvalidConfigExecutor(),
        runtime_root=tmp_path / "runtime-invalid",
    )

    evidence = parse_openclaw_run_evidence(artifact.runner_metadata)
    assert artifact.status.value == "invalid"
    assert artifact.error is not None
    assert artifact.error.code == "openclaw_config_invalid"
    assert evidence is not None
    assert evidence.generated_openclaw_config is not None
    assert evidence.workspace_snapshot is not None
    assert evidence.workspace_diff is not None
    assert artifact.output_artifacts == []


def _write_openclaw_case(tmp_path: Path) -> CaseConfig:
    case_path = tmp_path / "test.yaml"
    case_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: openclaw_case",
                "title: OpenClaw case",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: system",
                "      content: You are careful.",
                "    - role: user",
                "      content: Produce report.md in the workspace.",
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return load_test_config(case_path)
