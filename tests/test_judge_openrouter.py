from __future__ import annotations

import json
from dataclasses import dataclass

from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterAssistantMessage,
    OpenRouterChatRequest,
    OpenRouterChatResponse,
    OpenRouterProviderError,
)
from personal_agent_eval.judge import JudgeInvocation, JudgeIterationStatus, OpenRouterJudgeClient


@dataclass
class FakeOpenRouterBackend:
    responses: list[OpenRouterChatResponse | Exception]
    requests: list[OpenRouterChatRequest] | None = None
    timeouts: list[float | None] | None = None

    def __post_init__(self) -> None:
        if self.requests is None:
            self.requests = []
        if self.timeouts is None:
            self.timeouts = []

    def create_chat_completion(
        self,
        chat_request: OpenRouterChatRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> OpenRouterChatResponse:
        assert self.requests is not None
        assert self.timeouts is not None
        self.requests.append(chat_request)
        self.timeouts.append(timeout_seconds)
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


def test_openrouter_judge_client_builds_raw_success_result() -> None:
    backend = FakeOpenRouterBackend(
        responses=[
            OpenRouterChatResponse(
                assistant_message=OpenRouterAssistantMessage(
                    role="assistant",
                    content=json.dumps(
                        {
                            "dimensions": {
                                "task": 4.0,
                                "process": 3.0,
                                "autonomy": 4.0,
                                "closeness": 5.0,
                                "efficiency": 2.0,
                                "spark": 3.0,
                            },
                            "summary": "Strong result.",
                            "evidence": {
                                "task": ["Completed the task."],
                                "process": ["Used a clear sequence."],
                                "autonomy": ["Acted without extra prompting."],
                                "closeness": ["Matched the request."],
                                "efficiency": ["A little verbose."],
                                "spark": ["Included one useful detail."],
                            },
                        }
                    ),
                ),
                provider_name="openai",
                provider_model_id="openai/gpt-5-mini-2026-04-01",
                request_id="req-judge-1",
                response_id="resp-judge-1",
                finish_reason="stop",
                native_finish_reason="stop",
                usage={
                    "input_tokens": 40,
                    "output_tokens": 20,
                    "total_tokens": 60,
                    "cache_write_tokens": 11,
                    "cost": 0.00125,
                },
            )
        ]
    )
    client = OpenRouterJudgeClient(backend)

    raw_result = client.run_once(
        JudgeInvocation(
            judge_name="rubric_judge",
            judge_model="openai/gpt-5-mini",
            repetition_index=0,
            attempt_index=0,
            messages=(
                {"role": "system", "content": "Return strict JSON."},
                {"role": "user", "content": '{"case_id":"example_case"}'},
            ),
            timeout_seconds=15.0,
        )
    )

    assert backend.requests is not None
    assert backend.timeouts == [15.0]
    assert backend.requests[0].model == "openai/gpt-5-mini"
    assert backend.requests[0].temperature == 0.0
    assert backend.requests[0].metadata["judge_name"] == "rubric_judge"
    assert raw_result.status is JudgeIterationStatus.SUCCESS
    assert raw_result.request_id == "req-judge-1"
    assert raw_result.response_id == "resp-judge-1"
    assert raw_result.provider_model_id == "openai/gpt-5-mini-2026-04-01"
    assert raw_result.usage["cost"] == 0.00125
    assert raw_result.parsed_response is not None
    assert raw_result.parsed_response["summary"] == "Strong result."


def test_openrouter_judge_client_maps_provider_failures() -> None:
    client = OpenRouterJudgeClient(
        FakeOpenRouterBackend(
            responses=[
                OpenRouterProviderError(
                    "Upstream rate limit.",
                    code="rate_limit",
                    retryable=True,
                    provider_code="rate_limit_exceeded",
                    status_code=429,
                )
            ]
        )
    )

    raw_result = client.run_once(
        JudgeInvocation(
            judge_name="rubric_judge",
            judge_model="openai/gpt-5-mini",
            repetition_index=1,
            attempt_index=0,
            messages=({"role": "user", "content": "payload"},),
        )
    )

    assert raw_result.status is JudgeIterationStatus.PROVIDER_ERROR
    assert raw_result.error_code == "rate_limit"
    assert raw_result.error_message == "Upstream rate limit."
    assert raw_result.warnings == ["retryable=True"]
