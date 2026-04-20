from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent_eval.config import (
    load_openclaw_agent,
    load_run_profile,
    load_test_config,
)
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import TestConfig as CaseConfig
from personal_agent_eval.domains.openclaw import (
    normalize_openrouter_base_url,
    openrouter_primary_model_ref,
    render_openclaw_json,
    render_openclaw_json_text,
    resolve_openclaw_config,
    validate_generated_openclaw_config,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_resolve_openclaw_config_keeps_paths_and_case_hints_separate(tmp_path: Path) -> None:
    case_config = _write_openclaw_case(tmp_path, source_messages=True)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")

    resolved = resolve_openclaw_config(
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        workspace_dir=tmp_path / "ephemeral-workspace",
        state_dir=tmp_path / "ephemeral-state",
    )

    assert resolved.agent_id == "support_agent"
    assert resolved.requested_model == "openai/gpt-4o-mini"
    assert resolved.openclaw_primary_model_ref == "openrouter/openai/gpt-4o-mini"
    assert (
        resolved.workspace_template_dir
        == (FIXTURES_ROOT / "configs" / "agents" / "support_agent" / "workspace").resolve()
    )
    assert resolved.workspace_dir == (tmp_path / "ephemeral-workspace").resolve()
    assert resolved.openclaw_workspace_path_in_config == str(
        (tmp_path / "ephemeral-workspace").resolve()
    )
    assert resolved.state_dir == (tmp_path / "ephemeral-state").resolve()
    assert resolved.case_openclaw_hints == {
        "expected_artifact": "report.md",
        "task_mode": "patch_existing_file",
    }
    assert [message.role for message in resolved.case_messages] == ["system", "user"]
    assert resolved.case_messages[1].metadata == {"priority": "high"}


def test_render_openclaw_json_minimax_slug_uses_openrouter_ref(tmp_path: Path) -> None:
    case_config = _write_openclaw_case(tmp_path, source_messages=False)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    resolved = resolve_openclaw_config(
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "minimax_m27", "requested_model": "minimax/minimax-m2.7"}
        ),
        agent_config=agent_config,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
    )
    assert resolved.openclaw_primary_model_ref == "openrouter/minimax/minimax-m2.7"
    generated = render_openclaw_json(resolved)
    assert generated.agents.defaults["model"]["primary"] == "openrouter/minimax/minimax-m2.7"
    assert generated.agents.defaults["model"] == {"primary": "openrouter/minimax/minimax-m2.7"}
    assert generated.agents.defaults["models"]["openrouter/minimax/minimax-m2.7"]["alias"] == (
        "benchmark-primary"
    )
    openrouter = generated.models["providers"]["openrouter"]
    assert openrouter["baseUrl"] == "https://openrouter.ai/api/v1"
    assert openrouter["apiKey"] == "OPENROUTER_API_KEY"
    assert [model["id"] for model in openrouter["models"]] == ["minimax/minimax-m2.7"]


def test_render_openclaw_json_is_deterministic_and_uses_requested_model(tmp_path: Path) -> None:
    case_config = _write_openclaw_case(tmp_path, source_messages=False)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    resolved = resolve_openclaw_config(
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "provider": "openai", "model_name": "gpt-4.1-mini"}
        ),
        agent_config=agent_config,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
    )

    generated = render_openclaw_json(resolved)
    rendered_text = render_openclaw_json_text(resolved)
    or_primary = "openrouter/openai/gpt-4.1-mini"

    assert generated.agents.defaults["model"]["primary"] == or_primary
    assert generated.agents.defaults["models"][or_primary] == {
        "alias": "benchmark-primary",
        "params": {"max_tokens": 8192},
    }
    assert generated.agents.defaults["workspace"] == str((tmp_path / "workspace").resolve())
    assert generated.agents.defaults["sandbox"] == {"mode": "off"}
    assert generated.agents.defaults["model"] == {"primary": or_primary}
    assert generated.models["providers"]["openrouter"]["baseUrl"] == (
        "https://openrouter.ai/api/v1"
    )
    assert generated.agents.agent_list == [
        {
            "id": "support-agent",
            "systemPromptOverride": "You are a benchmark fixture agent.",
            "model": or_primary,
        }
    ]
    assert "ephemeral-state" not in rendered_text
    assert f'"primary": "{or_primary}"' in rendered_text
    assert '"baseUrl": "https://openrouter.ai/api/v1"' in rendered_text
    assert rendered_text == render_openclaw_json_text(resolved)


def test_render_openclaw_json_does_not_merge_case_hints_into_generated_payload(
    tmp_path: Path,
) -> None:
    case_config = _write_openclaw_case(tmp_path, source_messages=False)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    resolved = resolve_openclaw_config(
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
    )

    generated = render_openclaw_json(resolved).to_json_dict()

    assert "expected_artifact" not in str(generated)
    assert "task_mode" not in str(generated)


def test_resolve_openclaw_config_rejects_non_mapping_case_hints(tmp_path: Path) -> None:
    path = tmp_path / "test.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: openclaw_case",
                "title: Invalid OpenClaw case",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: user",
                "      content: Hello",
                "  context:",
                "    openclaw: invalid",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    case_config = load_test_config(path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")

    with pytest.raises(ValueError, match="input.context.openclaw must be a mapping"):
        resolve_openclaw_config(
            case_config=case_config,
            run_profile=run_profile,
            model_selection=ModelConfig.model_validate({"model_id": "baseline_model"}),
            agent_config=agent_config,
            workspace_dir=tmp_path / "workspace",
            state_dir=tmp_path / "state",
        )


def test_openrouter_primary_model_ref_idempotent() -> None:
    assert openrouter_primary_model_ref("z-ai/glm-5-turbo") == "openrouter/z-ai/glm-5-turbo"
    assert openrouter_primary_model_ref("openrouter/x/y") == "openrouter/x/y"


def test_normalize_openrouter_base_url_repairs_legacy_path() -> None:
    assert normalize_openrouter_base_url("https://openrouter.ai/v1") == (
        "https://openrouter.ai/api/v1"
    )
    assert normalize_openrouter_base_url("https://openrouter.ai/api/v1") == (
        "https://openrouter.ai/api/v1"
    )


def test_resolve_openclaw_config_container_workspace_path(tmp_path: Path) -> None:
    case_config = _write_openclaw_case(tmp_path, source_messages=False)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    resolved = resolve_openclaw_config(
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate(
            {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
        ),
        agent_config=agent_config,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        workspace_path_in_openclaw_config="/work/workspace",
    )
    assert resolved.openclaw_primary_model_ref == "openrouter/openai/gpt-4o-mini"
    generated = render_openclaw_json(resolved)
    assert generated.agents.defaults["workspace"] == "/work/workspace"
    assert resolved.workspace_dir == (tmp_path / "workspace").resolve()


def test_validate_generated_openclaw_config_requires_one_agent_and_matching_default() -> None:
    with pytest.raises(ValueError, match="exactly one agent entry"):
        validate_generated_openclaw_config(
            {
                "agents": {
                    "defaults": {
                        "workspace": "/tmp/ws",
                        "model": {"primary": "openai/gpt-4o-mini"},
                    },
                    "list": [],
                },
            }
        )

    with pytest.raises(ValueError, match="agents.defaults.model.primary to match"):
        validate_generated_openclaw_config(
            {
                "agents": {
                    "defaults": {
                        "workspace": "/tmp/ws",
                        "model": {"primary": "openai/gpt-4o-mini"},
                    },
                    "list": [{"id": "agent", "model": "anthropic/claude"}],
                },
            }
        )


def _write_openclaw_case(tmp_path: Path, *, source_messages: bool) -> CaseConfig:
    if source_messages:
        (tmp_path / "messages.yaml").write_text(
            "\n".join(
                [
                    "- role: user",
                    "  content: Solve the task.",
                    "  priority: high",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        user_message = "\n".join(
            [
                "    - role: system",
                "      content: You are careful.",
                "    - role: user",
                "      source:",
                "        path: messages.yaml",
                "        format: yaml",
            ]
        )
    else:
        user_message = "\n".join(
            [
                "    - role: system",
                "      content: You are careful.",
                "    - role: user",
                "      content: Solve the task.",
            ]
        )

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
                user_message,
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
                "      task_mode: patch_existing_file",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return load_test_config(path)
