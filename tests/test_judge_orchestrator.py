from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personal_agent_eval.artifacts import (
    OpenClawRunEvidence,
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
    with_openclaw_run_evidence,
)
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    ToolCallTraceEvent,
    ToolResultTraceEvent,
    TraceEvent,
)
from personal_agent_eval.config import load_evaluation_profile
from personal_agent_eval.config.test_config import load_test_config
from personal_agent_eval.judge import (
    JudgeIterationStatus,
    JudgeOrchestrator,
    RawJudgeRunResult,
    build_judge_messages,
    build_judge_prompt_bundle,
)
from personal_agent_eval.judge.system_prompt import resolve_judge_system_prompt_text

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"
_FIXTURE_EVAL_PROFILE = load_evaluation_profile(
    FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
)
_FIXTURE_JUDGE_SYSTEM_PROMPT = resolve_judge_system_prompt_text(_FIXTURE_EVAL_PROFILE)


@dataclass
class FakeJudgeClient:
    results: list[RawJudgeRunResult]

    def run_once(self, invocation: object) -> RawJudgeRunResult:
        return self.results.pop(0)


def _build_artifact() -> RunArtifact:
    trace: list[TraceEvent] = [
        MessageTraceEvent(
            sequence=0,
            event_type="message",
            role="user",
            content="Please complete the task.",
        ),
        MessageTraceEvent(
            sequence=1,
            event_type="message",
            role="assistant",
            content="I will use a tool first.",
        ),
        ToolCallTraceEvent(
            sequence=2,
            event_type="tool_call",
            call_id="call_1",
            tool_name="search",
            raw_arguments={"q": "example"},
            parsed_arguments={"q": "example"},
        ),
        ToolResultTraceEvent(
            sequence=3,
            event_type="tool_result",
            call_id="call_1",
            status="success",
            output={"results": ["alpha", "beta"]},
        ),
        FinalOutputTraceEvent(
            sequence=4,
            event_type="final_output",
            content="Task completed with a concise answer.",
        ),
    ]
    return RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="run-judge-001",
            case_id="example_case",
            suite_id="example_suite",
            run_profile_id="default",
            runner_type="llm_probe",
        ),
        status=RunStatus.SUCCESS,
        request=RunRequestMetadata(requested_model="openai/gpt-5-mini"),
        trace=trace,
    )


def _build_raw_result(
    *,
    repetition_index: int,
    attempt_index: int,
    status: JudgeIterationStatus,
    content: str | None = None,
    parsed_response: dict[str, object] | None = None,
    error_message: str | None = None,
) -> RawJudgeRunResult:
    return RawJudgeRunResult(
        raw_result_ref=f"rubric_judge:repetition:{repetition_index}:attempt:{attempt_index}",
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        repetition_index=repetition_index,
        attempt_index=attempt_index,
        status=status,
        request_messages=[{"role": "user", "content": "payload"}],
        response_content=content,
        parsed_response=parsed_response,
        error_message=error_message,
    )


def _valid_contract(
    *,
    task: float = 4.0,
    process: float = 3.0,
    autonomy: float = 4.0,
    closeness: float = 5.0,
    efficiency: float = 2.0,
    spark: float = 3.0,
    empty_evidence_dimension: str | None = None,
) -> dict[str, object]:
    dimensions = {
        "task": {"evidence": ["Completed the task."], "score": task},
        "process": {"evidence": ["Followed a clear process."], "score": process},
        "autonomy": {"evidence": ["Did not need extra guidance."], "score": autonomy},
        "closeness": {"evidence": ["Stayed close to the request."], "score": closeness},
        "efficiency": {"evidence": ["Could be shorter."], "score": efficiency},
        "spark": {"evidence": ["Included one useful touch."], "score": spark},
    }
    if empty_evidence_dimension is not None:
        dimensions[empty_evidence_dimension]["evidence"] = []
    return {
        "summary": "Helpful overall result.",
        "dimensions": dimensions,
    }


def test_build_judge_messages_includes_case_artifact_and_deterministic_summary() -> None:
    config = load_test_config(FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml")

    bundle = build_judge_prompt_bundle(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=_build_artifact(),
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary={"passed": True, "failed_checks": 0},
    )
    messages = bundle.messages

    assert len(messages) == 2
    assert "strict evaluation judge" in messages[0]["content"]
    assert "EVALUATION TARGET" in messages[1]["content"]
    assert "Problem statement" not in messages[1]["content"]
    assert "SUBJECT RESPONSE" in messages[1]["content"]
    payload = bundle.user_payload
    assert payload["schema_version"] == 2
    assert payload["evaluation_target"]["dimensions"] == [
        "task",
        "process",
        "autonomy",
        "closeness",
        "efficiency",
        "spark",
    ]
    assert "case_id" not in payload["evaluation_target"]
    assert "title" not in payload["evaluation_target"]
    assert payload["subject_response"]["final_output"]["text"] == (
        "Task completed with a concise answer."
    )
    assert payload["subject_response"]["assistant_visible_messages"][0]["text_excerpt"] == (
        "I will use a tool first."
    )
    assert payload["evaluation_target"]["task_messages"][0]["role"] == "system"
    assert "name" not in payload["evaluation_target"]["task_messages"][0]
    user_messages = [
        message
        for message in payload["evaluation_target"]["task_messages"]
        if message["content"] == "Summarize the attached context."
    ]
    assert len(user_messages) == 1
    assert "role" not in user_messages[0]
    assert "name" not in user_messages[0]
    assert payload["execution_evidence"]["deterministic_summary"] == {
        "passed": True,
        "failed_checks": 0,
    }
    assert payload["execution_evidence"]["process_trace"][0]["role"] == "assistant"
    assert (
        payload["execution_evidence"]["process_trace"][0]["content"]["text_excerpt"]
        == "I will use a tool first."
    )
    assert payload["execution_evidence"]["process_trace"][1]["kind"] == "tool_call"
    assert payload["execution_evidence"]["process_trace"][2]["kind"] == "tool_result"
    assert (
        payload["execution_evidence"]["process_trace"][2]["output_summary"]["content_type"]
        == "search_results"
    )
    assert len(payload["execution_evidence"]["process_trace"]) == 3
    assert "judge_name" not in payload
    assert "judge_model" not in payload
    assert "run_artifact" not in payload
    assert "Material failures\n- none\n\nProcess trace" in messages[1]["content"]


def test_build_judge_messages_filters_raw_run_artifact_fields() -> None:
    artifact = _build_artifact()
    artifact = artifact.model_copy(
        update={
            "request": RunRequestMetadata(
                requested_model="openai/gpt-5-mini",
                metadata={
                    "model_selection": {"model_id": "secret-model", "provider": "openai"},
                    "attachments": ["/tmp/x.txt"],
                },
            ),
            "provider": artifact.provider.model_copy(
                update={
                    "provider_model_id": "openai/gpt-secret",
                    "metadata": {"model": "leak"},
                }
            ),
            "runner_metadata": {"model_id": "suite-model-id"},
            "usage": artifact.usage.model_copy(
                update={"raw_provider_usage": {"prompt_tokens": 1, "model": "leak-model"}}
            ),
        }
    )
    config = load_test_config(FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml")
    bundle = build_judge_prompt_bundle(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=artifact,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary=None,
    )
    payload = bundle.user_payload
    assert "run_artifact" not in payload
    assert "provider" not in payload["subject_response"]
    assert payload["subject_response"]["tool_activity_summary"]["tools_used"] == ["search"]
    assert payload["execution_evidence"]["material_failures"] == []


def test_build_judge_messages_summarizes_search_outputs_without_breaking_on_unknown_shapes(
    ) -> None:
    artifact = _build_artifact().model_copy(
        update={
            "trace": [
                *list(_build_artifact().trace[:3]),
                ToolResultTraceEvent(
                    sequence=3,
                    event_type="tool_result",
                    call_id="call_1",
                    status="success",
                    output={
                        "query": "benchmark judge prompt",
                        "results": [
                            {
                                "title": "Judge docs",
                                "url": "https://docs.example.com/judge",
                                "snippet": "Long snippet",
                            },
                            {
                                "title": "Prompt design",
                                "url": "https://blog.example.org/prompts",
                                "snippet": "Another snippet",
                            },
                        ],
                    },
                ),
                FinalOutputTraceEvent(
                    sequence=4,
                    event_type="final_output",
                    content="done",
                ),
            ]
        }
    )
    config = load_test_config(FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml")
    payload = build_judge_prompt_bundle(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=artifact,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary=None,
    ).user_payload
    summary = payload["execution_evidence"]["process_trace"][2]["output_summary"]
    assert summary["content_type"] == "search_results"
    assert summary["query"] == "benchmark judge prompt"
    assert "docs.example.com" in summary["top_sources"]
    rendered = build_judge_messages(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=artifact,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary=None,
    )[1]["content"]
    assert "query: benchmark judge prompt" in rendered
    assert "top_sources: docs.example.com" not in rendered


def test_build_judge_messages_normalizes_html_and_unknown_tool_outputs_resiliently() -> None:
    artifact = with_openclaw_run_evidence(
        _build_artifact().model_copy(
        update={
            "trace": [
                MessageTraceEvent(
                    sequence=0,
                    event_type="message",
                    role="assistant",
                    content="using tools",
                ),
                ToolCallTraceEvent(
                    sequence=1,
                    event_type="tool_call",
                    call_id="call_html",
                    tool_name="fetch_page",
                    raw_arguments={"url": "https://example.com"},
                    parsed_arguments={"url": "https://example.com"},
                ),
                ToolResultTraceEvent(
                    sequence=2,
                    event_type="tool_result",
                    call_id="call_html",
                    status="success",
                    output="<!doctype html><html><body>" + ("x" * 3000) + "</body></html>",
                ),
                ToolCallTraceEvent(
                    sequence=3,
                    event_type="tool_call",
                    call_id="call_unknown",
                    tool_name="weird_tool",
                    raw_arguments={},
                    parsed_arguments={},
                ),
                ToolResultTraceEvent(
                    sequence=4,
                    event_type="tool_result",
                    call_id="call_unknown",
                    status="success",
                    output=object(),
                ),
                FinalOutputTraceEvent(
                    sequence=5,
                    event_type="final_output",
                    content="done",
                ),
            ]
        }
        ),
        OpenClawRunEvidence(
            agent_id="support_agent",
            metadata={"observable_summary": {"key_output_basenames": ["report.md"]}},
        ),
    )
    config = load_test_config(FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml")
    payload = build_judge_prompt_bundle(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=artifact,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary=None,
    ).user_payload
    html_summary = payload["execution_evidence"]["process_trace"][2]["output_summary"]
    unknown_summary = payload["execution_evidence"]["process_trace"][4]["output_summary"]
    assert html_summary["content_type"] == "html"
    assert html_summary["truncated"] is True
    assert unknown_summary["content_type"] == "object"


def test_build_judge_messages_extracts_visible_text_from_openclaw_embedded_json() -> None:
    embedded = (
        "[tools] browser failed: gateway closed\\n"
        "Bind: loopback raw_params={\"action\":\"open\",\"url\":\"https://www.python.org/downloads/\"}\\n"
        "{"
        "\"payloads\":[{\"text\":\"Respuesta visible final https://www.python.org/downloads/\"}],"
        "\"finalPromptText\":\"[1] user\\nEnunciado\","
        "\"finalAssistantVisibleText\":\"Respuesta visible final https://www.python.org/downloads/\","
        "\"meta\":{\"toolSummary\":{\"calls\":2,\"tools\":[\"exec\",\"write\"],\"failures\":0}}"
        "}"
    )
    artifact = with_openclaw_run_evidence(
        _build_artifact().model_copy(
            update={
                "trace": [
                    MessageTraceEvent(
                        sequence=0,
                        event_type="message",
                        role="user",
                        content="Please complete the task.",
                    ),
                    FinalOutputTraceEvent(
                        sequence=1,
                        event_type="final_output",
                        content=embedded,
                    ),
                ]
            }
        ),
        OpenClawRunEvidence(
            agent_id="support_agent",
            metadata={"observable_summary": {"key_output_basenames": ["report.md"]}},
        ),
    )
    config = load_test_config(FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml")
    payload = build_judge_prompt_bundle(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=artifact,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary=None,
    ).user_payload
    assert payload["subject_response"]["final_output"]["text"] == (
        "Respuesta visible final https://www.python.org/downloads/"
    )
    assert payload["subject_response"]["tool_activity_summary"]["tool_call_count"] == 2
    assert payload["subject_response"]["tool_activity_summary"]["tools_used"] == ["exec", "write"]
    assert payload["execution_evidence"]["process_trace"][0]["kind"] == "tool_call"
    assert payload["execution_evidence"]["process_trace"][0]["tool_name"] == "exec"
    assert payload["execution_evidence"]["process_trace"][1]["kind"] == "tool_result"
    assert payload["execution_evidence"]["process_trace"][2]["tool_name"] == "write"
    write_summary = payload["execution_evidence"]["process_trace"][3]["output_summary"]
    assert write_summary["artifact_basenames"] == ["report.md"]
    rendered = build_judge_messages(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=artifact,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary=None,
    )[1]["content"]
    assert "extracted from OpenClaw" not in rendered
    assert "Recovered from embedded OpenClaw" not in rendered
    assert "Tool activity: 2 tool calls; tools used: exec, write" in rendered
    assert "artifact_basenames: report.md" in rendered


def test_build_judge_messages_preserves_utf8_in_prompt_text() -> None:
    artifact = _build_artifact().model_copy(
        update={
            "trace": [
                MessageTraceEvent(
                    sequence=0,
                    event_type="message",
                    role="assistant",
                    content="Importe recomendado: 10.000€",
                ),
                FinalOutputTraceEvent(
                    sequence=1,
                    event_type="final_output",
                    content="Importe recomendado: 10.000€",
                ),
            ]
        }
    )
    config = load_test_config(FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml")
    user_message = build_judge_messages(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=config,
        run_artifact=artifact,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        deterministic_summary=None,
    )[1]["content"]
    assert "10.000€" in user_message
    assert "EVALUATION TARGET" in user_message
    assert "\\u20ac" not in user_message


def test_orchestrator_records_successful_iteration_and_aggregation() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(),
                )
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
    )

    assert result.successful_iterations == 1
    assert result.failed_iterations == 0
    assert result.used_repetition_indices == [0]
    assert result.excluded_repetition_indices == []
    assert result.dimensions is not None
    assert result.dimensions.task == 4.0
    assert result.summary == "Helpful overall result."
    assert result.iteration_results[0].status is JudgeIterationStatus.SUCCESS


def test_orchestrator_retries_then_succeeds() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.PROVIDER_ERROR,
                    error_message="Temporary upstream failure.",
                ),
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=1,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=5.0),
                ),
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        max_retries=1,
    )

    assert result.successful_iterations == 1
    assert len(result.raw_results) == 2
    assert result.iteration_results[0].status is JudgeIterationStatus.SUCCESS
    assert any("succeeded after 1 retry attempt" in warning for warning in result.warnings)


def test_orchestrator_retries_then_keeps_failed_repetition_visible() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.TIMED_OUT,
                    error_message="Timed out.",
                ),
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=1,
                    status=JudgeIterationStatus.PROVIDER_ERROR,
                    error_message="Still unavailable.",
                ),
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
        max_retries=1,
    )

    assert result.successful_iterations == 0
    assert result.failed_iterations == 1
    assert result.used_repetition_indices == []
    assert result.excluded_repetition_indices == [0]
    assert result.iteration_results[0].status is JudgeIterationStatus.FAILED
    assert any("failed after 2 total attempts" in warning for warning in result.warnings)


def test_orchestrator_marks_structurally_invalid_output() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    content="{not-json",
                )
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
    )

    assert result.iteration_results[0].status is JudgeIterationStatus.INVALID_OUTPUT
    assert result.successful_iterations == 0
    assert result.failed_iterations == 1


def test_orchestrator_keeps_success_with_incomplete_evidence_warning() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(empty_evidence_dimension="spark"),
                )
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=1,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
    )

    assert result.iteration_results[0].status is JudgeIterationStatus.SUCCESS
    assert any("evidence for dimension 'spark'" in warning.lower() for warning in result.warnings)


def test_orchestrator_aggregates_successful_iterations_only_with_median() -> None:
    orchestrator = JudgeOrchestrator(
        FakeJudgeClient(
            results=[
                _build_raw_result(
                    repetition_index=0,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=1.0, efficiency=1.0),
                ),
                _build_raw_result(
                    repetition_index=1,
                    attempt_index=0,
                    status=JudgeIterationStatus.PROVIDER_ERROR,
                    error_message="Provider error.",
                ),
                _build_raw_result(
                    repetition_index=2,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=5.0, efficiency=3.0),
                ),
                _build_raw_result(
                    repetition_index=3,
                    attempt_index=0,
                    status=JudgeIterationStatus.SUCCESS,
                    parsed_response=_valid_contract(task=3.0, efficiency=5.0),
                ),
            ]
        )
    )

    result = orchestrator.evaluate(
        judge_name="rubric_judge",
        judge_model="openai/gpt-5-mini",
        test_config=load_test_config(
            FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
        ),
        run_artifact=_build_artifact(),
        repetitions=4,
        system_prompt=_FIXTURE_JUDGE_SYSTEM_PROMPT,
    )

    assert result.successful_iterations == 3
    assert result.failed_iterations == 1
    assert result.used_repetition_indices == [0, 2, 3]
    assert result.excluded_repetition_indices == [1]
    assert result.dimensions is not None
    assert result.dimensions.task == 3.0
    assert result.dimensions.efficiency == 3.0
    assert result.summary is not None
    assert "[repetition 0] Helpful overall result." in result.summary
    assert "[repetition 2] Helpful overall result." in result.summary
