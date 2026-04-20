"""Canonical run profile schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator

from personal_agent_eval.config._base import (
    ID_PATTERN,
    ConfigError,
    ConfigModel,
    load_yaml_mapping,
)


class ExecutionPolicy(ConfigModel):
    """Execution policy controls for a run profile."""

    max_concurrency: int = Field(default=1, ge=1)
    run_repetitions: int = Field(default=1, ge=1)
    fail_fast: bool = False
    stop_on_runner_error: bool = True


class OpenClawRunProfile(ConfigModel):
    """OpenClaw-specific execution settings resolved from run_profile.yaml."""

    agent_id: str = Field(pattern=ID_PATTERN)
    image: str
    timeout_seconds: int = Field(gt=0)
    docker_cli: str = Field(
        default="docker",
        description="OCI runtime CLI (docker, podman, …) used to run the pinned image.",
    )

    @field_validator("image")
    @classmethod
    def _validate_image(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("openclaw.image must be a non-empty string.")
        return stripped

    @field_validator("docker_cli")
    @classmethod
    def _validate_docker_cli(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("openclaw.docker_cli must be a non-empty string.")
        return stripped


class RunProfileConfig(ConfigModel):
    """Canonical run profile config."""

    schema_version: Literal[1]
    run_profile_id: str = Field(pattern=ID_PATTERN)
    title: str
    runner_defaults: dict[str, Any] = Field(default_factory=dict)
    model_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    openclaw: OpenClawRunProfile | None = None


def load_run_profile(path: str | Path) -> RunProfileConfig:
    """Load and validate a canonical run profile."""
    payload, resolved_path = load_yaml_mapping(path)

    try:
        config = RunProfileConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid run profile '{resolved_path}': {exc}") from exc

    return config.with_source_path(resolved_path)
