"""Fingerprint builders and reuse rules."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from personal_agent_eval.config.evaluation_profile import EvaluationProfileConfig
from personal_agent_eval.config.run_profile import RunProfileConfig
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import Message, TestConfig
from personal_agent_eval.fingerprints.models import (
    AnchorReferenceFingerprint,
    AttachmentFingerprint,
    EvaluationFingerprintInput,
    EvaluationFingerprintPayload,
    JudgeDefinitionFingerprint,
    JudgeRunFingerprint,
    ResolvedMessageFingerprint,
    ReuseAction,
    ReuseDecision,
    RunFingerprintInput,
    RunFingerprintPayload,
)
from personal_agent_eval.judge.system_prompt import judge_system_prompt_fingerprint_material


def build_run_fingerprint_input(
    *,
    test_config: TestConfig,
    run_profile: RunProfileConfig,
    model_selection: ModelConfig,
    repetition_index: int | None = None,
) -> RunFingerprintInput:
    """Build the persistable run fingerprint input for one execution."""
    payload = RunFingerprintPayload(
        runner_type=test_config.runner.type,
        requested_model=_resolve_requested_model(model_selection),
        runner_config=_normalize_for_hash(
            _resolve_execution_settings(
                case_config=test_config,
                run_profile=run_profile,
                model_selection=model_selection,
                repetition_index=repetition_index,
            )
        ),
        input_messages=_resolve_messages_for_fingerprint(test_config.input.messages),
        input_context=_normalize_for_hash(dict(test_config.input.context)),
        attachments=[
            _attachment_fingerprint(path)
            for path in sorted(test_config.input.attachments, key=lambda item: item.name)
        ],
        case_metadata=_normalize_for_hash(dict(test_config.metadata)),
    )
    fingerprint = _sha256_json(payload.to_json_dict())
    return RunFingerprintInput(payload=payload, fingerprint=fingerprint)


def build_evaluation_fingerprint_input(
    *,
    evaluation_profile: EvaluationProfileConfig,
) -> EvaluationFingerprintInput:
    """Build the persistable evaluation fingerprint input."""
    payload = EvaluationFingerprintPayload(
        judges=sorted(
            [
                JudgeDefinitionFingerprint(
                    judge_id=judge.judge_id,
                    type=judge.type,
                    settings=_normalize_for_hash(
                        judge.model_dump(exclude={"judge_id", "type"}, mode="json")
                    ),
                )
                for judge in evaluation_profile.judges
            ],
            key=lambda item: item.judge_id,
        ),
        judge_runs=sorted(
            [
                JudgeRunFingerprint(
                    judge_id=judge_run.judge_id,
                    repetitions=judge_run.repetitions,
                    sample_size=judge_run.sample_size,
                )
                for judge_run in evaluation_profile.judge_runs
            ],
            key=lambda item: (item.judge_id, item.repetitions, item.sample_size or 0),
        ),
        judge_aggregation=_normalize_for_hash(
            evaluation_profile.aggregation.model_dump(mode="json")
        ),
        final_aggregation=_normalize_for_hash(
            evaluation_profile.final_aggregation.model_dump(mode="json")
        ),
        anchors={
            "enabled": evaluation_profile.anchors.enabled,
            "references": [
                anchor
                for anchor in sorted(
                    [
                        AnchorReferenceFingerprint(
                            anchor_id=anchor.anchor_id,
                            label=anchor.label,
                            text=anchor.text,
                        )
                        for anchor in evaluation_profile.anchors.references
                    ],
                    key=lambda item: item.anchor_id,
                )
            ],
        },
        security_policy=_normalize_for_hash(
            evaluation_profile.security_policy.model_dump(mode="json")
        ),
        judge_system_prompt=_normalize_for_hash(
            judge_system_prompt_fingerprint_material(evaluation_profile)
        ),
    )
    fingerprint = _sha256_json(payload.to_json_dict())
    return EvaluationFingerprintInput(payload=payload, fingerprint=fingerprint)


def build_run_profile_fingerprint(*, run_profile: RunProfileConfig) -> str:
    """Build a semantic fingerprint for one run profile."""
    payload = _normalize_for_hash(
        run_profile.model_dump(exclude={"run_profile_id", "title"}, mode="json")
    )
    return _sha256_json(payload)


def decide_reuse(
    *,
    requested_run_fingerprint: str,
    requested_evaluation_fingerprint: str,
    stored_run_fingerprint: str | None = None,
    stored_evaluation_fingerprint: str | None = None,
) -> ReuseDecision:
    """Decide what can be reused for a requested run/evaluation pair."""
    run_reusable = stored_run_fingerprint == requested_run_fingerprint
    evaluation_reusable = run_reusable and (
        stored_evaluation_fingerprint == requested_evaluation_fingerprint
    )

    if not run_reusable:
        action = ReuseAction.EXECUTE_NEW_RUN
    elif evaluation_reusable:
        action = ReuseAction.REUSE_ALL
    else:
        action = ReuseAction.REUSE_RUN_ONLY

    return ReuseDecision(
        requested_run_fingerprint=requested_run_fingerprint,
        requested_evaluation_fingerprint=requested_evaluation_fingerprint,
        stored_run_fingerprint=stored_run_fingerprint,
        stored_evaluation_fingerprint=stored_evaluation_fingerprint,
        run_reusable=run_reusable,
        evaluation_reusable=evaluation_reusable,
        action=action,
    )


def is_run_reusable(*, requested_run_fingerprint: str, stored_run_fingerprint: str | None) -> bool:
    """Return whether an existing run can be reused."""
    return stored_run_fingerprint == requested_run_fingerprint


def is_evaluation_reusable(
    *,
    requested_run_fingerprint: str,
    requested_evaluation_fingerprint: str,
    stored_run_fingerprint: str | None,
    stored_evaluation_fingerprint: str | None,
) -> bool:
    """Return whether an existing evaluation can be reused."""
    return (
        stored_run_fingerprint == requested_run_fingerprint
        and stored_evaluation_fingerprint == requested_evaluation_fingerprint
    )


def _resolve_execution_settings(
    *,
    case_config: TestConfig,
    run_profile: RunProfileConfig,
    model_selection: ModelConfig,
    repetition_index: int | None,
) -> dict[str, Any]:
    resolved = dict(run_profile.runner_defaults)
    resolved.update(run_profile.model_overrides.get(model_selection.model_id, {}))
    resolved.update(case_config.runner.model_dump(exclude={"type"}, mode="json"))
    if repetition_index is not None:
        resolved["run_repetition_index"] = repetition_index
    return resolved


def _resolve_requested_model(model_selection: ModelConfig) -> str:
    payload = model_selection.model_dump(mode="json")
    requested_model = payload.get("requested_model")
    if isinstance(requested_model, str) and requested_model:
        return requested_model

    openrouter_model = payload.get("openrouter_model")
    if isinstance(openrouter_model, str) and openrouter_model:
        return openrouter_model

    model_name = payload.get("model_name")
    provider = payload.get("provider")
    if isinstance(model_name, str) and model_name:
        if "/" in model_name:
            return model_name
        if isinstance(provider, str) and provider:
            return f"{provider}/{model_name}"
        return model_name

    return model_selection.model_id


def _resolve_messages_for_fingerprint(
    messages: list[Message],
) -> list[ResolvedMessageFingerprint]:
    resolved: list[ResolvedMessageFingerprint] = []
    for message in messages:
        if message.source is None:
            resolved.append(
                ResolvedMessageFingerprint(
                    role=message.role,
                    content=message.content,
                    name=message.name,
                )
            )
            continue
        resolved.extend(_load_source_messages(message))
    return resolved


def _load_source_messages(message: Message) -> list[ResolvedMessageFingerprint]:
    if message.source is None:
        raise ValueError("Message source was required but missing.")

    raw_content = message.source.path.read_text(encoding="utf-8")
    format_name = message.source.format or _infer_source_format(message.source.path)
    if format_name == "json":
        loaded = json.loads(raw_content)
    elif format_name == "yaml":
        loaded = yaml.safe_load(raw_content)
    else:
        raise ValueError(f"Unsupported message source format '{format_name}'.")

    if isinstance(loaded, str):
        return [
            ResolvedMessageFingerprint(
                role=message.role,
                content=loaded,
                name=message.name,
            )
        ]

    if isinstance(loaded, Mapping):
        return [_resolved_message_from_mapping(loaded, fallback_message=message)]

    if isinstance(loaded, list):
        resolved_messages: list[ResolvedMessageFingerprint] = []
        for item in loaded:
            if not isinstance(item, Mapping):
                raise ValueError(
                    f"Message source '{message.source.path}' must contain only mapping entries."
                )
            resolved_messages.append(_resolved_message_from_mapping(item, fallback_message=message))
        return resolved_messages

    raise ValueError(
        f"Message source '{message.source.path}' must contain a string, mapping, "
        "or list of mappings."
    )


def _resolved_message_from_mapping(
    payload: Mapping[str, Any],
    *,
    fallback_message: Message,
) -> ResolvedMessageFingerprint:
    role_value = payload.get("role", fallback_message.role)
    content_value = payload.get("content")
    name_value = payload.get("name", fallback_message.name)
    if content_value is not None and not isinstance(content_value, str):
        raise ValueError("Resolved message content must be a string when provided.")
    if not isinstance(role_value, str):
        raise ValueError("Resolved message role must be a string.")
    if name_value is not None and not isinstance(name_value, str):
        raise ValueError("Resolved message name must be a string when provided.")
    metadata = {
        key: value for key, value in payload.items() if key not in {"role", "content", "name"}
    }
    return ResolvedMessageFingerprint(
        role=role_value,
        content=content_value,
        name=name_value,
        metadata=_normalize_for_hash(metadata),
    )


def _infer_source_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    raise ValueError(f"Unable to infer message source format from '{path}'.")


def _attachment_fingerprint(path: Path) -> AttachmentFingerprint:
    data = path.read_bytes()
    return AttachmentFingerprint(
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        name=path.name,
    )


def _sha256_json(payload: dict[str, Any]) -> str:
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, Path):
        return value.name
    if isinstance(value, Mapping):
        normalized = {
            str(key): _normalize_for_hash(item) for key, item in value.items() if item is not None
        }
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_normalize_for_hash(item) for item in value]
    return value
