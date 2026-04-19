"""OpenClaw agent config schema and loader."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from personal_agent_eval.config._base import (
    ID_PATTERN,
    ConfigError,
    ConfigModel,
    load_yaml_mapping,
)

_FORBIDDEN_PRIMARY_MODEL_KEYS = frozenset(
    {"default_model", "model", "model_id", "primary_model", "requested_model"}
)


class OpenClawModelDefaults(ConfigModel):
    """Benchmark-owned model fragments merged into generated openclaw.json."""

    model_config = ConfigDict(extra="allow", frozen=True)

    fallbacks: list[str] = Field(default_factory=list)
    aliases: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_primary_model_is_not_overridden(self) -> Self:
        extra_keys = set(self.model_extra or {})
        forbidden = sorted(extra_keys.intersection(_FORBIDDEN_PRIMARY_MODEL_KEYS))
        if forbidden:
            formatted = ", ".join(forbidden)
            raise ValueError(
                "openclaw.model_defaults cannot override the primary benchmark model "
                f"via keys: {formatted}."
            )
        return self


class OpenClawFragments(ConfigModel):
    """Allowed benchmark-controlled OpenClaw fragments."""

    identity: dict[str, Any] | None = None
    agents_defaults: dict[str, Any] | None = None
    agent: dict[str, Any] | None = None
    model_defaults: OpenClawModelDefaults | None = None

    @model_validator(mode="after")
    def _validate_primary_model_is_not_overridden(self) -> Self:
        _reject_primary_model_keys(self.agents_defaults, field_name="openclaw.agents_defaults")
        _reject_primary_model_keys(self.agent, field_name="openclaw.agent")
        return self


class OpenClawAgentConfig(ConfigModel):
    """Canonical reusable OpenClaw agent definition."""

    schema_version: Literal[1]
    agent_id: str = Field(pattern=ID_PATTERN)
    title: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    openclaw: OpenClawFragments = Field(default_factory=OpenClawFragments)

    _agent_dir: Path | None = PrivateAttr(default=None)
    _workspace_dir: Path | None = PrivateAttr(default=None)

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        deduplicated = {tag.strip() for tag in value if tag.strip()}
        return sorted(deduplicated)

    @property
    def agent_dir(self) -> Path | None:
        """Return the resolved agent directory."""
        return self._agent_dir

    @property
    def workspace_dir(self) -> Path | None:
        """Return the resolved workspace template directory."""
        return self._workspace_dir

    def with_layout(self, *, agent_dir: Path, workspace_dir: Path) -> Self:
        """Attach resolved filesystem layout after validation."""
        self._agent_dir = agent_dir
        self._workspace_dir = workspace_dir
        return self


def load_openclaw_agent(path: str | Path) -> OpenClawAgentConfig:
    """Load and validate a reusable OpenClaw agent directory or agent.yaml."""
    input_path = Path(path).expanduser().resolve()
    agent_path, agent_dir = _resolve_agent_paths(input_path)
    payload, resolved_path = load_yaml_mapping(agent_path)

    try:
        config = OpenClawAgentConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid OpenClaw agent '{resolved_path}': {exc}") from exc

    if config.agent_id != agent_dir.name:
        raise ConfigError(
            f"Invalid OpenClaw agent '{resolved_path}': agent_id '{config.agent_id}' must match "
            f"directory name '{agent_dir.name}'."
        )

    workspace_dir = agent_dir / "workspace"
    if not workspace_dir.exists():
        raise ConfigError(
            f"Invalid OpenClaw agent '{resolved_path}': missing workspace directory "
            f"'{workspace_dir}'."
        )
    if not workspace_dir.is_dir():
        raise ConfigError(
            f"Invalid OpenClaw agent '{resolved_path}': workspace path '{workspace_dir}' must be "
            "a directory."
        )

    return config.with_source_path(resolved_path).with_layout(
        agent_dir=agent_dir,
        workspace_dir=workspace_dir,
    )


def _resolve_agent_paths(input_path: Path) -> tuple[Path, Path]:
    if input_path.is_dir():
        return input_path / "agent.yaml", input_path

    if input_path.name != "agent.yaml":
        raise ConfigError(
            "OpenClaw agent references must point to an agent directory or an 'agent.yaml' file."
        )

    return input_path, input_path.parent


def _reject_primary_model_keys(
    fragment: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> None:
    if fragment is None:
        return

    forbidden = sorted(key for key in fragment if key in _FORBIDDEN_PRIMARY_MODEL_KEYS)
    if forbidden:
        formatted = ", ".join(forbidden)
        raise ValueError(
            f"{field_name} cannot override the primary benchmark model via keys: {formatted}."
        )
