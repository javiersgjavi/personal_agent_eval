"""Canonical evaluation profile schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from personal_agent_eval.config._base import (
    ID_PATTERN,
    ConfigError,
    ConfigModel,
    load_yaml_mapping,
)


class JudgeConfig(ConfigModel):
    """A judge definition."""

    model_config = ConfigDict(extra="allow", frozen=True)

    judge_id: str = Field(pattern=ID_PATTERN)
    type: str


class JudgeRunConfig(ConfigModel):
    """A concrete judge execution plan."""

    judge_run_id: str = Field(pattern=ID_PATTERN)
    judge_id: str = Field(pattern=ID_PATTERN)
    repetitions: int = Field(default=1, ge=1)
    sample_size: int | None = Field(default=None, ge=1)


class AggregationConfig(ConfigModel):
    """Aggregation policy for judge outputs."""

    method: Literal["mean", "majority_vote", "all_pass"] = "mean"
    pass_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class Anchor(ConfigModel):
    """An anchor example that can be referenced by judges."""

    anchor_id: str = Field(pattern=ID_PATTERN)
    label: str
    text: str


class AnchorsConfig(ConfigModel):
    """Anchor configuration."""

    enabled: bool = False
    references: list[Anchor] = Field(default_factory=list)


class SecurityPolicy(ConfigModel):
    """Security policy for evaluation execution."""

    allow_local_python_hooks: bool = False
    network_access: Literal["deny", "allow"] = "deny"
    redact_secrets: bool = True


class EvaluationProfileConfig(ConfigModel):
    """Canonical evaluation profile config."""

    schema_version: Literal[1]
    evaluation_profile_id: str = Field(pattern=ID_PATTERN)
    title: str
    judges: list[JudgeConfig] = Field(default_factory=list)
    judge_runs: list[JudgeRunConfig] = Field(default_factory=list)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    anchors: AnchorsConfig = Field(default_factory=AnchorsConfig)
    security_policy: SecurityPolicy = Field(default_factory=SecurityPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_evaluation_profile(path: str | Path) -> EvaluationProfileConfig:
    """Load and validate a canonical evaluation profile."""
    payload, resolved_path = load_yaml_mapping(path)

    try:
        config = EvaluationProfileConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid evaluation profile '{resolved_path}': {exc}") from exc

    return config.with_source_path(resolved_path)
