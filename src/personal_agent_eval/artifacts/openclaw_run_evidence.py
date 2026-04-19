"""OpenClaw run evidence contract (Step 2): structured refs under runner_metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, ValidationError

from personal_agent_eval.artifacts.run_artifact import ArtifactModel, OutputArtifactRef, RunArtifact
from personal_agent_eval.config._base import ID_PATTERN

OPENCLAW_RUNNER_METADATA_KEY = "openclaw"


class OpenClawEvidenceArtifactTypes:
    """Stable ``artifact_type`` values for :class:`OutputArtifactRef` OpenClaw assets."""

    GENERATED_OPENCLAW_CONFIG = "openclaw_generated_config"
    RAW_SESSION_TRACE = "openclaw_raw_session_trace"
    OPENCLAW_LOGS = "openclaw_logs"
    WORKSPACE_SNAPSHOT = "openclaw_workspace_snapshot"
    WORKSPACE_DIFF = "openclaw_workspace_diff"
    KEY_OUTPUT = "openclaw_key_output"


class OpenClawRunEvidence(ArtifactModel):
    """Large OpenClaw assets as :class:`OutputArtifactRef` entries, not embedded blobs.

    Stored on :class:`RunArtifact` as ``runner_metadata[\"openclaw\"]`` so the top-level
    run artifact JSON shape stays unchanged for existing consumers.
    """

    schema_version: Literal[1] = 1
    agent_id: str = Field(pattern=ID_PATTERN)
    container_image: str | None = None
    generated_openclaw_config: OutputArtifactRef | None = None
    raw_session_trace: OutputArtifactRef | None = None
    openclaw_logs: OutputArtifactRef | None = None
    workspace_snapshot: OutputArtifactRef | None = None
    workspace_diff: OutputArtifactRef | None = None
    key_output_artifacts: list[OutputArtifactRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def parse_openclaw_run_evidence(
    runner_metadata: Mapping[str, Any],
) -> OpenClawRunEvidence | None:
    """Return validated OpenClaw evidence if ``runner_metadata`` contains it."""
    payload = runner_metadata.get(OPENCLAW_RUNNER_METADATA_KEY)
    if payload is None:
        return None
    if isinstance(payload, OpenClawRunEvidence):
        return payload
    return OpenClawRunEvidence.model_validate(payload)


def inject_openclaw_run_evidence(
    runner_metadata: dict[str, Any],
    evidence: OpenClawRunEvidence,
) -> None:
    """Write ``evidence`` into ``runner_metadata`` under the canonical key (JSON-ready dict)."""
    runner_metadata[OPENCLAW_RUNNER_METADATA_KEY] = evidence.model_dump(mode="json")


def with_openclaw_run_evidence(
    artifact: RunArtifact,
    evidence: OpenClawRunEvidence,
) -> RunArtifact:
    """Return a copy of ``artifact`` with OpenClaw evidence attached."""
    metadata = dict(artifact.runner_metadata)
    inject_openclaw_run_evidence(metadata, evidence)
    return artifact.model_copy(update={"runner_metadata": metadata})


def validate_runner_metadata_openclaw(runner_metadata: Mapping[str, Any]) -> None:
    """Fail fast if an ``openclaw`` block is present but invalid."""
    if OPENCLAW_RUNNER_METADATA_KEY not in runner_metadata:
        return
    try:
        OpenClawRunEvidence.model_validate(runner_metadata[OPENCLAW_RUNNER_METADATA_KEY])
    except ValidationError as exc:
        raise ValueError(f"Invalid OpenClaw run evidence in runner_metadata: {exc}") from exc
