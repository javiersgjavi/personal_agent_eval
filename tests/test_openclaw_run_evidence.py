from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from personal_agent_eval.artifacts import (
    OPENCLAW_RUNNER_METADATA_KEY,
    OpenClawEvidenceArtifactTypes,
    OpenClawRunEvidence,
    OutputArtifactRef,
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
    RunTiming,
    inject_openclaw_run_evidence,
    parse_openclaw_run_evidence,
    with_openclaw_run_evidence,
)
from personal_agent_eval.fingerprints import RunFingerprintInput, RunFingerprintPayload
from personal_agent_eval.storage import FilesystemStorage
from personal_agent_eval.storage.models import RunStorageManifest


def _ref(*, artifact_id: str, artifact_type: str, uri: str) -> OutputArtifactRef:
    return OutputArtifactRef(artifact_id=artifact_id, artifact_type=artifact_type, uri=uri)


def _minimal_openclaw_artifact(*, runner_metadata: dict[str, Any] | None = None) -> RunArtifact:
    return RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="run_oc_1",
            case_id="example_case",
            suite_id="example_suite",
            run_profile_id="default",
            runner_type="openclaw",
        ),
        status=RunStatus.SUCCESS,
        timing=RunTiming(
            queued_at=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
            started_at=datetime(2026, 4, 19, 10, 0, 1, tzinfo=UTC),
            completed_at=datetime(2026, 4, 19, 10, 0, 2, tzinfo=UTC),
            duration_seconds=1.0,
        ),
        request=RunRequestMetadata(requested_model="openai/gpt-example"),
        runner_metadata=dict(runner_metadata or {}),
    )


def test_openclaw_run_evidence_round_trip_json() -> None:
    evidence = OpenClawRunEvidence(
        agent_id="support_agent",
        container_image="ghcr.io/openclaw/openclaw-base:0.1.0",
        generated_openclaw_config=_ref(
            artifact_id="openclaw_cfg",
            artifact_type=OpenClawEvidenceArtifactTypes.GENERATED_OPENCLAW_CONFIG,
            uri="file:///tmp/run/openclaw.json",
        ),
        raw_session_trace=_ref(
            artifact_id="openclaw_trace",
            artifact_type=OpenClawEvidenceArtifactTypes.RAW_SESSION_TRACE,
            uri="file:///tmp/run/session.jsonl",
        ),
        openclaw_logs=_ref(
            artifact_id="openclaw_logs",
            artifact_type=OpenClawEvidenceArtifactTypes.OPENCLAW_LOGS,
            uri="file:///tmp/run/logs.txt",
        ),
        workspace_snapshot=_ref(
            artifact_id="ws_snapshot",
            artifact_type=OpenClawEvidenceArtifactTypes.WORKSPACE_SNAPSHOT,
            uri="file:///tmp/run/workspace.tgz",
        ),
        workspace_diff=_ref(
            artifact_id="ws_diff",
            artifact_type=OpenClawEvidenceArtifactTypes.WORKSPACE_DIFF,
            uri="file:///tmp/run/workspace.diff",
        ),
        key_output_artifacts=[
            _ref(
                artifact_id="key_report",
                artifact_type=OpenClawEvidenceArtifactTypes.KEY_OUTPUT,
                uri="file:///tmp/run/report.md",
            )
        ],
        metadata={"harness": "fixture"},
    )
    restored = OpenClawRunEvidence.model_validate(evidence.to_json_dict())
    assert restored == evidence


def test_parse_openclaw_run_evidence_missing_key() -> None:
    assert parse_openclaw_run_evidence({}) is None
    assert parse_openclaw_run_evidence({"other": 1}) is None


def test_run_artifact_top_level_json_shape_unchanged_with_openclaw_block() -> None:
    evidence = OpenClawRunEvidence(agent_id="support_agent")
    artifact = _minimal_openclaw_artifact(
        runner_metadata={OPENCLAW_RUNNER_METADATA_KEY: evidence.model_dump(mode="json")}
    )
    payload = artifact.to_json_dict()
    assert set(payload) == {
        "identity",
        "status",
        "timing",
        "request",
        "provider",
        "usage",
        "trace",
        "output_artifacts",
        "error",
        "runner_metadata",
    }
    nested = parse_openclaw_run_evidence(artifact.runner_metadata)
    assert nested is not None
    assert nested.agent_id == "support_agent"


def test_run_artifact_rejects_invalid_openclaw_block() -> None:
    with pytest.raises(ValueError, match="Invalid OpenClaw run evidence"):
        _minimal_openclaw_artifact(
            runner_metadata={
                OPENCLAW_RUNNER_METADATA_KEY: {"schema_version": 1, "agent_id": "Invalid ID"}
            }
        )


def test_with_openclaw_run_evidence_preserves_other_runner_metadata() -> None:
    evidence = OpenClawRunEvidence(agent_id="support_agent")
    artifact = _minimal_openclaw_artifact(runner_metadata={"attempt_count": 1})
    merged = with_openclaw_run_evidence(artifact, evidence)
    assert merged.runner_metadata["attempt_count"] == 1
    assert parse_openclaw_run_evidence(merged.runner_metadata) == evidence


def test_inject_openclaw_run_evidence_writes_json_mapping() -> None:
    md: dict[str, object] = {}
    evidence = OpenClawRunEvidence(agent_id="support_agent")
    inject_openclaw_run_evidence(md, evidence)
    assert isinstance(md[OPENCLAW_RUNNER_METADATA_KEY], dict)
    assert OpenClawRunEvidence.model_validate(md[OPENCLAW_RUNNER_METADATA_KEY]) == evidence


def test_openclaw_run_evidence_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OpenClawRunEvidence.model_validate(
            {
                "schema_version": 1,
                "agent_id": "support_agent",
                "unexpected": True,
            }
        )


def test_storage_round_trips_openclaw_run_artifact(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    suite_id = "example_suite"
    run_profile_id = "default"
    run_profile_fingerprint = "d" * 64
    run_fingerprint = "a" * 64
    model_id = "baseline_model"

    evidence = OpenClawRunEvidence(
        agent_id="support_agent",
        generated_openclaw_config=_ref(
            artifact_id="cfg",
            artifact_type=OpenClawEvidenceArtifactTypes.GENERATED_OPENCLAW_CONFIG,
            uri="file:///workspace/openclaw.json",
        ),
    )
    run_artifact = with_openclaw_run_evidence(
        _minimal_openclaw_artifact(),
        evidence,
    )

    storage.write_run_manifest(
        RunStorageManifest(
            suite_id=suite_id,
            run_profile_id=run_profile_id,
            run_profile_fingerprint=run_profile_fingerprint,
            runner_type="openclaw",
            run_repetitions=1,
        )
    )
    storage.write_case_run(
        suite_id=suite_id,
        run_profile_id=run_profile_id,
        run_profile_fingerprint=run_profile_fingerprint,
        model_id=model_id,
        repetition_index=0,
        run_fingerprint=run_fingerprint,
        artifact=run_artifact,
        fingerprint_input=RunFingerprintInput(
            fingerprint=run_fingerprint,
            payload=RunFingerprintPayload(
                runner_type="openclaw",
                requested_model="openai/gpt-example",
            ),
        ),
    )

    loaded = storage.read_case_run(
        suite_id=suite_id,
        run_profile_fingerprint=run_profile_fingerprint,
        model_id=model_id,
        case_id="example_case",
        repetition_index=0,
    )
    assert loaded == run_artifact
    assert parse_openclaw_run_evidence(loaded.runner_metadata) == evidence
