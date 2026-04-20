"""Omit subject-model identity from payloads sent to judge LLMs."""

from __future__ import annotations

import copy
from typing import Any

from personal_agent_eval.artifacts import RunArtifact
from personal_agent_eval.judge.openclaw_context import build_openclaw_judge_context


def redact_run_artifact_for_judge(artifact: RunArtifact) -> dict[str, Any]:
    """Return a deep copy of the run artifact JSON safe to embed in judge prompts.

    Structured fields that identify the evaluated model are **removed** (not replaced with
    placeholders): requested model, provider model id, suite ``model_selection`` snapshot,
    raw ``runner_metadata`` blobs, and provider usage keys that echo the model id.

    For ``runner.type: openclaw``, a replacement ``runner_metadata.openclaw_judge_context`` is
    attached with text excerpts of workspace diff, traces, logs, and key outputs so judges can
    evaluate agent behavior without raw ``file://`` evidence references.

    Stored artifacts on disk are unchanged; only the judge-facing snapshot is stripped.

    Note: free-form assistant text in the trace could still mention a vendor or model name;
    this layer only removes structured identity fields.
    """
    data: dict[str, Any] = copy.deepcopy(artifact.to_json_dict())

    request = data.get("request")
    if isinstance(request, dict):
        request.pop("requested_model", None)
        metadata = request.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("model_selection", None)
            if not metadata:
                request.pop("metadata", None)

    provider = data.get("provider")
    if isinstance(provider, dict):
        provider.pop("provider_model_id", None)
        pmeta = provider.get("metadata")
        if isinstance(pmeta, dict):
            for key in ("model", "model_id", "requested_model"):
                pmeta.pop(key, None)
            if not pmeta:
                provider.pop("metadata", None)

    data.pop("runner_metadata", None)
    openclaw_context = build_openclaw_judge_context(artifact)
    if openclaw_context is not None:
        data["runner_metadata"] = {"openclaw_judge_context": openclaw_context}

    usage = data.get("usage")
    if isinstance(usage, dict):
        raw_usage = usage.get("raw_provider_usage")
        if isinstance(raw_usage, dict):
            raw_usage.pop("model", None)
            raw_usage.pop("model_id", None)
            if not raw_usage:
                usage.pop("raw_provider_usage", None)

    trace = data.get("trace")
    if isinstance(trace, list):
        for event in trace:
            if not isinstance(event, dict):
                continue
            em = event.get("metadata")
            if isinstance(em, dict):
                for key in ("model_id", "provider_model_id", "requested_model"):
                    em.pop(key, None)
                if not em:
                    event.pop("metadata", None)

    return data
