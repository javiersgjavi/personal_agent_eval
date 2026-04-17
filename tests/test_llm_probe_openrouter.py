from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterChatRequest,
    OpenRouterClient,
    OpenRouterProtocolError,
    TransportRequest,
    TransportResponse,
)


@dataclass
class FakeTransport:
    response: TransportResponse
    last_request: TransportRequest | None = None

    def send(self, request: TransportRequest) -> TransportResponse:
        self.last_request = request
        return self.response


def test_openrouter_client_builds_request_and_normalizes_response() -> None:
    transport = FakeTransport(
        response=TransportResponse(
            status_code=200,
            headers={"x-request-id": "req-123"},
            json_body={
                "id": "resp-456",
                "model": "openai/gpt-5-mini-2026-04-01",
                "provider": {"name": "openai"},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "native_finish_reason": "end_turn",
                        "message": {
                            "role": "assistant",
                            "content": "Hello",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"city":"Madrid"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                    "total_tokens": 17,
                    "reasoning_tokens": 2,
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            },
        )
    )
    client = OpenRouterClient(api_key="test-key", transport=transport)

    response = client.create_chat_completion(
        OpenRouterChatRequest(
            model="openai/gpt-5-mini",
            messages=({"role": "user", "content": "Hi"},),
            temperature=0.1,
        ),
        timeout_seconds=12.0,
    )

    assert transport.last_request is not None
    assert transport.last_request.url.endswith("/chat/completions")
    assert transport.last_request.headers["Authorization"] == "Bearer test-key"
    assert transport.last_request.json_body["model"] == "openai/gpt-5-mini"
    assert response.provider_name == "openai"
    assert response.provider_model_id == "openai/gpt-5-mini-2026-04-01"
    assert response.request_id == "req-123"
    assert response.response_id == "resp-456"
    assert response.finish_reason == "stop"
    assert response.native_finish_reason == "end_turn"
    assert response.usage == {
        "input_tokens": 12,
        "output_tokens": 5,
        "total_tokens": 17,
        "reasoning_tokens": 2,
        "cached_input_tokens": 3,
    }
    assert response.assistant_message.tool_calls[0].parsed_arguments == {"city": "Madrid"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": "not-a-mapping"}]},
    ],
)
def test_openrouter_client_rejects_malformed_response_bodies(body: dict[str, Any]) -> None:
    client = OpenRouterClient(
        api_key="test-key",
        transport=FakeTransport(
            response=TransportResponse(status_code=200, headers={}, json_body=body)
        ),
    )

    with pytest.raises(OpenRouterProtocolError, match="OpenRouter response"):
        client.create_chat_completion(
            OpenRouterChatRequest(model="openai/gpt-5-mini", messages=tuple())
        )
