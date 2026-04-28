from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from personal_agent_eval.config import (
    ConfigError,
    load_evaluation_profile,
    load_openclaw_agent,
    load_run_profile,
    load_suite_config,
    load_test_config,
)
from personal_agent_eval.config.test_config import FileExistsCheck

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"
Loader = Callable[[Path], object]


def test_load_test_config_normalizes_paths_and_defaults() -> None:
    config = load_test_config(FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml")

    assert config.case_id == "example_case"
    assert config.tags == ["llm_probe", "smoke"]
    assert (
        config.source_path
        == (FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml").resolve()
    )
    assert config.input.messages[1].source is not None
    assert (
        config.input.messages[1].source.path
        == (FIXTURES_ROOT / "configs" / "cases" / "example_case" / "messages.yaml").resolve()
    )
    assert config.input.attachments == [
        (
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "artifacts" / "prompt.txt"
        ).resolve()
    ]
    assert config.deterministic_checks[0].declarative is not None
    assert config.deterministic_checks[0].declarative.kind == "final_response_present"
    assert config.deterministic_checks[0].dimensions == ["process"]
    assert config.deterministic_checks[1].python_hook is not None
    assert config.deterministic_checks[1].dimensions == ["task"]
    assert (
        config.deterministic_checks[1].python_hook.path
        == (
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "hooks" / "custom_check.py"
        ).resolve()
    )


def test_load_suite_config_from_fixture() -> None:
    config = load_suite_config(FIXTURES_ROOT / "configs" / "suites" / "example_suite.yaml")

    assert config.suite_id == "example_suite"
    assert config.case_selection.include_case_ids == ["example_case"]
    assert config.models[0].model_id == "baseline_model"


def test_load_suite_config_supports_openclaw_agent_assignments(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        """schema_version: 1
suite_id: multi_agent_suite
title: Multi-agent suite
models: []
openclaw:
  agent_assignments:
    - agent_id: support_agent
      case_selection:
        include_case_ids:
          - case_a
    - agent_id: tapas
      case_selection:
        include_tags:
          - tapas
        exclude_case_ids:
          - case_b
""",
        encoding="utf-8",
    )

    config = load_suite_config(path)

    assert config.openclaw.agent_assignments[0].agent_id == "support_agent"
    assert config.openclaw.agent_assignments[0].case_selection.include_case_ids == ["case_a"]
    assert config.openclaw.agent_assignments[1].agent_id == "tapas"
    assert config.openclaw.agent_assignments[1].case_selection.include_tags == ["tapas"]
    assert config.openclaw.agent_assignments[1].case_selection.exclude_case_ids == ["case_b"]


def test_load_suite_config_rejects_empty_openclaw_agent_assignment(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(
        """schema_version: 1
suite_id: broken_suite
title: Broken suite
models: []
openclaw:
  agent_assignments:
    - agent_id: support_agent
      case_selection: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="include_case_ids or include_tags"):
        load_suite_config(path)


def test_load_run_profile_from_fixture() -> None:
    config = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "default.yaml")

    assert config.run_profile_id == "default"
    assert config.execution_policy.max_concurrency == 2
    assert config.execution_policy.run_repetitions == 1
    assert config.execution_policy.fail_fast is True


def test_load_openclaw_run_profile_from_fixture() -> None:
    config = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")

    assert config.run_profile_id == "openclaw_default"
    assert config.openclaw is not None
    assert config.openclaw.agent_id == "support_agent"
    assert config.openclaw.image == "ghcr.io/openclaw/openclaw:2026.4.15"
    assert config.openclaw.timeout_seconds == 300


def test_load_openclaw_agent_from_fixture_directory() -> None:
    config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")

    assert config.agent_id == "support_agent"
    assert config.title == "Support Agent"
    assert config.tags == ["openclaw", "support"]
    assert (
        config.source_path
        == (FIXTURES_ROOT / "configs" / "agents" / "support_agent" / "agent.yaml").resolve()
    )
    assert config.agent_dir == (FIXTURES_ROOT / "configs" / "agents" / "support_agent").resolve()
    assert (
        config.workspace_dir
        == (FIXTURES_ROOT / "configs" / "agents" / "support_agent" / "workspace").resolve()
    )
    assert config.openclaw.identity == {"name": "Support Agent"}
    assert config.openclaw.model_defaults is not None
    assert config.openclaw.model_defaults.aliases == {"default": "benchmark-primary"}
    assert config.openclaw.model_defaults.fallbacks == []


def test_load_evaluation_profile_from_fixture() -> None:
    config = load_evaluation_profile(
        FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
    )

    assert config.evaluation_profile_id == "default"
    assert config.anchors.enabled is True
    assert config.judge_runs[0].repetitions == 3
    assert config.aggregation.method == "median"
    assert config.security_policy.redact_secrets is True


def test_evaluation_profile_rejects_inline_and_path_system_prompt_together(tmp_path: Path) -> None:
    path = tmp_path / "conflict.yaml"
    path.write_text(
        """schema_version: 1
evaluation_profile_id: conflict_prompt
title: Conflict
judge_system_prompt: "inline text"
judge_system_prompt_path: prompts/x.txt
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc_info:
        load_evaluation_profile(path)
    assert "only one" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    ("payload", "loader"),
    [
        (
            "\n".join(
                [
                    "schema_version: 1",
                    "case_id: Invalid ID",
                    "title: Invalid id config",
                    "runner:",
                    "  type: llm_probe",
                    "input:",
                    "  messages: []",
                ]
            ),
            load_test_config,
        ),
        (
            "\n".join(
                [
                    "schema_version: 1",
                    "suite_id: Invalid ID",
                    "title: Invalid id config",
                ]
            ),
            load_suite_config,
        ),
        (
            "\n".join(
                [
                    "schema_version: 1",
                    "run_profile_id: Invalid ID",
                    "title: Invalid id config",
                ]
            ),
            load_run_profile,
        ),
        (
            "\n".join(
                [
                    "schema_version: 1",
                    "evaluation_profile_id: Invalid ID",
                    "title: Invalid id config",
                ]
            ),
            load_evaluation_profile,
        ),
    ],
)
def test_loaders_reject_invalid_ids(tmp_path: Path, payload: str, loader: Loader) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid"):
        loader(path)


def test_test_loader_rejects_invalid_runner_type(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: valid_case",
                "title: Invalid runner",
                "runner:",
                "  type: unsupported_runner",
                "input:",
                "  messages: []",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="runner.type"):
        load_test_config(path)


def test_test_loader_accepts_openclaw_runner_context(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: openclaw_case",
                "title: OpenClaw case",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: user",
                "      content: Solve the task.",
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_test_config(path)

    assert config.runner.type == "openclaw"
    assert config.input.context == {"openclaw": {"expected_artifact": "report.md"}}


def test_test_loader_accepts_openclaw_turns(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
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
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_test_config(path)

    assert config.input.messages[0].content == "Keep context across turns."
    assert [turn.content for turn in config.input.turns] == [
        "Create draft.md.",
        "Revise draft.md and create report.md.",
    ]


def test_test_loader_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: valid_case",
                "title: Unknown field",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages: []",
                "unexpected: true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="unexpected"):
        load_test_config(path)


def test_test_loader_applies_empty_defaults(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: defaults_case",
                "title: Defaults case",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages: []",
            ]
        ),
        encoding="utf-8",
    )

    config = load_test_config(path)

    assert config.expectations.hard_expectations == []
    assert config.expectations.soft_expectations == []
    assert config.deterministic_checks == []
    assert config.tags == []
    assert config.metadata == {}


def test_test_loader_requires_message_content_or_source(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: bad_message_case",
                "title: Bad message",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages:",
                "    - role: user",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="requires either inline 'content' or a 'source'"):
        load_test_config(path)


def test_test_loader_requires_hook_path_or_import(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: bad_hook_case",
                "title: Bad hook",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages: []",
                "deterministic_checks:",
                "  - check_id: hook_check",
                "    python_hook:",
                "      callable_name: run_check",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="requires either 'import_path' or 'path'"):
        load_test_config(path)


def test_test_loader_resolves_declarative_check_paths(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    (tmp_path / "outputs").mkdir()
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: path_case",
                "title: Path case",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages: []",
                "deterministic_checks:",
                "  - check_id: output_file",
                "    declarative:",
                "      kind: file_exists",
                "      path: outputs/result.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_test_config(path)
    declarative = config.deterministic_checks[0].declarative

    assert isinstance(declarative, FileExistsCheck)
    assert declarative.path == (tmp_path / "outputs" / "result.txt").resolve()


def test_test_loader_requires_output_artifact_matcher(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: artifact_case",
                "title: Artifact case",
                "runner:",
                "  type: llm_probe",
                "input:",
                "  messages: []",
                "deterministic_checks:",
                "  - check_id: missing_matcher",
                "    declarative:",
                "      kind: output_artifact_present",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="requires at least one matcher field"):
        load_test_config(path)


def test_yaml_loader_requires_mapping(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text("- not-a-mapping\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="top-level mapping"):
        load_suite_config(path)


def test_load_openclaw_agent_rejects_mismatched_directory_name(tmp_path: Path) -> None:
    agent_dir = tmp_path / "wrong_dir"
    workspace_dir = agent_dir / "workspace"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "AGENTS.md").write_text("placeholder\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "agent_id: support_agent",
                "title: Support agent",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="must match directory name"):
        load_openclaw_agent(agent_dir)


def test_load_openclaw_agent_requires_workspace_directory(tmp_path: Path) -> None:
    agent_dir = tmp_path / "support_agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "agent_id: support_agent",
                "title: Support agent",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="missing workspace directory"):
        load_openclaw_agent(agent_dir)


def test_load_openclaw_agent_rejects_primary_model_override(tmp_path: Path) -> None:
    agent_dir = tmp_path / "support_agent"
    workspace_dir = agent_dir / "workspace"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "AGENTS.md").write_text("placeholder\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "agent_id: support_agent",
                "title: Support agent",
                "openclaw:",
                "  agent:",
                "    model: forbidden/model",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="primary benchmark model"):
        load_openclaw_agent(agent_dir)


def test_load_openclaw_agent_rejects_fallbacks(tmp_path: Path) -> None:
    agent_dir = tmp_path / "support_agent"
    workspace_dir = agent_dir / "workspace"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "AGENTS.md").write_text("placeholder\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "agent_id: support_agent",
                "title: Support agent",
                "openclaw:",
                "  model_defaults:",
                "    fallbacks:",
                "      - openai/gpt-4o-mini",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="fallbacks is not supported"):
        load_openclaw_agent(agent_dir)


def test_load_run_profile_rejects_invalid_openclaw_block(tmp_path: Path) -> None:
    path = tmp_path / "run_profile.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "run_profile_id: openclaw_profile",
                "title: Invalid OpenClaw profile",
                "openclaw:",
                "  agent_id: support_agent",
                "  image: '   '",
                "  timeout_seconds: 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Invalid run profile"):
        load_run_profile(path)
