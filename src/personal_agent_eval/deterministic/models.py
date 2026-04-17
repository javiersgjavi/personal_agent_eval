"""Deterministic evaluation result models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import ConfigDict, Field

from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class DeterministicCheckOutcome(StrEnum):
    """Terminal outcome for one deterministic check."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class HookCheckResult(ArtifactModel):
    """Structured payload returned by a Python deterministic hook."""

    passed: bool
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class DeterministicHookContext(ArtifactModel):
    """Context passed to custom Python hooks."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    check_id: str
    description: str | None = None
    case_source_path: str | None = None


class DeterministicCheckResult(ArtifactModel):
    """Recorded result for one deterministic check."""

    check_id: str
    kind: str
    source: Literal["declarative", "python_hook"]
    outcome: DeterministicCheckOutcome
    passed: bool
    description: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class DeterministicEvaluationSummary(ArtifactModel):
    """Aggregate counts for one deterministic evaluation run."""

    total_checks: int = Field(ge=0)
    passed_checks: int = Field(ge=0)
    failed_checks: int = Field(ge=0)
    error_checks: int = Field(ge=0)


class DeterministicEvaluationResult(ArtifactModel):
    """Top-level deterministic evaluation result for one run artifact."""

    schema_version: Literal[1] = 1
    case_id: str
    run_id: str
    passed: bool
    summary: DeterministicEvaluationSummary
    checks: list[DeterministicCheckResult] = Field(default_factory=list)
