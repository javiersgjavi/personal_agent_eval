"""Typed models for fingerprint payloads and reuse decisions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from personal_agent_eval.artifacts.run_artifact import ArtifactModel

FINGERPRINT_HEX_PATTERN = r"^[a-f0-9]{64}$"


class FingerprintHashPayloadModel(ArtifactModel):
    """Payload material for SHA-256 fingerprints; do not round floats (stable hash input)."""

    def to_json_dict(self, *, round_floats: bool = False) -> dict[str, Any]:
        return super().to_json_dict(round_floats=round_floats)


class FingerprintAlgorithm(StrEnum):
    """Hash algorithms currently supported for canonical fingerprints."""

    SHA256 = "sha256"


class FingerprintInputBase(FingerprintHashPayloadModel):
    """Persistable fingerprint input payload for later storage."""

    fingerprint_version: Literal[1] = 1
    hash_algorithm: FingerprintAlgorithm = FingerprintAlgorithm.SHA256


class ResolvedMessageFingerprint(ArtifactModel):
    """Normalized message content that affects execution."""

    role: str
    content: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttachmentFingerprint(ArtifactModel):
    """Path-independent attachment identity based on content."""

    sha256: str = Field(pattern=FINGERPRINT_HEX_PATTERN)
    byte_size: int = Field(ge=0)
    name: str | None = None


class OpenClawWorkspaceEntryFingerprint(ArtifactModel):
    """Normalized effective workspace entry used for OpenClaw agent identity."""

    relative_path: str
    source: Literal["template", "placeholder"]
    sha256: str = Field(pattern=FINGERPRINT_HEX_PATTERN)
    size_bytes: int = Field(ge=0)


class OpenClawAgentFingerprintPayload(FingerprintHashPayloadModel):
    """Normalized OpenClaw agent definition and effective workspace identity."""

    agent_id: str
    agent_config: dict[str, Any] = Field(default_factory=dict)
    workspace_entries: list[OpenClawWorkspaceEntryFingerprint] = Field(default_factory=list)


class OpenClawAgentFingerprintInput(FingerprintInputBase):
    """Persistable OpenClaw agent fingerprint input payload."""

    kind: Literal["openclaw_agent"] = "openclaw_agent"
    payload: OpenClawAgentFingerprintPayload
    fingerprint: str = Field(pattern=FINGERPRINT_HEX_PATTERN)


class RunFingerprintPayload(FingerprintHashPayloadModel):
    """Normalized execution inputs that affect the raw run trace."""

    runner_type: str
    requested_model: str
    runner_config: dict[str, Any] = Field(default_factory=dict)
    input_messages: list[ResolvedMessageFingerprint] = Field(default_factory=list)
    input_context: dict[str, Any] = Field(default_factory=dict)
    attachments: list[AttachmentFingerprint] = Field(default_factory=list)
    case_metadata: dict[str, Any] = Field(default_factory=dict)


class RunFingerprintInput(FingerprintInputBase):
    """Persistable run fingerprint input payload."""

    kind: Literal["run"] = "run"
    payload: RunFingerprintPayload
    fingerprint: str = Field(pattern=FINGERPRINT_HEX_PATTERN)


class JudgeDefinitionFingerprint(ArtifactModel):
    """Normalized judge definition relevant for evaluation behavior."""

    judge_id: str
    type: str
    settings: dict[str, Any] = Field(default_factory=dict)


class JudgeRunFingerprint(ArtifactModel):
    """Normalized judge repetition plan."""

    judge_id: str
    repetitions: int = Field(ge=1)
    sample_size: int | None = Field(default=None, ge=1)


class AnchorReferenceFingerprint(ArtifactModel):
    """Normalized anchor content used to ground judges."""

    anchor_id: str
    label: str
    text: str


class EvaluationFingerprintPayload(FingerprintHashPayloadModel):
    """Normalized evaluation inputs that affect judging and aggregation."""

    judges: list[JudgeDefinitionFingerprint] = Field(default_factory=list)
    judge_runs: list[JudgeRunFingerprint] = Field(default_factory=list)
    judge_aggregation: dict[str, Any] = Field(default_factory=dict)
    final_aggregation: dict[str, Any] = Field(default_factory=dict)
    anchors: dict[str, Any] = Field(default_factory=dict)
    security_policy: dict[str, Any] = Field(default_factory=dict)
    judge_system_prompt: dict[str, Any] = Field(default_factory=dict)


class EvaluationFingerprintInput(FingerprintInputBase):
    """Persistable evaluation fingerprint input payload."""

    kind: Literal["evaluation"] = "evaluation"
    payload: EvaluationFingerprintPayload
    fingerprint: str = Field(pattern=FINGERPRINT_HEX_PATTERN)


class ReuseAction(StrEnum):
    """Top-level orchestration decision for run/evaluation reuse."""

    REUSE_ALL = "reuse_all"
    REUSE_RUN_ONLY = "reuse_run_only"
    EXECUTE_NEW_RUN = "execute_new_run"


class ReuseDecision(ArtifactModel):
    """Reusable summary that Step 10/11 can consume later."""

    requested_run_fingerprint: str = Field(pattern=FINGERPRINT_HEX_PATTERN)
    requested_evaluation_fingerprint: str = Field(pattern=FINGERPRINT_HEX_PATTERN)
    stored_run_fingerprint: str | None = Field(default=None, pattern=FINGERPRINT_HEX_PATTERN)
    stored_evaluation_fingerprint: str | None = Field(default=None, pattern=FINGERPRINT_HEX_PATTERN)
    run_reusable: bool
    evaluation_reusable: bool
    action: ReuseAction
