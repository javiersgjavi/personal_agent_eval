"""Typed storage manifests."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class RunStorageManifest(ArtifactModel):
    """Top-level manifest for one run fingerprint space."""

    schema_version: Literal[1] = 1
    run_fingerprint: str = Field(min_length=1)
    runner_type: str = Field(min_length=1)
    suite_id: str = Field(min_length=1)
    run_profile_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class EvaluationStorageManifest(ArtifactModel):
    """Top-level manifest for one evaluation fingerprint space."""

    schema_version: Literal[1] = 1
    evaluation_fingerprint: str = Field(min_length=1)
    evaluation_profile_id: str = Field(min_length=1)
    aggregation_method: str = Field(min_length=1)
    default_dimension_policy: str = Field(min_length=1)
