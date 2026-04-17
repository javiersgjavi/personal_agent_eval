"""Thin OpenRouter client wrapper for llm_probe runs."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import Message
from typing import Any, Protocol, cast
from urllib import error, request

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_SMOKE_MODEL = "minimax/minimax-m2.7"


@dataclass(frozen=True, slots=True)
class OpenRouterToolCall:
    """Provider-normalized tool call payload."""

    call_id: str
    tool_name: str
    raw_arguments: Any
    parsed_arguments: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OpenRouterAssistantMessage:
    """Provider-normalized assistant response."""

    role: str
    content: str | None
    name: str | None = None
    tool_calls: tuple[OpenRouterToolCall, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OpenRouterChatRequest:
    """Runner-facing request object for OpenRouter chat completions."""

    model: str
    messages: tuple[dict[str, Any], ...]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    tool_choice: str | dict[str, Any] | None = None
    tools: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Render the request as an OpenRouter JSON payload."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in self.messages],
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.tool_choice is not None:
            payload["tool_choice"] = self.tool_choice
        if self.tools:
            payload["tools"] = [dict(tool) for tool in self.tools]
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class OpenRouterChatResponse:
    """Runner-facing normalized OpenRouter response."""

    assistant_message: OpenRouterAssistantMessage
    provider_name: str | None = None
    provider_model_id: str | None = None
    request_id: str | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    native_finish_reason: str | None = None
    usage: dict[str, int | None] = field(default_factory=dict)
    raw_usage: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransportRequest:
    """HTTP request for the transport layer."""

    url: str
    headers: dict[str, str]
    json_body: dict[str, Any]
    timeout_seconds: float | None


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """HTTP response returned by the transport layer."""

    status_code: int
    headers: dict[str, str]
    json_body: dict[str, Any]


class OpenRouterTransport(Protocol):
    """Minimal transport interface to keep network concerns mockable."""

    def send(self, request: TransportRequest) -> TransportResponse:
        """Send one JSON request and return the decoded JSON body."""


class OpenRouterConfigurationError(ValueError):
    """Raised when the client is misconfigured before any provider call."""


class OpenRouterError(RuntimeError):
    """Base class for normalized OpenRouter execution failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        provider_code: str | None = None,
        status_code: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.provider_code = provider_code
        self.status_code = status_code
        self.metadata = metadata or {}


class OpenRouterTimeoutError(OpenRouterError):
    """Raised when the request times out."""


class OpenRouterProviderError(OpenRouterError):
    """Raised for provider or transport failures."""


class OpenRouterProtocolError(OpenRouterError):
    """Raised for malformed provider responses."""


class UrllibOpenRouterTransport:
    """Standard-library transport used by the default OpenRouter client."""

    def send(self, request_data: TransportRequest) -> TransportResponse:
        http_request = request.Request(
            url=request_data.url,
            data=json.dumps(request_data.json_body).encode("utf-8"),
            headers=request_data.headers,
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=request_data.timeout_seconds) as response:
                status_code = getattr(response, "status", response.getcode())
                headers = _headers_to_dict(response.headers)
                body = _load_json_body(response.read())
        except error.HTTPError as exc:
            headers = _headers_to_dict(exc.headers)
            body = _decode_error_body(exc)
            error_details = _extract_error_payload(body)
            raise OpenRouterProviderError(
                error_details.message,
                code=error_details.code,
                retryable=_is_retryable_status(exc.code),
                provider_code=error_details.provider_code,
                status_code=exc.code,
                metadata={"body": body, "headers": headers},
            ) from exc
        except error.URLError as exc:
            if isinstance(exc.reason, TimeoutError | socket.timeout):
                raise OpenRouterTimeoutError(
                    "The OpenRouter request timed out.",
                    code="timeout",
                    retryable=True,
                ) from exc
            raise OpenRouterProviderError(
                f"Unable to reach OpenRouter: {exc.reason}",
                code="transport_error",
                retryable=True,
                metadata={"reason": str(exc.reason)},
            ) from exc
        except TimeoutError as exc:
            raise OpenRouterTimeoutError(
                "The OpenRouter request timed out.",
                code="timeout",
                retryable=True,
            ) from exc

        return TransportResponse(status_code=status_code, headers=headers, json_body=body)


class OpenRouterClient:
    """Thin OpenRouter client facade used by the llm_probe runner."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_OPENROUTER_BASE_URL,
        transport: OpenRouterTransport | None = None,
        app_name: str = "personal_agent_eval",
    ) -> None:
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._transport = transport or UrllibOpenRouterTransport()
        self._app_name = app_name

    def create_chat_completion(
        self,
        chat_request: OpenRouterChatRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> OpenRouterChatResponse:
        """Create one OpenRouter chat completion."""
        if not self._api_key:
            raise OpenRouterConfigurationError(
                "OpenRouter API key is required. Set OPENROUTER_API_KEY or pass api_key."
            )

        response = self._transport.send(
            TransportRequest(
                url=f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": self._app_name,
                    "X-Title": self._app_name,
                },
                json_body=chat_request.to_payload(),
                timeout_seconds=timeout_seconds,
            )
        )
        return _parse_chat_response(response)


@dataclass(frozen=True, slots=True)
class _ErrorPayloadDetails:
    """Normalized provider error details extracted from a response body."""

    message: str
    code: str
    provider_code: str | None = None


def _parse_chat_response(response: TransportResponse) -> OpenRouterChatResponse:
    body = response.json_body
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenRouterProtocolError(
            "OpenRouter response did not include any choices.",
            code="invalid_response",
            retryable=False,
            metadata={"body": body},
        )

    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise OpenRouterProtocolError(
            "OpenRouter response choice was not a mapping.",
            code="invalid_response",
            retryable=False,
            metadata={"body": body},
        )

    message_payload = first_choice.get("message")
    if not isinstance(message_payload, Mapping):
        raise OpenRouterProtocolError(
            "OpenRouter response choice did not include a message object.",
            code="invalid_response",
            retryable=False,
            metadata={"body": body},
        )

    assistant_message = OpenRouterAssistantMessage(
        role=str(message_payload.get("role", "assistant")),
        content=_coerce_optional_string(message_payload.get("content")),
        name=_coerce_optional_string(message_payload.get("name")),
        tool_calls=_parse_tool_calls(message_payload.get("tool_calls")),
        metadata=_extract_message_metadata(message_payload),
    )

    usage_payload = body.get("usage")
    raw_usage = dict(usage_payload) if isinstance(usage_payload, Mapping) else None
    usage = _normalize_usage(usage_payload)
    provider_payload = body.get("provider")

    metadata = {
        "status_code": response.status_code,
        "created": body.get("created"),
    }
    if isinstance(provider_payload, Mapping):
        metadata["provider"] = dict(provider_payload)
    if response.headers:
        metadata["response_headers"] = dict(response.headers)

    provider_name = None
    if isinstance(provider_payload, Mapping):
        provider_name = _coerce_optional_string(
            provider_payload.get("name")
        ) or _coerce_optional_string(provider_payload.get("provider_name"))

    return OpenRouterChatResponse(
        assistant_message=assistant_message,
        provider_name=provider_name,
        provider_model_id=_coerce_optional_string(body.get("model")),
        request_id=response.headers.get("x-request-id"),
        response_id=_coerce_optional_string(body.get("id")),
        finish_reason=_coerce_optional_string(first_choice.get("finish_reason")),
        native_finish_reason=_coerce_optional_string(first_choice.get("native_finish_reason")),
        usage=usage,
        raw_usage=raw_usage,
        metadata=metadata,
    )


def _parse_tool_calls(payload: object) -> tuple[OpenRouterToolCall, ...]:
    if not isinstance(payload, list):
        return ()

    tool_calls: list[OpenRouterToolCall] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            continue
        item_mapping = cast(Mapping[str, Any], item)
        function_payload = item_mapping.get("function")
        function_mapping: Mapping[str, Any]
        if isinstance(function_payload, Mapping):
            function_mapping = cast(Mapping[str, Any], function_payload)
        else:
            function_mapping = {}
        raw_arguments = function_mapping.get("arguments")
        parsed_arguments = _parse_tool_arguments(raw_arguments)
        tool_calls.append(
            OpenRouterToolCall(
                call_id=_coerce_optional_string(item_mapping.get("id")) or f"tool_call_{index}",
                tool_name=_coerce_optional_string(function_mapping.get("name")) or "unknown",
                raw_arguments=raw_arguments,
                parsed_arguments=parsed_arguments,
                metadata={
                    str(key): value
                    for key, value in item_mapping.items()
                    if key not in {"id", "function"}
                },
            )
        )
    return tuple(tool_calls)


def _parse_tool_arguments(raw_arguments: object) -> dict[str, Any] | None:
    if isinstance(raw_arguments, Mapping):
        return {str(key): value for key, value in raw_arguments.items()}
    if not isinstance(raw_arguments, str):
        return None
    try:
        loaded = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        return loaded
    return None


def _normalize_usage(payload: object) -> dict[str, int | None]:
    if not isinstance(payload, Mapping):
        return {}
    payload_mapping = cast(Mapping[str, Any], payload)

    prompt_tokens = _coerce_optional_int(payload_mapping.get("prompt_tokens"))
    completion_tokens = _coerce_optional_int(payload_mapping.get("completion_tokens"))
    total_tokens = _coerce_optional_int(payload_mapping.get("total_tokens"))
    reasoning_tokens = _coerce_optional_int(payload_mapping.get("reasoning_tokens"))
    cached_tokens = None

    prompt_details = payload_mapping.get("prompt_tokens_details")
    if isinstance(prompt_details, Mapping):
        prompt_details_mapping = cast(Mapping[str, Any], prompt_details)
        cached_tokens = _coerce_optional_int(prompt_details_mapping.get("cached_tokens"))

    return {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_input_tokens": cached_tokens,
    }


def _extract_message_metadata(message_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in message_payload.items()
        if key not in {"role", "content", "name", "tool_calls"}
    }


def _load_json_body(raw_bytes: bytes) -> dict[str, Any]:
    try:
        loaded = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenRouterProtocolError(
            "OpenRouter returned a non-JSON response body.",
            code="invalid_response",
            retryable=False,
        ) from exc
    if not isinstance(loaded, dict):
        raise OpenRouterProtocolError(
            "OpenRouter returned a JSON response that was not an object.",
            code="invalid_response",
            retryable=False,
            metadata={"body_type": type(loaded).__name__},
        )
    return loaded


def _decode_error_body(exc: error.HTTPError) -> dict[str, Any]:
    try:
        raw_body = exc.read()
    except OSError:
        raw_body = b""
    if not raw_body:
        return {}
    try:
        loaded = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw_body": raw_body.decode("utf-8", errors="replace")}
    if isinstance(loaded, dict):
        return loaded
    return {"raw_body": loaded}


def _extract_error_payload(body: Mapping[str, Any]) -> _ErrorPayloadDetails:
    error_payload = body.get("error")
    if isinstance(error_payload, Mapping):
        message = (
            _coerce_optional_string(error_payload.get("message")) or "OpenRouter returned an error."
        )
        code = _coerce_optional_string(error_payload.get("code")) or "provider_error"
        provider_code = _coerce_optional_string(error_payload.get("type"))
        return _ErrorPayloadDetails(
            message=message,
            code=code,
            provider_code=provider_code,
        )
    return _ErrorPayloadDetails(
        message="OpenRouter returned an error.",
        code="provider_error",
    )


def _headers_to_dict(headers: Message | Mapping[str, str] | None) -> dict[str, str]:
    if headers is None:
        return {}
    if isinstance(headers, Mapping):
        return {str(key).lower(): str(value) for key, value in headers.items()}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _coerce_optional_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_optional_int(value: object) -> int | None:
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
