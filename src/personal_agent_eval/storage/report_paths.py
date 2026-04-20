"""Helpers to derive stable, workspace-root-relative paths for reporting."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from personal_agent_eval.artifacts import RunArtifact, parse_openclaw_run_evidence
from personal_agent_eval.artifacts.openclaw_run_evidence import OpenClawEvidenceArtifactTypes
from personal_agent_eval.artifacts.run_artifact import OutputArtifactRef
from personal_agent_eval.workflow.models import OpenClawWorkflowEvidenceSummary


def file_uri_relative_to_storage_root(*, uri: str, storage_root: Path) -> str | None:
    """Return a POSIX path relative to ``storage_root`` for a local ``file://`` URI, if possible."""
    path = _local_file_uri_to_path(uri)
    if path is None:
        return None
    resolved = path.resolve()
    root = storage_root.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _local_file_uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    if parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path))


def build_openclaw_workflow_evidence_summary(
    storage_root: Path,
    run_artifact: RunArtifact,
) -> OpenClawWorkflowEvidenceSummary | None:
    """Map persisted OpenClaw evidence refs to paths relative to the workspace/storage root."""
    evidence = parse_openclaw_run_evidence(run_artifact.runner_metadata)
    if evidence is None:
        return None
    paths: dict[str, str] = {}

    def add_ref(ref: OutputArtifactRef | None, key: str) -> None:
        if ref is None:
            return
        rel = file_uri_relative_to_storage_root(uri=ref.uri, storage_root=storage_root)
        if rel is not None:
            paths[key] = rel

    t = OpenClawEvidenceArtifactTypes
    add_ref(evidence.generated_openclaw_config, t.GENERATED_OPENCLAW_CONFIG)
    add_ref(evidence.raw_session_trace, t.RAW_SESSION_TRACE)
    add_ref(evidence.openclaw_logs, t.OPENCLAW_LOGS)
    add_ref(evidence.workspace_snapshot, t.WORKSPACE_SNAPSHOT)
    add_ref(evidence.workspace_diff, t.WORKSPACE_DIFF)
    for ref in evidence.key_output_artifacts:
        add_ref(ref, f"{t.KEY_OUTPUT}:{ref.artifact_id}")

    return OpenClawWorkflowEvidenceSummary(
        agent_id=evidence.agent_id,
        container_image=evidence.container_image,
        evidence_paths=paths,
    )
