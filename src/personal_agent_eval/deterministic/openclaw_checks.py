"""OpenClaw-specific helpers for deterministic checks."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from personal_agent_eval.artifacts import RunArtifact
from personal_agent_eval.artifacts.openclaw_run_evidence import OpenClawEvidenceArtifactTypes
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    OutputArtifactRef,
)


def effective_final_response_text(artifact: RunArtifact) -> str:
    """Text used for ``final_response_present`` when the trace shape is runner-specific.

    For ``llm_probe``, this matches the historic rule: last non-empty ``final_output`` event.

    For ``openclaw``, falls back to the last assistant ``message`` with content, then to the
    first readable text ``output_artifact`` body (key outputs from the workspace).
    """
    finals = [
        event.content.strip()
        for event in artifact.trace
        if isinstance(event, FinalOutputTraceEvent)
        and event.content is not None
        and event.content.strip()
    ]
    if finals:
        return finals[-1]

    if artifact.identity.runner_type != "openclaw":
        return ""

    assistants = [
        (event.content or "").strip()
        for event in artifact.trace
        if isinstance(event, MessageTraceEvent)
        and event.role == "assistant"
        and event.content
        and event.content.strip()
    ]
    if assistants:
        return assistants[-1]

    for ref in artifact.output_artifacts:
        if ref.artifact_type != OpenClawEvidenceArtifactTypes.KEY_OUTPUT:
            continue
        text = _read_text_from_uri(ref.uri, max_bytes=256_000)
        if text and text.strip():
            return text.strip()
    return ""


def output_artifact_resolves_to_workspace_file(
    ref: OutputArtifactRef,
    relative_path: str,
) -> bool:
    """Return whether ``ref`` points at a file whose path ends with ``relative_path``."""
    normalized = relative_path.replace("\\", "/").lstrip("/")
    path = _path_from_uri(ref.uri)
    if path is None or not path.is_file():
        return False
    try:
        suffix = path.resolve().as_posix()
    except OSError:
        return False
    return suffix.endswith(normalized) or path.name == Path(normalized).name


def read_output_artifact_text(ref: OutputArtifactRef, *, max_bytes: int) -> str | None:
    """Return decoded text for a ``file://`` output ref, or ``None`` if unreadable."""
    return _read_text_from_uri(ref.uri, max_bytes=max_bytes)


def _path_from_uri(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = Path(parsed.path)
    return path if path.is_file() else None


def _read_text_from_uri(uri: str, *, max_bytes: int) -> str | None:
    path = _path_from_uri(uri)
    if path is None:
        return None
    try:
        raw = path.read_bytes()[:max_bytes]
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
