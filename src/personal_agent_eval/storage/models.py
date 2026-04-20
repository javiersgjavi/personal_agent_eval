"""Typed storage manifests."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class RunStorageManifest(ArtifactModel):
    """Top-level manifest for one suite/run-profile campaign."""

    schema_version: Literal[1] = 1
    suite_id: str = Field(min_length=1)
    run_profile_id: str = Field(min_length=1)
    run_profile_fingerprint: str = Field(min_length=1)
    runner_type: str = Field(min_length=1)
    run_repetitions: int = Field(ge=1)


class EvaluationStorageManifest(ArtifactModel):
    """Top-level manifest for one suite/run/evaluation campaign."""

    schema_version: Literal[1] = 1
    suite_id: str = Field(min_length=1)
    run_profile_id: str = Field(min_length=1)
    run_profile_fingerprint: str = Field(min_length=1)
    evaluation_fingerprint: str = Field(min_length=1)
    evaluation_profile_id: str = Field(min_length=1)
    aggregation_method: str = Field(min_length=1)
    default_dimension_policy: str = Field(min_length=1)
    judge_system_prompt_source: str = Field(min_length=1)
    judge_system_prompt: str = Field(min_length=1)


class RunIterationRecord(ArtifactModel):
    """Stored identity for one run repetition."""

    repetition_index: int = Field(ge=0)
    run_fingerprint: str = Field(min_length=1)


class RunCaseStorageManifest(ArtifactModel):
    """Per-model per-case run manifest within one campaign."""

    schema_version: Literal[1] = 1
    suite_id: str = Field(min_length=1)
    run_profile_id: str = Field(min_length=1)
    run_profile_fingerprint: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    iterations: list[RunIterationRecord] = Field(default_factory=list)
    runner_type: str | None = Field(
        default=None,
        description="Runner for this case when known (e.g. openclaw vs llm_probe).",
    )
    openclaw_agent_id: str | None = Field(
        default=None,
        description="Resolved OpenClaw agent_id when runner_type is openclaw.",
    )


class EvaluationIterationRecord(ArtifactModel):
    """Stored identity for one evaluation repetition."""

    repetition_index: int = Field(ge=0)
    run_fingerprint: str = Field(min_length=1)
    evaluation_fingerprint: str = Field(min_length=1)


class EvaluationCaseStorageManifest(ArtifactModel):
    """Per-model per-case evaluation manifest within one campaign."""

    schema_version: Literal[1] = 1
    suite_id: str = Field(min_length=1)
    run_profile_id: str = Field(min_length=1)
    run_profile_fingerprint: str = Field(min_length=1)
    evaluation_profile_id: str = Field(min_length=1)
    evaluation_fingerprint: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    iterations: list[EvaluationIterationRecord] = Field(default_factory=list)
