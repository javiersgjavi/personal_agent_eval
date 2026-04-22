from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers.docker_subprocess_stub import patch_openclaw_docker_run
from personal_agent_eval.artifacts import parse_openclaw_run_evidence
from personal_agent_eval.artifacts.run_artifact import FinalOutputTraceEvent
from personal_agent_eval.config import load_openclaw_agent, load_run_profile, load_test_config
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import TestConfig as CaseConfig
from personal_agent_eval.domains.openclaw import run_openclaw_case

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_run_openclaw_case_success_captures_external_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_openclaw_docker_run(monkeypatch)
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
        raw_trace_path.read_text(encoding="utf-8").strip() == '{"content": "Generated report.md"}'
    )
    assert "run_agent" in log_path.read_text(encoding="utf-8")
    assert "report.md" in diff_path.read_text(encoding="utf-8")
    assert key_output_path.read_text(encoding="utf-8").startswith("# Report")
    assert artifact.trace[-1].event_type == "final_output"
    oc_meta = artifact.request.metadata.get("openclaw") if artifact.request.metadata else None
    assert isinstance(oc_meta, dict)
    assert oc_meta.get("execution") == "docker"
    assert oc_meta.get("docker_cli") == "docker"


def test_run_openclaw_case_invalid_config_still_records_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_openclaw_docker_run(monkeypatch, validation_ok=False)
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


def test_run_openclaw_case_uses_docker_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        if "validate" in argv:
            return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")
        return SimpleNamespace(returncode=0, stdout='{"content": "stub"}', stderr="")

    monkeypatch.setattr("personal_agent_eval.domains.openclaw.runner.subprocess.run", fake_run)

    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    run_openclaw_case(
        run_id="run_docker_default",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        runtime_root=tmp_path / "runtime-docker",
    )

    assert len(calls) >= 2
    assert calls[0][0] == "docker"
    assert "run" in calls[0]
    assert "ghcr.io/openclaw/openclaw:2026.4.15" in calls[0]
    assert "--env-file" in calls[0]
    env_file = Path(calls[0][calls[0].index("--env-file") + 1])
    assert "OPENCLAW_CONFIG_PATH=/work/openclaw.json" in env_file.read_text(encoding="utf-8")
    generated = (tmp_path / "runtime-docker" / "openclaw.json").read_text(encoding="utf-8")
    assert '"/work/workspace"' in generated


def test_run_openclaw_case_extracts_final_output_from_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        if "validate" in argv:
            return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr='{"content": "from-stderr"}')

    monkeypatch.setattr("personal_agent_eval.domains.openclaw.runner.subprocess.run", fake_run)

    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_stderr_output",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        runtime_root=tmp_path / "runtime-stderr",
    )

    assert artifact.trace[-1].event_type == "final_output"
    assert isinstance(artifact.trace[-1], FinalOutputTraceEvent)
    assert artifact.trace[-1].content == "from-stderr"


def test_run_openclaw_case_persists_observable_summary_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        "[tools] browser failed: gateway closed\n"
        'Bind: loopback raw_params={"action":"open","url":"https://www.python.org/downloads/"}\n'
        "{"
        '"payloads":[{"text":"Consulta completada en python.org/downloads/"}],'
        '"finalAssistantVisibleText":"Consulta completada en python.org/downloads/",'
        '"meta":{"toolSummary":{"calls":2,"tools":["web_search","write"],"failures":0}}'
        "}"
    )
    patch_openclaw_docker_run(monkeypatch, run_stdout=payload)

    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_observable_summary",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        runtime_root=tmp_path / "runtime-observable",
    )

    evidence = parse_openclaw_run_evidence(artifact.runner_metadata)
    assert evidence is not None
    observable_summary = evidence.metadata.get("observable_summary")
    assert isinstance(observable_summary, dict)
    assert observable_summary["final_assistant_visible_text"].startswith("Consulta completada")
    assert observable_summary["tool_summary"]["tools"] == ["web_search", "write"]


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
