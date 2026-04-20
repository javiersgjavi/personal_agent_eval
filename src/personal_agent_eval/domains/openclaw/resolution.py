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


def openrouter_primary_model_ref(raw_model: str) -> str:
    """Map a suite model slug to an OpenClaw OpenRouter ref ``openrouter/<provider>/<model>``."""
    stripped = raw_model.strip()
    if not stripped:
        return raw_model
    if stripped.startswith("openrouter/"):
        return stripped
    return f"openrouter/{stripped}"


class ResolvedOpenClawMessage(ArtifactModel):
    """Resolved case message content used by an OpenClaw run."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratedOpenClawAgents(ArtifactModel):
    """Minimal generated OpenClaw ``agents`` block for rendered config."""

    defaults: dict[str, Any] = Field(default_factory=dict)
    agent_list: list[dict[str, Any]] = Field(default_factory=list)

    def to_json_dict(self, *, round_floats: bool = True) -> dict[str, Any]:
        return {
            "defaults": dict(self.defaults),
            "list": list(self.agent_list),
        }


class GeneratedOpenClawConfig(ArtifactModel):
    """Generated ``openclaw.json`` matching OpenClaw's strict root schema (agents-only root)."""

    agents: GeneratedOpenClawAgents

    def to_json_dict(self, *, round_floats: bool = True) -> dict[str, Any]:
        return {"agents": self.agents.to_json_dict(round_floats=round_floats)}


class ResolvedOpenClawConfig(ArtifactModel):
    """Internal resolved OpenClaw config before writing openclaw.json."""

    agent_id: str
    requested_model: str
    openclaw_primary_model_ref: str
    openclaw_workspace_path_in_config: str
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
    workspace_path_in_openclaw_config: str | None = None,
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

    workspace_dir_resolved = workspace_dir.expanduser().resolve()
    openclaw_workspace_path_in_config = (
        workspace_path_in_openclaw_config
        if workspace_path_in_openclaw_config is not None
        else str(workspace_dir_resolved)
    )

    raw_requested = _resolve_requested_model(model_selection)
    primary_ref = openrouter_primary_model_ref(raw_requested)

    return ResolvedOpenClawConfig(
        agent_id=agent_config.agent_id,
        requested_model=raw_requested,
        openclaw_primary_model_ref=primary_ref,
        openclaw_workspace_path_in_config=openclaw_workspace_path_in_config,
        container_image=run_profile.openclaw.image,
        timeout_seconds=run_profile.openclaw.timeout_seconds,
        workspace_template_dir=agent_config.workspace_dir,
        workspace_dir=workspace_dir_resolved,
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
    primary = resolved_config.openclaw_primary_model_ref
    agent_entry = _build_openclaw_agent_list_entry(
        fragment=dict(resolved_config.agent_fragment),
        directory_agent_id=resolved_config.agent_id,
        primary_model=primary,
    )

    agents_defaults = dict(resolved_config.agents_defaults_fragment)
    _normalize_legacy_agents_defaults(agents_defaults)
    agents_defaults["workspace"] = resolved_config.openclaw_workspace_path_in_config

    models_fragment = _openrouter_normalize_models_fragment(
        dict(resolved_config.model_defaults_fragment)
    )
    fallbacks = models_fragment.pop("fallbacks", None)
    aliases = models_fragment.pop("aliases", None)

    model_block: dict[str, Any] = {"primary": primary}
    if isinstance(fallbacks, list) and fallbacks:
        model_block["fallbacks"] = list(fallbacks)
    agents_defaults["model"] = model_block
    agents_defaults["models"] = _build_agents_defaults_models_catalog(
        primary=primary,
        fallbacks=fallbacks if isinstance(fallbacks, list) else [],
        aliases=aliases,
    )

    generated = GeneratedOpenClawConfig(
        agents=GeneratedOpenClawAgents(defaults=agents_defaults, agent_list=[agent_entry]),
    )
    validate_generated_openclaw_config(generated)
    return generated


def _build_openclaw_agent_list_entry(
    *,
    fragment: dict[str, Any],
    directory_agent_id: str,
    primary_model: str,
) -> dict[str, Any]:
    """Build ``agents.list[]`` entry; map legacy ``prompt`` to ``systemPromptOverride``."""
    entry = dict(fragment)
    entry.setdefault("id", directory_agent_id)
    if "prompt" in entry:
        entry["systemPromptOverride"] = entry.pop("prompt")
    entry["model"] = primary_model
    return entry


def _normalize_legacy_agents_defaults(agents_defaults: dict[str, Any]) -> None:
    """Coerce pre-strict-schema shortcuts (e.g. string sandbox) to valid objects."""
    sandbox = agents_defaults.get("sandbox")
    if isinstance(sandbox, str):
        # Legacy YAML used string presets; strict schema expects an object. Full workspace access.
        agents_defaults["sandbox"] = {"mode": "off"}


def _build_agents_defaults_models_catalog(
    *,
    primary: str,
    fallbacks: list[Any],
    aliases: Any,
) -> dict[str, Any]:
    """Build ``agents.defaults.models`` allowlist map per OpenClaw docs."""
    catalog: dict[str, Any] = {}
    alias_label = "default"
    if isinstance(aliases, Mapping):
        for _slot, label in aliases.items():
            if isinstance(label, str) and label.strip():
                alias_label = label.strip()
                break
    catalog[primary] = {"alias": alias_label}
    for fb in fallbacks:
        if isinstance(fb, str) and fb.strip() and fb not in catalog:
            catalog[fb] = {}
    return catalog


def _openrouter_normalize_models_fragment(fragment: dict[str, Any]) -> dict[str, Any]:
    out = dict(fragment)
    fallbacks = out.get("fallbacks")
    if isinstance(fallbacks, list):
        out["fallbacks"] = [
            openrouter_primary_model_ref(item) if isinstance(item, str) else item
            for item in fallbacks
        ]
    return out


def render_openclaw_json_text(resolved_config: ResolvedOpenClawConfig) -> str:
    """Return a stable JSON representation of the generated OpenClaw config."""
    payload = render_openclaw_json(resolved_config).to_json_dict()
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def validate_generated_openclaw_config(
    payload: GeneratedOpenClawConfig | Mapping[str, Any],
) -> GeneratedOpenClawConfig:
    """Validate the minimal generated ``openclaw.json`` shape from the harness."""
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
    list_model = agent_entry.get("model")
    if not isinstance(list_model, str) or not list_model.strip():
        raise ValueError("Generated OpenClaw agent entry requires a non-empty primary model.")
    model_block = generated.agents.defaults.get("model")
    if not isinstance(model_block, Mapping):
        raise ValueError("Generated OpenClaw config requires agents.defaults.model mapping.")
    primary_model = model_block.get("primary")
    if primary_model != list_model:
        raise ValueError(
            "Generated OpenClaw config requires agents.defaults.model.primary to match "
            "agents.list[0].model."
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
    return GeneratedOpenClawConfig.model_validate({"agents": normalized_agents})
