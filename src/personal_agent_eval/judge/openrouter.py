"""OpenRouter-backed judge client wrapper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterChatRequest,
    OpenRouterChatResponse,
    OpenRouterClient,
    OpenRouterConfigurationError,
    OpenRouterError,
    OpenRouterProviderError,
    OpenRouterTimeoutError,
)
from personal_agent_eval.judge.models import JudgeIterationStatus, RawJudgeRunResult


@dataclass(frozen=True, slots=True)
class JudgeInvocation:
    """A single provider call for one judge attempt."""

    judge_name: str
    judge_model: str
    repetition_index: int
    attempt_index: int
    messages: tuple[dict[str, str], ...]
    prompt_payload: dict[str, object] | None = None
    timeout_seconds: float | None = None
    request_options: dict[str, object] | None = None

    @property
    def raw_result_ref(self) -> str:
        """Return the stable raw result reference for the attempt."""
        return f"{self.judge_name}:repetition:{self.repetition_index}:attempt:{self.attempt_index}"


class OpenRouterJudgeBackend(Protocol):
    """Subset of the OpenRouter client used by judge orchestration."""

    def create_chat_completion(
        self,
        chat_request: OpenRouterChatRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> OpenRouterChatResponse:
        """Create one chat completion."""


class OpenRouterJudgeClient:
    """Thin adapter that maps OpenRouter calls onto raw judge attempt results."""

    def __init__(self, client: OpenRouterJudgeBackend | None = None) -> None:
        self._client = client or OpenRouterClient()

    def run_once(self, invocation: JudgeInvocation) -> RawJudgeRunResult:
        """Execute one judge attempt via OpenRouter."""
        request_messages = [dict(message) for message in invocation.messages]

        try:
            request_options = dict(invocation.request_options or {})
            temperature = request_options.pop("temperature", 0.0)
            response = self._client.create_chat_completion(
                OpenRouterChatRequest(
                    model=invocation.judge_model,
                    messages=tuple(request_messages),
                    temperature=temperature if isinstance(temperature, int | float) else 0.0,
                    metadata={
                        "judge_name": invocation.judge_name,
                        "repetition_index": invocation.repetition_index,
                        "attempt_index": invocation.attempt_index,
                    },
                    extra_body=request_options,
                ),
                timeout_seconds=invocation.timeout_seconds,
            )
        except OpenRouterTimeoutError as exc:
            return self._error_result(
                invocation=invocation,
                status=JudgeIterationStatus.TIMED_OUT,
                exc=exc,
                request_messages=request_messages,
            )
        except OpenRouterProviderError as exc:
            return self._error_result(
                invocation=invocation,
                status=JudgeIterationStatus.PROVIDER_ERROR,
                exc=exc,
                request_messages=request_messages,
            )
        except OpenRouterConfigurationError as exc:
            return RawJudgeRunResult(
                raw_result_ref=invocation.raw_result_ref,
                judge_name=invocation.judge_name,
                judge_model=invocation.judge_model,
                repetition_index=invocation.repetition_index,
                attempt_index=invocation.attempt_index,
                status=JudgeIterationStatus.FAILED,
                request_messages=request_messages,
                prompt_payload=invocation.prompt_payload,
                error_code="configuration_error",
                error_message=str(exc),
            )
        except OpenRouterError as exc:
            return self._error_result(
                invocation=invocation,
                status=JudgeIterationStatus.FAILED,
                exc=exc,
                request_messages=request_messages,
            )
        except Exception as exc:
            return RawJudgeRunResult(
                raw_result_ref=invocation.raw_result_ref,
                judge_name=invocation.judge_name,
                judge_model=invocation.judge_model,
                repetition_index=invocation.repetition_index,
                attempt_index=invocation.attempt_index,
                status=JudgeIterationStatus.FAILED,
                request_messages=request_messages,
                prompt_payload=invocation.prompt_payload,
                error_code="unexpected_error",
                error_message=f"{exc.__class__.__name__}: {exc}",
            )

        parsed_response: dict[str, object] | None = None
        response_content = response.assistant_message.content
        if isinstance(response_content, str):
            try:
                loaded = json.loads(response_content)
            except json.JSONDecodeError:
                parsed_response = None
            else:
                if isinstance(loaded, dict):
                    parsed_response = loaded

        return RawJudgeRunResult(
            raw_result_ref=invocation.raw_result_ref,
            judge_name=invocation.judge_name,
            judge_model=invocation.judge_model,
            repetition_index=invocation.repetition_index,
            attempt_index=invocation.attempt_index,
            status=JudgeIterationStatus.SUCCESS,
            request_messages=request_messages,
            prompt_payload=invocation.prompt_payload,
            response_content=response_content,
            parsed_response=parsed_response,
            provider_name=response.provider_name,
            provider_model_id=response.provider_model_id,
            request_id=response.request_id,
            response_id=response.response_id,
            finish_reason=response.finish_reason,
            native_finish_reason=response.native_finish_reason,
            usage=response.usage,
        )

    def _error_result(
        self,
        *,
        invocation: JudgeInvocation,
        status: JudgeIterationStatus,
        exc: OpenRouterError,
        request_messages: list[dict[str, str]],
    ) -> RawJudgeRunResult:
        return RawJudgeRunResult(
            raw_result_ref=invocation.raw_result_ref,
            judge_name=invocation.judge_name,
            judge_model=invocation.judge_model,
            repetition_index=invocation.repetition_index,
            attempt_index=invocation.attempt_index,
            status=status,
            request_messages=request_messages,
            prompt_payload=invocation.prompt_payload,
            error_code=exc.code,
            error_message=str(exc),
            warnings=[f"retryable={exc.retryable}"],
        )
