"""Canonical suite config schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from personal_agent_eval.config._base import (
    ID_PATTERN,
    ConfigError,
    ConfigModel,
    load_yaml_mapping,
)


class ModelConfig(ConfigModel):
    """A named model entry in a suite."""

    model_config = ConfigDict(extra="allow", frozen=True)

    model_id: str = Field(pattern=ID_PATTERN)
    label: str | None = None
    requested_model: str | None = None
    provider: str | None = None
    model_name: str | None = None


class CaseSelection(ConfigModel):
    """Suite case filters."""

    include_case_ids: list[str] = Field(default_factory=list)
    exclude_case_ids: list[str] = Field(default_factory=list)
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)


class OpenClawAgentAssignment(ConfigModel):
    """Assign one OpenClaw agent to a subset of suite cases."""

    agent_id: str = Field(pattern=ID_PATTERN)
    case_selection: CaseSelection

    @model_validator(mode="after")
    def _validate_has_include_filter(self) -> OpenClawAgentAssignment:
        if not self.case_selection.include_case_ids and not self.case_selection.include_tags:
            raise ValueError(
                "openclaw.agent_assignments entries must define include_case_ids or include_tags."
            )
        return self


class SuiteOpenClawConfig(ConfigModel):
    """Suite-level OpenClaw overrides."""

    agent_assignments: list[OpenClawAgentAssignment] = Field(default_factory=list)


class SuiteConfig(ConfigModel):
    """Canonical suite config."""

    schema_version: Literal[1]
    suite_id: str = Field(pattern=ID_PATTERN)
    title: str
    models: list[ModelConfig] = Field(default_factory=list)
    case_selection: CaseSelection = Field(default_factory=CaseSelection)
    openclaw: SuiteOpenClawConfig = Field(default_factory=SuiteOpenClawConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_suite_config(path: str | Path) -> SuiteConfig:
    """Load and validate a canonical suite config."""
    payload, resolved_path = load_yaml_mapping(path)

    try:
        config = SuiteConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid suite config '{resolved_path}': {exc}") from exc

    return config.with_source_path(resolved_path)
