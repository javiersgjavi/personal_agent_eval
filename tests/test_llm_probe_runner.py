from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personal_agent_eval.artifacts import RunStatus
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    RunnerTraceEvent,
)
from personal_agent_eval.config import (
    RunProfileConfig,
    load_run_profile,
    load_suite_config,
    load_test_config,
)
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import TestConfig as CaseConfigModel
from personal_agent_eval.domains.llm_probe.openrouter import (
    OpenRouterAssistantMessage,
    OpenRouterChatRequest,
    OpenRouterChatResponse,
    OpenRouterProviderError,
    OpenRouterToolCall,
)
from personal_agent_eval.domains.llm_probe.runner import run_llm_probe_case

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


@dataclass
class FakeClient:
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


def _build_success_response(*, content: str = "Summary ready.") -> OpenRouterChatResponse:
    return OpenRouterChatResponse(
        assistant_message=OpenRouterAssistantMessage(role="assistant", content=content),
        provider_name="openai",
        provider_model_id="openai/gpt-example",
        request_id="req-1",
        response_id="resp-1",
        finish_reason="stop",
        native_finish_reason="stop",
        usage={
            "input_tokens": 20,
            "output_tokens": 8,
            "total_tokens": 28,
            "reasoning_tokens": 1,
            "cached_input_tokens": 2,
            "cache_write_tokens": 5,
            "cost": 0.00042,
        },
        raw_usage={"prompt_tokens": 20, "completion_tokens": 8, "cost": "0.00042"},
        metadata={"region": "us"},
    )


def _load_case_and_profile() -> tuple[CaseConfigModel, RunProfileConfig, ModelConfig]:
    case_config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "default.yaml")
    suite_config = load_suite_config(FIXTURES_ROOT / "configs" / "suites" / "example_suite.yaml")
    return case_config, run_profile, suite_config.models[0]


def test_llm_probe_runner_builds_success_artifact_from_case_profile_and_model() -> None:
    case_config, run_profile, model_selection = _load_case_and_profile()
    client = FakeClient(responses=[_build_success_response()])

    artifact = run_llm_probe_case(
        run_id="run-1001",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        client=client,
    )

    assert artifact.status is RunStatus.SUCCESS
    assert artifact.request.requested_model == "openai/gpt-example"
    assert artifact.request.gateway == "openrouter"
    assert artifact.request.execution_parameters.temperature == 0.0
    assert artifact.request.execution_parameters.timeout_seconds == 30.0
    assert artifact.request.execution_parameters.retries == 5
    assert artifact.request.metadata["attachments"] == [
        str(
            (
                FIXTURES_ROOT / "configs" / "cases" / "example_case" / "artifacts" / "prompt.txt"
            ).resolve()
        )
    ]
    assert artifact.provider.provider_name == "openai"
    assert artifact.provider.provider_model_id == "openai/gpt-example"
    assert artifact.usage.normalized.total_tokens == 28
    assert artifact.usage.normalized.cache_write_tokens == 5
    assert artifact.usage.cost_usd == 0.00042
    assert isinstance(artifact.trace[0], MessageTraceEvent)
    assert artifact.trace[0].role == "system"
    assert isinstance(artifact.trace[1], MessageTraceEvent)
    assert artifact.trace[1].role == "system"
    assert isinstance(artifact.trace[2], MessageTraceEvent)
    assert artifact.trace[2].role == "user"
    assert isinstance(artifact.trace[-1], FinalOutputTraceEvent)
    assert artifact.trace[-1].content == "Summary ready."
    assert artifact.runner_metadata["attempt_count"] == 1
    assert client.requests is not None
    assert client.requests[0].messages[0]["role"] == "system"
    assert client.requests[0].messages[1]["role"] == "system"
    assert client.requests[0].messages[2]["role"] == "user"


def test_llm_probe_runner_returns_provider_error_artifact() -> None:
    case_config, run_profile, model_selection = _load_case_and_profile()
    client = FakeClient(
        responses=[
            OpenRouterProviderError(
                "Rate limited by provider.",
                code="rate_limit",
                retryable=False,
                provider_code="rate_limit_exceeded",
                status_code=429,
            )
        ]
    )

    artifact = run_llm_probe_case(
        run_id="run-1002",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        client=client,
    )

    assert artifact.status is RunStatus.PROVIDER_ERROR
    assert artifact.error is not None
    assert artifact.error.code == "rate_limit"
    assert artifact.error.provider_code == "rate_limit_exceeded"
    assert artifact.error.retryable is False
    assert artifact.runner_metadata["attempt_count"] == 1


def test_llm_probe_runner_marks_empty_provider_output_as_invalid() -> None:
    case_config, run_profile, model_selection = _load_case_and_profile()
    client = FakeClient(
        responses=[
            OpenRouterChatResponse(
                assistant_message=OpenRouterAssistantMessage(role="assistant", content="   "),
            )
        ]
    )

    artifact = run_llm_probe_case(
        run_id="run-1003",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        client=client,
    )

    assert artifact.status is RunStatus.INVALID
    assert artifact.error is not None
    assert artifact.error.code == "empty_output"
    assert artifact.trace[-1].event_type == "message"


def test_llm_probe_runner_retries_retryable_provider_errors() -> None:
    case_config, run_profile, model_selection = _load_case_and_profile()
    client = FakeClient(
        responses=[
            OpenRouterProviderError(
                "Temporary upstream failure.",
                code="upstream_unavailable",
                retryable=True,
                status_code=503,
            ),
            _build_success_response(content="Recovered response."),
        ]
    )

    artifact = run_llm_probe_case(
        run_id="run-1004",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        client=client,
    )

    assert artifact.status is RunStatus.SUCCESS
    assert artifact.runner_metadata["attempt_count"] == 2
    assert client.requests is not None
    assert len(client.requests) == 2
    assert any(
        isinstance(event, RunnerTraceEvent) and event.name == "retry_scheduled"
        for event in artifact.trace
    )


def test_llm_probe_runner_marks_tool_only_response_as_invalid() -> None:
    case_config, run_profile, model_selection = _load_case_and_profile()
    client = FakeClient(
        responses=[
            OpenRouterChatResponse(
                assistant_message=OpenRouterAssistantMessage(
                    role="assistant",
                    content=None,
                    tool_calls=(
                        OpenRouterToolCall(
                            call_id="call_1",
                            tool_name="lookup",
                            raw_arguments='{"city":"Madrid"}',
                            parsed_arguments={"city": "Madrid"},
                        ),
                    ),
                ),
            )
        ]
    )

    artifact = run_llm_probe_case(
        run_id="run-1005",
        suite_id="example_suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        client=client,
    )

    assert artifact.status is RunStatus.INVALID
    assert artifact.error is not None
    assert artifact.error.code == "tool_calls_not_supported"
