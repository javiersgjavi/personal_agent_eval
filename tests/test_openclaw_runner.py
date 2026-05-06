from __future__ import annotations

import json
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
    assert artifact.output_artifacts[0].metadata == {"workspace_relative_path": "report.md"}
    assert evidence.key_output_artifacts[0].metadata == {"workspace_relative_path": "report.md"}

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


def test_run_openclaw_case_extracts_usage_and_estimates_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.dumps(
        {
            "content": "done",
            "meta": {
                "agentMeta": {
                    "usage": {
                        "input": 1_000_000,
                        "output": 100_000,
                        "cacheRead": 500_000,
                        "cacheWrite": 200_000,
                        "total": 1_800_000,
                    }
                }
            },
        }
    )
    patch_openclaw_docker_run(monkeypatch, run_stdout=payload)

    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_usage",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "sonnet", "requested_model": "anthropic/claude-sonnet-4.6"}
        ),
        agent_config=agent_config,
        runtime_root=tmp_path / "runtime-usage",
    )

    assert artifact.usage.normalized.input_tokens == 1_000_000
    assert artifact.usage.normalized.output_tokens == 100_000
    assert artifact.usage.normalized.cached_input_tokens == 500_000
    assert artifact.usage.normalized.cache_write_tokens == 200_000
    assert artifact.usage.cost_usd == pytest.approx(5.4)


def test_run_openclaw_case_runs_turns_in_one_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        _ = kwargs
        calls.append(list(argv))
        if "validate" in argv:
            return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")
        turn_number = len([call for call in calls if "agent" in call and "--message" in call])
        if turn_number == 2:
            host_root = _host_root_from_argv(argv)
            report = host_root / "workspace" / "report.md"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("# Report\n\nrevised\n", encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout=f'{{"content": "turn {turn_number} complete"}}',
            stderr="",
        )

    monkeypatch.setattr("personal_agent_eval.domains.openclaw.runner.subprocess.run", fake_run)

    case_config = _write_openclaw_multiturn_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_openclaw_multiturn",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        runtime_root=tmp_path / "runtime-multiturn",
    )

    evidence = parse_openclaw_run_evidence(artifact.runner_metadata)
    assert artifact.status.value == "success"
    agent_calls = [call for call in calls if "agent" in call and "--message" in call]
    assert len(agent_calls) == 2
    session_ids = [call[call.index("--session-id") + 1] for call in agent_calls]
    assert session_ids[0] == session_ids[1]
    assert "Create draft.md." in agent_calls[0][agent_calls[0].index("--message") + 1]
    assert "Revise draft.md" in agent_calls[1][agent_calls[1].index("--message") + 1]
    assert "Keep context across turns." in agent_calls[0][agent_calls[0].index("--message") + 1]
    assert "Keep context across turns." not in agent_calls[1][agent_calls[1].index("--message") + 1]
    assert evidence is not None
    assert evidence.raw_session_trace is not None
    raw_trace_path = Path(evidence.raw_session_trace.uri.removeprefix("file://"))
    raw_trace = json.loads(raw_trace_path.read_text(encoding="utf-8"))
    assert [turn["turn_index"] for turn in raw_trace["turns"]] == [1, 2]
    final_outputs = [
        event.content for event in artifact.trace if isinstance(event, FinalOutputTraceEvent)
    ]
    assert final_outputs == ["turn 1 complete", "turn 2 complete"]


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


def _write_openclaw_multiturn_case(tmp_path: Path) -> CaseConfig:
    case_path = tmp_path / "test-multiturn.yaml"
    case_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: openclaw_multiturn_case",
                "title: OpenClaw multiturn case",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: system",
                "      content: Keep context across turns.",
                "  turns:",
                "    - role: user",
                "      content: Create draft.md.",
                "    - role: user",
                "      content: Revise draft.md and create report.md.",
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return load_test_config(case_path)


def _host_root_from_argv(argv: list[str]) -> Path:
    volume_spec = argv[argv.index("-v") + 1]
    return Path(volume_spec.split(":", 2)[0])


def test_workspace_snapshot_excludes_venvs_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tarfile as _tarfile

    from personal_agent_eval.domains.openclaw.runner import (
        _is_excluded_workspace_path,
        _write_workspace_artifacts,
    )

    workspace = tmp_path / "workspace"
    template = tmp_path / "template"
    for d in (workspace, template):
        d.mkdir()
        (d / "main.md").write_text("content", encoding="utf-8")

    (workspace / ".venvs").mkdir()
    (workspace / ".venvs" / "lib").mkdir()
    (workspace / ".venvs" / "lib" / "heavy.so").write_bytes(b"\x00" * 1024)
    (workspace / ".venv-custom").mkdir()
    (workspace / ".venv-custom" / "pyvenv.cfg").write_text("home = /usr", encoding="utf-8")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "mod.pyc").write_bytes(b"\x00" * 64)
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "pkg").mkdir()
    (workspace / "node_modules" / "pkg" / "index.js").write_text(
        "module.exports={}", encoding="utf-8"
    )
    (workspace / "subdir").mkdir()
    (workspace / "subdir" / "__pycache__").mkdir()
    (workspace / "subdir" / "__pycache__" / "nested.pyc").write_bytes(b"\x00" * 32)
    (workspace / "subdir" / "keep.txt").write_text("kept", encoding="utf-8")
    (workspace / "tts").mkdir()
    (workspace / "tts" / "audio.mp3").write_bytes(b"\x00" * 1024)
    (workspace / "downloads").mkdir()
    (workspace / "downloads" / "file.pdf").write_bytes(b"\x00" * 1024)
    (workspace / "tmp").mkdir()
    (workspace / "tmp" / "scratch.bin").write_bytes(b"\x00" * 64)

    snapshot = tmp_path / "snapshot.tar.gz"
    diff = tmp_path / "diff.txt"
    _write_workspace_artifacts(
        template_dir=template,
        workspace_dir=workspace,
        snapshot_path=snapshot,
        diff_path=diff,
    )

    with _tarfile.open(snapshot, "r:gz") as archive:
        names = {m.name for m in archive.getmembers()}

    assert "workspace/main.md" in names
    assert "workspace/subdir/keep.txt" in names
    assert not any(".venvs" in n for n in names)
    assert not any(".venv-custom" in n for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any(".git" in n for n in names)
    assert not any("node_modules" in n for n in names)
    assert not any("/tts/" in n or n.endswith("/tts") for n in names)
    assert not any("/downloads/" in n or n.endswith("/downloads") for n in names)
    assert not any("/tmp/" in n or n.endswith("/tmp") for n in names)

    assert not _is_excluded_workspace_path(workspace / "main.md", workspace)
    assert _is_excluded_workspace_path(workspace / ".venvs" / "lib" / "heavy.so", workspace)
    assert _is_excluded_workspace_path(workspace / ".venv-custom" / "pyvenv.cfg", workspace)
    assert _is_excluded_workspace_path(workspace / "__pycache__" / "mod.pyc", workspace)
    assert _is_excluded_workspace_path(workspace / ".git" / "HEAD", workspace)
    assert _is_excluded_workspace_path(workspace / "node_modules" / "pkg" / "index.js", workspace)
    assert _is_excluded_workspace_path(
        workspace / "subdir" / "__pycache__" / "nested.pyc", workspace
    )
    assert not _is_excluded_workspace_path(workspace / "subdir" / "keep.txt", workspace)
    assert _is_excluded_workspace_path(workspace / "tts" / "audio.mp3", workspace)
    assert _is_excluded_workspace_path(workspace / "downloads" / "file.pdf", workspace)
    assert _is_excluded_workspace_path(workspace / "tmp" / "scratch.bin", workspace)

    diff_text = diff.read_text(encoding="utf-8")
    assert not any(
        skip in diff_text
        for skip in (
            ".venvs",
            ".venv-custom",
            "__pycache__",
            ".git",
            "node_modules",
            "/tts/",
            "/downloads/",
            "/tmp/",
        )
    )
