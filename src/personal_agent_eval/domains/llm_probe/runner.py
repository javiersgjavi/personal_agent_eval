"""llm_probe runner orchestration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol, cast

import yaml

from personal_agent_eval.artifacts import (
    LlmExecutionParameters,
    NormalizedUsage,
    ProviderMetadata,
    RunArtifact,
    RunArtifactIdentity,
    RunError,
    RunRequestMetadata,
    RunStatus,
    RunTiming,
)
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    RunnerTraceEvent,
    ToolCallTraceEvent,
    TraceEvent,
    UsageMetadata,
)
from personal_agent_eval.config.run_profile import RunProfileConfig
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import Message, TestConfig
from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterChatRequest,
    OpenRouterChatResponse,
    OpenRouterConfigurationError,
    OpenRouterError,
)

DEFAULT_RETRIES = 5
MessageRole = Literal["system", "user", "assistant", "tool"]


class ChatCompletionClient(Protocol):
    """Runner-facing subset of the OpenRouter client."""

    def create_chat_completion(
        self,
        chat_request: OpenRouterChatRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> OpenRouterChatResponse:
        """Execute one chat completion."""


@dataclass(frozen=True, slots=True)
class ResolvedInputMessage:
    """One fully-resolved initial conversation message."""

    role: MessageRole
    content: str | None
    name: str | None = None
    metadata: dict[str, Any] | None = None

    def to_request_payload(self) -> dict[str, Any]:
        """Render the message for the provider request payload."""
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        if self.name is not None:
            payload["name"] = self.name
        if self.metadata:
            payload.update(self.metadata)
        return payload


def run_llm_probe_case(
    *,
    run_id: str,
    suite_id: str,
    case_config: TestConfig,
    run_profile: RunProfileConfig,
    model_selection: ModelConfig,
    client: ChatCompletionClient,
    queued_at: datetime | None = None,
) -> RunArtifact:
    """Run one llm_probe case and return the canonical run artifact."""
    queued_timestamp = queued_at or datetime.now(UTC)
    started_at = datetime.now(UTC)
    started_monotonic = perf_counter()

    requested_model = _resolve_requested_model(model_selection)
    execution_settings = _resolve_execution_settings(
        case_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
    )
    request_metadata = _build_request_metadata(
        case_config=case_config, model_selection=model_selection
    )

    request_metadata["resolved_messages"] = []
    resolved_retries = _coerce_int(execution_settings.get("retries"))
    request_model = RunRequestMetadata(
        requested_model=requested_model,
        gateway="openrouter",
        execution_parameters=LlmExecutionParameters(
            temperature=_coerce_float(execution_settings.get("temperature")),
            top_p=_coerce_float(execution_settings.get("top_p")),
            max_tokens=_coerce_int(execution_settings.get("max_tokens")),
            seed=_coerce_int(execution_settings.get("seed")),
            max_turns=_coerce_int(execution_settings.get("max_turns")),
            timeout_seconds=_coerce_float(execution_settings.get("timeout_seconds")),
            retries=DEFAULT_RETRIES if resolved_retries is None else resolved_retries,
            tool_choice=_coerce_tool_choice(execution_settings.get("tool_choice")),
        ),
        metadata=request_metadata,
    )

    trace_builder = _TraceBuilder()
    provider_metadata = ProviderMetadata(gateway="openrouter")

    try:
        resolved_messages = _resolve_messages(case_config.input.messages)
    except OSError as exc:
        return _build_terminal_artifact(
            identity=_build_identity(
                run_id=run_id,
                suite_id=suite_id,
                case_config=case_config,
                run_profile=run_profile,
            ),
            status=RunStatus.FAILED,
            timing=_build_timing(
                queued_at=queued_timestamp,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
            request_model=request_model,
            trace=trace_builder.events,
            provider=provider_metadata,
            error=RunError(
                code="message_resolution_failed",
                message=f"Unable to resolve case messages: {exc.strerror or exc!s}",
                error_type=type(exc).__name__,
                retryable=False,
                metadata={"path": getattr(exc, "filename", None)},
            ),
            runner_metadata={"attempt_count": 0, "model_id": model_selection.model_id},
        )
    except ValueError as exc:
        return _build_terminal_artifact(
            identity=_build_identity(
                run_id=run_id,
                suite_id=suite_id,
                case_config=case_config,
                run_profile=run_profile,
            ),
            status=RunStatus.INVALID,
            timing=_build_timing(
                queued_at=queued_timestamp,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
            request_model=request_model,
            trace=trace_builder.events,
            provider=provider_metadata,
            error=RunError(
                code="invalid_messages",
                message=str(exc),
                error_type=type(exc).__name__,
                retryable=False,
            ),
            runner_metadata={"attempt_count": 0, "model_id": model_selection.model_id},
        )

    request_model.metadata["resolved_messages"] = [
        {
            "role": message.role,
            "content": message.content,
            "name": message.name,
        }
        for message in resolved_messages
    ]

    for message in resolved_messages:
        trace_builder.add_message(
            role=_validate_message_role(message.role),
            content=message.content,
            name=message.name,
            metadata=message.metadata or {},
        )

    chat_request = OpenRouterChatRequest(
        model=requested_model,
        messages=tuple(message.to_request_payload() for message in resolved_messages),
        temperature=request_model.execution_parameters.temperature,
        top_p=request_model.execution_parameters.top_p,
        max_tokens=request_model.execution_parameters.max_tokens,
        seed=request_model.execution_parameters.seed,
        tool_choice=request_model.execution_parameters.tool_choice,
    )

    retries = (
        DEFAULT_RETRIES
        if request_model.execution_parameters.retries is None
        else request_model.execution_parameters.retries
    )
    attempt_count = 0

    for attempt_index in range(retries + 1):
        attempt_count = attempt_index + 1
        trace_builder.add_runner_event(
            name="provider_attempt",
            detail=f"Starting provider attempt {attempt_count}.",
            metadata={"attempt": attempt_count},
        )
        try:
            response = client.create_chat_completion(
                chat_request,
                timeout_seconds=request_model.execution_parameters.timeout_seconds,
            )
        except OpenRouterConfigurationError as exc:
            return _build_terminal_artifact(
                identity=_build_identity(
                    run_id=run_id,
                    suite_id=suite_id,
                    case_config=case_config,
                    run_profile=run_profile,
                ),
                status=RunStatus.FAILED,
                timing=_build_timing(
                    queued_at=queued_timestamp,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
                request_model=request_model,
                trace=trace_builder.events,
                provider=provider_metadata,
                error=RunError(
                    code="runner_configuration_error",
                    message=str(exc),
                    error_type=type(exc).__name__,
                    retryable=False,
                ),
                runner_metadata={
                    "attempt_count": attempt_count,
                    "model_id": model_selection.model_id,
                },
            )
        except OpenRouterError as exc:
            trace_builder.add_runner_event(
                name="provider_error",
                detail=str(exc),
                metadata={"attempt": attempt_count, "code": exc.code, "retryable": exc.retryable},
            )
            exhausted = attempt_index >= retries or not exc.retryable
            if not exhausted:
                trace_builder.add_runner_event(
                    name="retry_scheduled",
                    detail=f"Retrying after attempt {attempt_count}.",
                    metadata={"attempt": attempt_count + 1},
                )
                continue
            status = RunStatus.TIMED_OUT if exc.code == "timeout" else RunStatus.PROVIDER_ERROR
            return _build_terminal_artifact(
                identity=_build_identity(
                    run_id=run_id,
                    suite_id=suite_id,
                    case_config=case_config,
                    run_profile=run_profile,
                ),
                status=status,
                timing=_build_timing(
                    queued_at=queued_timestamp,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
                request_model=request_model,
                trace=trace_builder.events,
                provider=provider_metadata,
                error=RunError(
                    code=exc.code,
                    message=str(exc),
                    error_type=type(exc).__name__,
                    retryable=exc.retryable,
                    provider_code=exc.provider_code,
                    metadata={
                        "attempt_count": attempt_count,
                        **exc.metadata,
                    },
                ),
                runner_metadata={
                    "attempt_count": attempt_count,
                    "model_id": model_selection.model_id,
                },
            )
        except Exception as exc:
            return _build_terminal_artifact(
                identity=_build_identity(
                    run_id=run_id,
                    suite_id=suite_id,
                    case_config=case_config,
                    run_profile=run_profile,
                ),
                status=RunStatus.FAILED,
                timing=_build_timing(
                    queued_at=queued_timestamp,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
                request_model=request_model,
                trace=trace_builder.events,
                provider=provider_metadata,
                error=RunError(
                    code="runner_execution_failed",
                    message=str(exc),
                    error_type=type(exc).__name__,
                    retryable=False,
                ),
                runner_metadata={
                    "attempt_count": attempt_count,
                    "model_id": model_selection.model_id,
                },
            )

        provider_metadata = ProviderMetadata(
            gateway="openrouter",
            provider_name=response.provider_name,
            provider_model_id=response.provider_model_id,
            request_id=response.request_id,
            response_id=response.response_id,
            finish_reason=response.finish_reason,
            native_finish_reason=response.native_finish_reason,
            metadata=dict(response.metadata),
        )

        trace_builder.add_message(
            role=_validate_message_role(response.assistant_message.role),
            content=response.assistant_message.content,
            name=response.assistant_message.name,
            metadata=response.assistant_message.metadata,
        )
        for tool_call in response.assistant_message.tool_calls:
            trace_builder.add_tool_call(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                raw_arguments=tool_call.raw_arguments,
                parsed_arguments=tool_call.parsed_arguments,
                metadata=tool_call.metadata,
            )

        usage = _build_usage(response)
        final_output = response.assistant_message.content
        if final_output is None or not final_output.strip():
            error_code = (
                "tool_calls_not_supported"
                if response.assistant_message.tool_calls
                else "empty_output"
            )
            error_message = (
                "The provider returned tool calls without a final assistant message."
                if response.assistant_message.tool_calls
                else "The provider returned an empty assistant message."
            )
            return _build_terminal_artifact(
                identity=_build_identity(
                    run_id=run_id,
                    suite_id=suite_id,
                    case_config=case_config,
                    run_profile=run_profile,
                ),
                status=RunStatus.INVALID,
                timing=_build_timing(
                    queued_at=queued_timestamp,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
                request_model=request_model,
                trace=trace_builder.events,
                provider=provider_metadata,
                usage=usage,
                error=RunError(
                    code=error_code,
                    message=error_message,
                    error_type="InvalidProviderOutput",
                    retryable=False,
                    metadata={"attempt_count": attempt_count},
                ),
                runner_metadata={
                    "attempt_count": attempt_count,
                    "model_id": model_selection.model_id,
                },
            )

        trace_builder.add_final_output(final_output)
        return RunArtifact(
            identity=_build_identity(
                run_id=run_id,
                suite_id=suite_id,
                case_config=case_config,
                run_profile=run_profile,
            ),
            status=RunStatus.SUCCESS,
            timing=_build_timing(
                queued_at=queued_timestamp,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
            request=request_model,
            provider=provider_metadata,
            usage=usage,
            trace=trace_builder.events,
            runner_metadata={
                "attempt_count": attempt_count,
                "model_id": model_selection.model_id,
                "tool_capable": True,
            },
        )

    raise AssertionError("Unreachable retry loop exit.")


def _build_identity(
    *, run_id: str, suite_id: str, case_config: TestConfig, run_profile: RunProfileConfig
) -> RunArtifactIdentity:
    return RunArtifactIdentity(
        schema_version=1,
        run_id=run_id,
        case_id=case_config.case_id,
        suite_id=suite_id,
        run_profile_id=run_profile.run_profile_id,
        runner_type="llm_probe",
    )


def _build_usage(response: OpenRouterChatResponse) -> UsageMetadata:
    return UsageMetadata(
        normalized=NormalizedUsage(
            input_tokens=_coerce_int(response.usage.get("input_tokens")),
            output_tokens=_coerce_int(response.usage.get("output_tokens")),
            total_tokens=_coerce_int(response.usage.get("total_tokens")),
            reasoning_tokens=_coerce_int(response.usage.get("reasoning_tokens")),
            cached_input_tokens=_coerce_int(response.usage.get("cached_input_tokens")),
        ),
        raw_provider_usage=response.raw_usage,
    )


def _build_terminal_artifact(
    *,
    identity: RunArtifactIdentity,
    status: RunStatus,
    timing: RunTiming,
    request_model: RunRequestMetadata,
    trace: list[TraceEvent],
    provider: ProviderMetadata,
    error: RunError,
    runner_metadata: dict[str, Any],
    usage: UsageMetadata | None = None,
) -> RunArtifact:
    return RunArtifact(
        identity=identity,
        status=status,
        timing=timing,
        request=request_model,
        provider=provider,
        usage=usage or UsageMetadata(),
        trace=trace,
        error=error,
        runner_metadata=runner_metadata,
    )


def _build_timing(
    *,
    queued_at: datetime,
    started_at: datetime,
    started_monotonic: float,
) -> RunTiming:
    completed_at = datetime.now(UTC)
    return RunTiming(
        queued_at=queued_at,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=max(0.0, perf_counter() - started_monotonic),
    )


def _resolve_execution_settings(
    *,
    case_config: TestConfig,
    run_profile: RunProfileConfig,
    model_selection: ModelConfig,
) -> dict[str, Any]:
    resolved = dict(run_profile.runner_defaults)
    resolved.update(run_profile.model_overrides.get(model_selection.model_id, {}))
    resolved.update(case_config.runner.model_dump(exclude={"type"}))
    return resolved


def _build_request_metadata(
    *,
    case_config: TestConfig,
    model_selection: ModelConfig,
) -> dict[str, Any]:
    return {
        "case_metadata": dict(case_config.metadata),
        "input_context": dict(case_config.input.context),
        "attachments": [str(path) for path in case_config.input.attachments],
        "requested_runner_config": case_config.runner.model_dump(),
        "model_selection": model_selection.model_dump(),
    }


def _resolve_requested_model(model_selection: ModelConfig) -> str:
    payload = model_selection.model_dump()
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


def _resolve_messages(messages: list[Message]) -> list[ResolvedInputMessage]:
    resolved: list[ResolvedInputMessage] = []
    for message in messages:
        if message.source is None:
            resolved.append(
                ResolvedInputMessage(
                    role=_validate_message_role(message.role),
                    content=message.content,
                    name=message.name,
                )
            )
            continue
        resolved.extend(_load_source_messages(message))
    return resolved


def _load_source_messages(message: Message) -> list[ResolvedInputMessage]:
    source = message.source
    if source is None:
        raise ValueError("Message source was required but missing.")

    raw_content = source.path.read_text(encoding="utf-8")
    format_name = source.format or _infer_source_format(source.path)
    if format_name == "json":
        loaded = json.loads(raw_content)
    elif format_name == "yaml":
        loaded = yaml.safe_load(raw_content)
    else:
        raise ValueError(f"Unsupported message source format '{format_name}'.")

    if isinstance(loaded, str):
        return [
            ResolvedInputMessage(
                role=_validate_message_role(message.role),
                content=loaded,
                name=message.name,
            )
        ]

    if isinstance(loaded, Mapping):
        return [_resolved_message_from_mapping(loaded, fallback_message=message)]

    if isinstance(loaded, list):
        resolved_messages: list[ResolvedInputMessage] = []
        for item in loaded:
            if not isinstance(item, Mapping):
                raise ValueError(
                    f"Message source '{source.path}' must contain only mapping entries."
                )
            resolved_messages.append(_resolved_message_from_mapping(item, fallback_message=message))
        return resolved_messages

    raise ValueError(
        f"Message source '{source.path}' must contain a string, mapping, or list of mappings."
    )


def _resolved_message_from_mapping(
    payload: Mapping[str, Any],
    *,
    fallback_message: Message,
) -> ResolvedInputMessage:
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
    return ResolvedInputMessage(
        role=_validate_message_role(role_value),
        content=content_value,
        name=name_value,
        metadata=metadata or None,
    )


def _infer_source_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    return "yaml"


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_tool_choice(value: object) -> str | dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return None


def _validate_message_role(value: str) -> MessageRole:
    if value not in {"system", "user", "assistant", "tool"}:
        raise ValueError("Resolved message role must be one of: system, user, assistant, tool.")
    return cast(MessageRole, value)


class _TraceBuilder:
    """Append-only builder for contiguous trace events."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def add_message(
        self,
        *,
        role: MessageRole,
        content: str | None,
        name: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.events.append(
            MessageTraceEvent(
                sequence=len(self.events),
                event_type="message",
                role=role,
                content=content,
                name=name,
                metadata=metadata,
            )
        )

    def add_runner_event(self, *, name: str, detail: str | None, metadata: dict[str, Any]) -> None:
        self.events.append(
            RunnerTraceEvent(
                sequence=len(self.events),
                event_type="runner",
                name=name,
                detail=detail,
                metadata=metadata,
            )
        )

    def add_tool_call(
        self,
        *,
        call_id: str,
        tool_name: str,
        raw_arguments: Any,
        parsed_arguments: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> None:
        self.events.append(
            ToolCallTraceEvent(
                sequence=len(self.events),
                event_type="tool_call",
                call_id=call_id,
                tool_name=tool_name,
                raw_arguments=raw_arguments,
                parsed_arguments=parsed_arguments,
                metadata=metadata,
            )
        )

    def add_final_output(self, content: str) -> None:
        self.events.append(
            FinalOutputTraceEvent(
                sequence=len(self.events),
                event_type="final_output",
                content=content,
            )
        )
