"""Canonical evaluation profile schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

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


class JudgeAggregationConfig(ConfigModel):
    """Aggregation policy for repeated judge outputs."""

    method: Literal["median", "mean", "majority_vote", "all_pass"] = "median"
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
    aggregation: JudgeAggregationConfig = Field(default_factory=JudgeAggregationConfig)
    anchors: AnchorsConfig = Field(default_factory=AnchorsConfig)
    security_policy: SecurityPolicy = Field(default_factory=SecurityPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    judge_system_prompt: str | None = Field(
        default=None,
        description="Optional judge system message. Multiline YAML string; lines are joined with "
        "spaces. Mutually exclusive with judge_system_prompt_path.",
    )
    judge_system_prompt_path: str | None = Field(
        default=None,
        description="Optional path to a UTF-8 text file, relative to this profile's YAML file. "
        "Mutually exclusive with judge_system_prompt. Recommended shared location: "
        "'prompts/judge_system_default.md' relative to this YAML.",
    )

    @field_validator("judge_system_prompt", "judge_system_prompt_path", mode="before")
    @classmethod
    def _empty_prompt_fields_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_judge_system_prompt_fields(self) -> EvaluationProfileConfig:
        has_inline = self.judge_system_prompt is not None and self.judge_system_prompt.strip() != ""
        has_path = (
            self.judge_system_prompt_path is not None
            and self.judge_system_prompt_path.strip() != ""
        )
        if has_inline and has_path:
            raise ValueError(
                "Specify only one of 'judge_system_prompt' or 'judge_system_prompt_path'."
            )
        return self


def load_evaluation_profile(path: str | Path) -> EvaluationProfileConfig:
    """Load and validate a canonical evaluation profile."""
    payload, resolved_path = load_yaml_mapping(path)

    try:
        config = EvaluationProfileConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid evaluation profile '{resolved_path}': {exc}") from exc

    return config.with_source_path(resolved_path)
