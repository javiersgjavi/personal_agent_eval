"""OpenClaw effective config resolution and deterministic openclaw.json rendering."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import Field

from personal_agent_eval.artifacts.run_artifact import ArtifactModel
from personal_agent_eval.config import OpenClawAgentConfig, RunProfileConfig, TestConfig
from personal_agent_eval.config.suite_config import ModelConfig

_OPENCLAW_MESSAGE_ROLES = {"system", "user", "assistant", "tool"}


class ResolvedOpenClawMessage(ArtifactModel):
    """Resolved case message content used by an OpenClaw run."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratedOpenClawAgents(ArtifactModel):
    """Minimal generated OpenClaw agent block for V2."""

    defaults: dict[str, Any] = Field(default_factory=dict)
    agent_list: list[dict[str, Any]] = Field(default_factory=list)

    def to_json_dict(self, *, round_floats: bool = True) -> dict[str, Any]:
        return {
            "defaults": dict(self.defaults),
            "list": list(self.agent_list),
        }


class GeneratedOpenClawConfig(ArtifactModel):
    """Minimal generated openclaw.json contract for the first harness."""

    identity: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, Any] = Field(default_factory=dict)
    agents: GeneratedOpenClawAgents

    def to_json_dict(self, *, round_floats: bool = True) -> dict[str, Any]:
        return {
            "identity": dict(self.identity),
            "models": dict(self.models),
            "agents": self.agents.to_json_dict(round_floats=round_floats),
        }


class ResolvedOpenClawConfig(ArtifactModel):
    """Internal resolved OpenClaw config before writing openclaw.json."""

    agent_id: str
    requested_model: str
    container_image: str
    timeout_seconds: int = Field(gt=0)
    workspace_template_dir: Path
    workspace_dir: Path
    state_dir: Path
    case_id: str
    case_messages: list[ResolvedOpenClawMessage] = Field(default_factory=list)
    case_attachments: list[Path] = Field(default_factory=list)
    case_openclaw_hints: dict[str, Any] = Field(default_factory=dict)
    identity_fragment: dict[str, Any] = Field(default_factory=dict)
    agents_defaults_fragment: dict[str, Any] = Field(default_factory=dict)
    agent_fragment: dict[str, Any] = Field(default_factory=dict)
    model_defaults_fragment: dict[str, Any] = Field(default_factory=dict)


def resolve_openclaw_config(
    *,
    case_config: TestConfig,
    run_profile: RunProfileConfig,
    model_selection: ModelConfig,
    agent_config: OpenClawAgentConfig,
    workspace_dir: Path,
    state_dir: Path,
) -> ResolvedOpenClawConfig:
    """Resolve the effective OpenClaw execution config for one run."""
    if case_config.runner.type != "openclaw":
        raise ValueError("resolve_openclaw_config() requires a case with runner.type='openclaw'.")
    if run_profile.openclaw is None:
        raise ValueError(
            "resolve_openclaw_config() requires run_profile.openclaw to be configured."
        )
    if run_profile.openclaw.agent_id != agent_config.agent_id:
        raise ValueError(
            "run_profile.openclaw.agent_id must match the loaded OpenClaw agent definition."
        )
    if agent_config.workspace_dir is None:
        raise ValueError("OpenClaw agent config must include a resolved workspace_dir.")

    return ResolvedOpenClawConfig(
        agent_id=agent_config.agent_id,
        requested_model=_resolve_requested_model(model_selection),
        container_image=run_profile.openclaw.image,
        timeout_seconds=run_profile.openclaw.timeout_seconds,
        workspace_template_dir=agent_config.workspace_dir,
        workspace_dir=workspace_dir.expanduser().resolve(),
        state_dir=state_dir.expanduser().resolve(),
        case_id=case_config.case_id,
        case_messages=_resolve_case_messages(case_config),
        case_attachments=list(case_config.input.attachments),
        case_openclaw_hints=_resolve_case_openclaw_hints(case_config),
        identity_fragment=dict(agent_config.openclaw.identity or {}),
        agents_defaults_fragment=dict(agent_config.openclaw.agents_defaults or {}),
        agent_fragment=dict(agent_config.openclaw.agent or {}),
        model_defaults_fragment=_resolve_model_defaults_fragment(agent_config),
    )


def render_openclaw_json(resolved_config: ResolvedOpenClawConfig) -> GeneratedOpenClawConfig:
    """Render the deterministic openclaw.json payload for ``resolved_config``."""
    agent_entry = dict(resolved_config.agent_fragment)
    agent_entry.setdefault("id", resolved_config.agent_id)
    agent_entry["model"] = resolved_config.requested_model

    agents_defaults = dict(resolved_config.agents_defaults_fragment)
    agents_defaults["workspace"] = str(resolved_config.workspace_dir)

    generated = GeneratedOpenClawConfig(
        identity=dict(resolved_config.identity_fragment),
        models={
            "default": resolved_config.requested_model,
            **resolved_config.model_defaults_fragment,
        },
        agents=GeneratedOpenClawAgents(defaults=agents_defaults, agent_list=[agent_entry]),
    )
    validate_generated_openclaw_config(generated)
    return generated


def render_openclaw_json_text(resolved_config: ResolvedOpenClawConfig) -> str:
    """Return a stable JSON representation of the generated OpenClaw config."""
    payload = render_openclaw_json(resolved_config).to_json_dict()
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def validate_generated_openclaw_config(
    payload: GeneratedOpenClawConfig | Mapping[str, Any],
) -> GeneratedOpenClawConfig:
    """Validate the minimal generated openclaw.json payload used by V2."""
    generated = (
        payload
        if isinstance(payload, GeneratedOpenClawConfig)
        else _coerce_generated_payload(payload)
    )
    workspace = generated.agents.defaults.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError(
            "Generated OpenClaw config requires a non-empty agents.defaults.workspace."
        )
    if len(generated.agents.agent_list) != 1:
        raise ValueError("Generated OpenClaw config currently supports exactly one agent entry.")
    agent_entry = generated.agents.agent_list[0]
    model = agent_entry.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Generated OpenClaw agent entry requires a non-empty primary model.")
    default_model = generated.models.get("default")
    if default_model != model:
        raise ValueError(
            "Generated OpenClaw config requires models.default to match agents.list[0].model."
        )
    return generated


def _resolve_requested_model(model_selection: ModelConfig) -> str:
    payload = model_selection.model_dump(mode="json")
    requested_model = payload.get("requested_model")
    if isinstance(requested_model, str) and requested_model:
        return requested_model

    openrouter_model = payload.get("openrouter_model")
    if isinstance(openrouter_model, str) and openrouter_model:
        return openrouter_model

    model_name = payload.get("model_name")
    provider = payload.get("provider")
    if isinstance(model_name, str) and model_name:
        if "/" in model_name:
            return model_name
        if isinstance(provider, str) and provider:
            return f"{provider}/{model_name}"
        return model_name

    return model_selection.model_id


def _resolve_case_openclaw_hints(case_config: TestConfig) -> dict[str, Any]:
    hints = case_config.input.context.get("openclaw")
    if hints is None:
        return {}
    if not isinstance(hints, Mapping):
        raise ValueError("input.context.openclaw must be a mapping when provided.")
    return dict(hints)


def _resolve_case_messages(case_config: TestConfig) -> list[ResolvedOpenClawMessage]:
    resolved: list[ResolvedOpenClawMessage] = []
    for message in case_config.input.messages:
        if message.source is None:
            resolved.append(
                ResolvedOpenClawMessage(
                    role=message.role,
                    content=message.content,
                    name=message.name,
                )
            )
            continue
        resolved.extend(
            _load_source_messages(
                message.source.path,
                fallback_role=message.role,
                name=message.name,
            )
        )
    return resolved


def _load_source_messages(
    path: Path,
    *,
    fallback_role: Literal["system", "user", "assistant", "tool"],
    name: str | None,
) -> list[ResolvedOpenClawMessage]:
    raw_content = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        loaded = json.loads(raw_content)
    else:
        loaded = yaml.safe_load(raw_content)

    if isinstance(loaded, str):
        return [ResolvedOpenClawMessage(role=fallback_role, content=loaded, name=name)]
    if isinstance(loaded, Mapping):
        return [
            _resolved_message_from_mapping(
                loaded,
                fallback_role=fallback_role,
                fallback_name=name,
            )
        ]
    if isinstance(loaded, list):
        resolved_messages: list[ResolvedOpenClawMessage] = []
        for item in loaded:
            if not isinstance(item, Mapping):
                raise ValueError(f"Message source '{path}' must contain only mapping entries.")
            resolved_messages.append(
                _resolved_message_from_mapping(
                    item,
                    fallback_role=fallback_role,
                    fallback_name=name,
                )
            )
        return resolved_messages
    raise ValueError(
        f"Message source '{path}' must contain a string, mapping, or list of mappings."
    )


def _resolved_message_from_mapping(
    payload: Mapping[str, Any],
    *,
    fallback_role: Literal["system", "user", "assistant", "tool"],
    fallback_name: str | None,
) -> ResolvedOpenClawMessage:
    role_value = payload.get("role", fallback_role)
    content_value = payload.get("content")
    name_value = payload.get("name", fallback_name)
    if not isinstance(role_value, str):
        raise ValueError("Resolved OpenClaw message role must be a string.")
    if role_value not in _OPENCLAW_MESSAGE_ROLES:
        raise ValueError(f"Unsupported OpenClaw message role '{role_value}'.")
    if content_value is not None and not isinstance(content_value, str):
        raise ValueError("Resolved OpenClaw message content must be a string when provided.")
    if name_value is not None and not isinstance(name_value, str):
        raise ValueError("Resolved OpenClaw message name must be a string when provided.")
    metadata = {
        key: value for key, value in payload.items() if key not in {"role", "content", "name"}
    }
    return ResolvedOpenClawMessage(
        role=cast(Literal["system", "user", "assistant", "tool"], role_value),
        content=content_value,
        name=name_value,
        metadata=metadata,
    )


def _resolve_model_defaults_fragment(agent_config: OpenClawAgentConfig) -> dict[str, Any]:
    model_defaults = agent_config.openclaw.model_defaults
    if model_defaults is None:
        return {}
    payload = model_defaults.model_dump(mode="json")
    extras = model_defaults.model_extra or {}
    return {**payload, **extras}


def _coerce_generated_payload(payload: Mapping[str, Any]) -> GeneratedOpenClawConfig:
    agents = payload.get("agents", {})
    if not isinstance(agents, Mapping):
        raise ValueError("Generated OpenClaw config requires an 'agents' mapping.")
    normalized_agents = {
        "defaults": agents.get("defaults", {}),
        "agent_list": agents.get("list", []),
    }
    return GeneratedOpenClawConfig.model_validate(
        {
            "identity": payload.get("identity", {}),
            "models": payload.get("models", {}),
            "agents": normalized_agents,
        }
    )
