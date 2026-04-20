"""Summarize OpenClaw evidence for judge prompts without exposing raw URI paths."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from personal_agent_eval.artifacts import RunArtifact
from personal_agent_eval.artifacts.openclaw_run_evidence import (
    OpenClawEvidenceArtifactTypes,
    parse_openclaw_run_evidence,
)
from personal_agent_eval.artifacts.run_artifact import OutputArtifactRef


def build_openclaw_judge_context(artifact: RunArtifact) -> dict[str, object] | None:
    """Return a compact, judge-facing summary of OpenClaw execution evidence.

    Full ``runner_metadata.openclaw`` is replaced in :func:`redact_run_artifact_for_judge` with
    this structure so judges can assess process and workspace outputs without relying on local
    ``file://`` paths inside the raw metadata blob.
    """
    if artifact.identity.runner_type != "openclaw":
        return None
    evidence = parse_openclaw_run_evidence(artifact.runner_metadata)
    if evidence is None:
        return None

    payload: dict[str, object] = {
        "agent_id": evidence.agent_id,
        "container_image": evidence.container_image,
    }
    if evidence.workspace_diff is not None:
        payload["workspace_diff_excerpt"] = _read_text_excerpt(
            evidence.workspace_diff,
            max_chars=12_000,
            binary_placeholder="[workspace_diff is binary or unreadable]",
        )
    if evidence.raw_session_trace is not None:
        payload["raw_session_trace_excerpt"] = _read_text_excerpt(
            evidence.raw_session_trace,
            max_chars=8_000,
            binary_placeholder="[raw_session_trace is binary or unreadable]",
        )
    if evidence.openclaw_logs is not None:
        payload["openclaw_logs_excerpt"] = _read_text_excerpt(
            evidence.openclaw_logs,
            max_chars=6_000,
            binary_placeholder="[openclaw_logs is binary or unreadable]",
        )
    if evidence.generated_openclaw_config is not None:
        payload["generated_openclaw_config_excerpt"] = _read_text_excerpt(
            evidence.generated_openclaw_config,
            max_chars=4_000,
            binary_placeholder="[generated_openclaw_config is binary or unreadable]",
        )

    key_refs = evidence.key_output_artifacts or [
        ref
        for ref in artifact.output_artifacts
        if ref.artifact_type == OpenClawEvidenceArtifactTypes.KEY_OUTPUT
    ]
    key_excerpts: list[dict[str, str | None]] = []
    for ref in key_refs:
        key_excerpts.append(
            {
                "basename": _uri_basename(ref.uri),
                "artifact_type": ref.artifact_type,
                "excerpt": _read_text_excerpt(
                    ref,
                    max_chars=4_000,
                    binary_placeholder="[key output is binary or unreadable]",
                ),
            }
        )
    if key_excerpts:
        payload["key_output_excerpts"] = key_excerpts

    return payload


def _uri_basename(uri: str) -> str:
    parsed = urlparse(uri)
    return Path(parsed.path).name or uri


def _read_text_excerpt(
    ref: OutputArtifactRef,
    *,
    max_chars: int,
    binary_placeholder: str,
) -> str | None:
    parsed = urlparse(ref.uri)
    if parsed.scheme != "file":
        return binary_placeholder
    path = Path(parsed.path)
    if not path.is_file():
        return None
    if ref.media_type == "application/gzip":
        return "[workspace snapshot archive omitted; see workspace_diff_excerpt if present]"
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return ""
    truncated = raw[: max_chars * 4]
    try:
        text = truncated.decode("utf-8")
    except UnicodeDecodeError:
        return binary_placeholder
    if len(text) > max_chars:
        return text[:max_chars] + "\n… [truncated]"
    return text
