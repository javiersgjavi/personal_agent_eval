"""Build a compact judge-facing view of the evaluated run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from personal_agent_eval.artifacts import RunArtifact, parse_openclaw_run_evidence
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    OutputArtifactRef,
    ToolCallTraceEvent,
    ToolResultTraceEvent,
)
from personal_agent_eval.config.test_config import TestConfig

_DIMENSIONS = ["task", "process", "autonomy", "closeness", "efficiency", "spark"]
_MAX_TEXT_CHARS = 2000
_MAX_VISIBLE_TEXT_CHARS = 12000
_MAX_TRACE_TEXT_CHARS = 1200
_MAX_LIST_ITEMS = 5
_MAX_DICT_ITEMS = 12


def build_judge_subject_view(
    *,
    test_config: TestConfig,
    run_artifact: RunArtifact,
    deterministic_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the compact JSON payload shown to the judge."""
    return {
        "schema_version": 2,
        "evaluation_target": _build_evaluation_target(test_config),
        "subject_response": _build_subject_response(run_artifact),
        "execution_evidence": _build_execution_evidence(
            run_artifact=run_artifact,
            deterministic_summary=deterministic_summary,
        ),
    }


def render_judge_user_text(subject_view: dict[str, Any]) -> str:
    """Render the subject view as a compact human-readable text prompt."""
    lines: list[str] = []
    lines.append("EVALUATION TARGET")
    dimensions = subject_view.get("evaluation_target", {}).get("dimensions", [])
    lines.append(f"Dimensions: {', '.join(dimensions)}")

    task_messages = subject_view.get("evaluation_target", {}).get("task_messages", [])
    if isinstance(task_messages, list) and task_messages:
        lines.append("")
        lines.append("Task messages")
        for index, message in enumerate(task_messages, start=1):
            if not isinstance(message, dict):
                continue
            role = message.get("role") or "user"
            content = message.get("content")
            if not isinstance(content, str):
                continue
            label = str(role).upper()
            lines.append(f"{index}. {label}")
            lines.extend(_indent_block(content.strip(), prefix="   "))

    expectations = subject_view.get("evaluation_target", {}).get("expectations", {})
    if isinstance(expectations, dict):
        lines.append("")
        lines.append("Expectations")
        hard = expectations.get("hard", [])
        soft = expectations.get("soft", [])
        if hard:
            lines.append("Hard")
            for item in hard:
                if isinstance(item, str) and item.strip():
                    lines.append(f"- {item.strip()}")
        if soft:
            lines.append("Soft")
            for item in soft:
                if isinstance(item, str) and item.strip():
                    lines.append(f"- {item.strip()}")

    rubric = subject_view.get("evaluation_target", {}).get("rubric")
    if isinstance(rubric, dict):
        rubric_text = _render_rubric_table(rubric)
        if rubric_text:
            lines.append("")
            lines.extend(rubric_text)

    deterministic_checks = subject_view.get("evaluation_target", {}).get("deterministic_checks", [])
    if isinstance(deterministic_checks, list) and deterministic_checks:
        lines.append("")
        lines.append("Deterministic checks")
        for check in deterministic_checks:
            if not isinstance(check, dict):
                continue
            check_id = check.get("check_id", "unknown")
            kind = check.get("kind", "unknown")
            dims = check.get("dimensions", [])
            dims_text = ", ".join(dims) if isinstance(dims, list) else ""
            suffix = f" [{dims_text}]" if dims_text else ""
            lines.append(f"- {check_id}: {kind}{suffix}")

    subject_response = subject_view.get("subject_response", {})
    if isinstance(subject_response, dict):
        lines.append("")
        lines.append("SUBJECT RESPONSE")
        final_output = subject_response.get("final_output")
        if isinstance(final_output, dict):
            content_type = final_output.get("content_type", "text")
            text = final_output.get("text", "")
            if isinstance(text, str) and text.strip():
                lines.append(f"Final output ({content_type})")
                lines.extend(_fenced_block(text.strip(), language=_fence_language(content_type)))
        assistant_messages = subject_response.get("assistant_visible_messages", [])
        if isinstance(assistant_messages, list) and assistant_messages:
            lines.append("Assistant-visible messages")
            for item in assistant_messages:
                if not isinstance(item, dict):
                    continue
                excerpt = item.get("text_excerpt")
                if isinstance(excerpt, str) and excerpt.strip():
                    lines.append(f"- {excerpt.strip()}")
        tool_summary = subject_response.get("tool_activity_summary", {})
        if isinstance(tool_summary, dict):
            tool_count = tool_summary.get("tool_call_count")
            tools_used = tool_summary.get("tools_used", [])
            rendered_tools = (
                ", ".join(tools_used) if isinstance(tools_used, list) and tools_used else "none"
            )
            lines.append(
                f"Tool activity: {tool_count if isinstance(tool_count, int) else 0} tool calls; "
                f"tools used: {rendered_tools}"
            )

    execution_evidence = subject_view.get("execution_evidence", {})
    if isinstance(execution_evidence, dict):
        lines.append("")
        lines.append("EXECUTION EVIDENCE")
        deterministic_summary = execution_evidence.get("deterministic_summary", {})
        if isinstance(deterministic_summary, dict):
            lines.append(
                "Deterministic summary: "
                + ", ".join(
                    f"{key}={deterministic_summary.get(key)}"
                    for key in ("passed_checks", "failed_checks", "error_checks", "total_checks")
                    if key in deterministic_summary
                )
            )
        material_failures = execution_evidence.get("material_failures", [])
        if isinstance(material_failures, list):
            lines.append("Material failures")
            if not material_failures:
                lines.append("- none")
            else:
                for item in material_failures:
                    if not isinstance(item, dict):
                        continue
                    message = item.get("message") or item.get("detail") or "unknown failure"
                    lines.append(f"- {message}")
            lines.append("")
        process_trace = execution_evidence.get("process_trace", [])
        if isinstance(process_trace, list):
            lines.append("Process trace")
            if not process_trace:
                lines.append("- none")
            else:
                for index, event in enumerate(process_trace, start=1):
                    lines.extend(_render_trace_event(index, event))
            lines.append("")

        artifacts = execution_evidence.get("artifacts", [])
        if isinstance(artifacts, list) and artifacts:
            lines.append("Artifacts")
            for item in artifacts:
                if not isinstance(item, dict):
                    continue
                basename = item.get("basename", "artifact")
                artifact_type = item.get("artifact_type", "artifact")
                excerpt = item.get("excerpt")
                lines.append(f"- {artifact_type}: {basename}")
                if isinstance(excerpt, str) and excerpt.strip():
                    excerpt_text = _truncate_text(excerpt.strip(), max_chars=1200)
                    lines.extend(_indent_block(excerpt_text, prefix="  "))

    return "\n".join(lines).strip() + "\n"


def _build_evaluation_target(test_config: TestConfig) -> dict[str, Any]:
    input_messages: list[dict[str, Any]] = []
    for message in test_config.input.messages:
        input_messages.extend(_serialize_input_messages(message))
    target: dict[str, Any] = {
        "dimensions": list(_DIMENSIONS),
        "task_messages": input_messages,
        "expectations": {
            "hard": [item.text for item in test_config.expectations.hard_expectations],
            "soft": [item.text for item in test_config.expectations.soft_expectations],
        },
        "deterministic_checks": [
            _serialize_check(check) for check in test_config.deterministic_checks
        ],
    }
    if test_config.rubric is not None:
        target["rubric"] = {
            "version": test_config.rubric.version,
            "scale": {
                "min": test_config.rubric.scale.min,
                "max": test_config.rubric.scale.max,
                "anchors": dict(test_config.rubric.scale.anchors),
            },
            "criteria": [
                {
                    "name": criterion.name,
                    "what_good_looks_like": criterion.what_good_looks_like,
                    "what_bad_looks_like": criterion.what_bad_looks_like,
                }
                for criterion in test_config.rubric.criteria
            ],
            "scoring_instructions": test_config.rubric.scoring_instructions,
        }
    attachment_names = [path.name for path in test_config.input.attachments]
    if attachment_names:
        target["attachments"] = attachment_names
    if test_config.input.context:
        target["context"] = test_config.input.context
    return target


def _serialize_input_messages(message: Any) -> list[dict[str, Any]]:
    def _compact_message(payload: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {"content": payload["content"]}
        role = payload.get("role")
        if role is not None and role != "user":
            compact["role"] = role
        name = payload.get("name")
        if name is not None:
            compact["name"] = name
        return compact

    if message.content is not None:
        return [
            _compact_message(
                {"role": message.role, "content": message.content, "name": message.name}
            )
        ]
    source = getattr(message, "source", None)
    if source is None:
        return [_compact_message({"role": message.role, "content": None, "name": message.name})]
    return _load_message_source_payload(
        path=source.path,
        source_format=source.format,
        default_role=message.role,
        default_name=message.name,
    )


def _load_message_source_payload(
    *,
    path: Path,
    source_format: str | None,
    default_role: str,
    default_name: str | None,
) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return [
            _compact_loaded_message(
                default_role,
                f"[unresolved message source: {path.name}]",
                default_name,
            )
        ]

    try:
        payload = _parse_message_source_payload(raw, path=path, source_format=source_format)
    except Exception:
        return [
            _compact_loaded_message(
                default_role,
                _truncate_text(raw, max_chars=_MAX_TEXT_CHARS),
                default_name,
            )
        ]

    return _coerce_message_source_payload(
        payload,
        default_role=default_role,
        default_name=default_name,
    )


def _parse_message_source_payload(raw: str, *, path: Path, source_format: str | None) -> Any:
    resolved_format = (source_format or path.suffix.lstrip(".")).lower()
    if resolved_format == "json":
        return json.loads(raw)
    return yaml.safe_load(raw)


def _coerce_message_source_payload(
    payload: Any,
    *,
    default_role: str,
    default_name: str | None,
) -> list[dict[str, Any]]:
    def _compact_message(payload: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {"content": payload.get("content")}
        role = payload.get("role")
        if role is not None and role != "user":
            compact["role"] = role
        name = payload.get("name")
        if name is not None:
            compact["name"] = name
        return compact

    if isinstance(payload, str):
        return [_compact_loaded_message(default_role, payload, default_name)]
    if isinstance(payload, dict):
        if isinstance(payload.get("messages"), list):
            payload = payload["messages"]
        else:
            return [
                _compact_message(
                    {
                        "role": str(payload.get("role", default_role)),
                        "content": payload.get("content"),
                        "name": payload.get("name", default_name),
                    }
                )
            ]
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, str):
                items.append(_compact_loaded_message(default_role, item, default_name))
                continue
            if not isinstance(item, dict):
                items.append(_compact_loaded_message(default_role, _safe_repr(item), default_name))
                continue
            items.append(
                _compact_message(
                    {
                        "role": str(item.get("role", default_role)),
                        "content": item.get("content"),
                        "name": item.get("name", default_name),
                    }
                )
            )
        return items
    return [_compact_loaded_message(default_role, _safe_repr(payload), default_name)]


def _compact_loaded_message(role: str, content: str, name: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"content": content}
    if role != "user":
        payload["role"] = role
    if name is not None:
        payload["name"] = name
    return payload


def _serialize_check(check: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "check_id": check.check_id,
        "dimensions": list(check.dimensions),
    }
    if check.description is not None:
        payload["description"] = check.description
    if check.declarative is not None:
        payload["kind"] = check.declarative.kind
    elif check.python_hook is not None:
        payload["kind"] = "python_hook"
        payload["callable_name"] = check.python_hook.callable_name
    return payload


def _render_rubric_table(rubric: dict[str, Any]) -> list[str]:
    scale = rubric.get("scale")
    criteria = rubric.get("criteria")
    scoring_instructions = rubric.get("scoring_instructions")

    lines: list[str] = []
    lines.append("Rubric (optional guidance)")

    if isinstance(scale, dict):
        min_score = scale.get("min")
        max_score = scale.get("max")
        anchors = scale.get("anchors")
        header_note = ""
        if isinstance(min_score, int | float) and isinstance(max_score, int | float):
            header_note = f" — overall score {min_score:g}–{max_score:g}"
        lines[-1] = lines[-1] + header_note

        if isinstance(anchors, dict) and anchors:
            lines.append("")
            lines.append("Scale anchors")
            lines.append("| Score | Meaning |")
            lines.append("|------:|---------|")
            for score, meaning in sorted(
                ((str(k), v) for k, v in anchors.items() if isinstance(v, str) and v.strip()),
                key=lambda item: _safe_float_sort_key(item[0]),
                reverse=True,
            ):
                lines.append(f"| {_escape_table_cell(score)} | {_escape_table_cell(meaning)} |")

    if isinstance(criteria, list) and criteria:
        rendered_rows: list[tuple[str, str, str]] = []
        for item in criteria:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            good = item.get("what_good_looks_like")
            bad = item.get("what_bad_looks_like")
            if not all(isinstance(value, str) and value.strip() for value in (name, good, bad)):
                continue
            rendered_rows.append((name.strip(), good.strip(), bad.strip()))

        if rendered_rows:
            lines.append("")
            lines.append("Criteria")
            lines.append("| Criterion | What “high” looks like | What “low” looks like |")
            lines.append("|---|---|---|")
            for name, good, bad in rendered_rows:
                lines.append(
                    "| " + " | ".join(_escape_table_cell(cell) for cell in (name, good, bad)) + " |"
                )

    if isinstance(scoring_instructions, str) and scoring_instructions.strip():
        lines.append("")
        lines.append("Scoring instruction")
        lines.extend(_indent_block(scoring_instructions.strip(), prefix="- "))

    if len(lines) == 1:
        return []
    return lines


def _escape_table_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def _safe_float_sort_key(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return float("-inf")


def _build_subject_response(run_artifact: RunArtifact) -> dict[str, Any]:
    assistant_messages = [
        _format_visible_text(
            _extract_observable_text(event.content),
            max_chars=_MAX_TRACE_TEXT_CHARS,
            field_name="text_excerpt",
        )
        for event in run_artifact.trace
        if isinstance(event, MessageTraceEvent)
        and event.role == "assistant"
        and _extract_observable_text(event.content) is not None
    ]
    final_output = _last_final_output(run_artifact)
    tool_calls = [
        event.tool_name for event in run_artifact.trace if isinstance(event, ToolCallTraceEvent)
    ]
    openclaw_tool_summary = _extract_openclaw_tool_summary(run_artifact)
    tool_call_count = len(tool_calls)
    tools_used = sorted(set(tool_calls))
    if tool_call_count == 0 and openclaw_tool_summary is not None:
        calls = openclaw_tool_summary.get("calls")
        tools = openclaw_tool_summary.get("tools")
        if isinstance(calls, int):
            tool_call_count = calls
        if isinstance(tools, list):
            tools_used = [str(item) for item in tools if isinstance(item, str) and item.strip()]
    response: dict[str, Any] = {
        "assistant_visible_messages": assistant_messages,
        "final_output": _format_visible_text(
            final_output,
            max_chars=_MAX_VISIBLE_TEXT_CHARS,
            field_name="text",
        ),
        "tool_activity_summary": {
            "tool_call_count": tool_call_count,
            "tools_used": tools_used,
        },
    }
    return response


def _build_execution_evidence(
    *,
    run_artifact: RunArtifact,
    deterministic_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "deterministic_summary": deterministic_summary,
        "process_trace": _build_process_trace(run_artifact),
        "artifacts": _build_artifact_excerpts(run_artifact),
        "material_failures": _build_material_failures(run_artifact),
    }
    return payload


def _build_process_trace(run_artifact: RunArtifact) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    tool_names_by_call_id = {
        event.call_id: event.tool_name
        for event in run_artifact.trace
        if isinstance(event, ToolCallTraceEvent)
    }
    for event in run_artifact.trace:
        if isinstance(event, MessageTraceEvent):
            if event.role not in {"assistant", "tool"}:
                continue
            visible_text = _extract_observable_text(event.content)
            if visible_text is None:
                continue
            item = {
                "kind": "message",
                "role": event.role,
                "content": _format_visible_text(
                    visible_text,
                    max_chars=_MAX_TRACE_TEXT_CHARS,
                    field_name="text_excerpt",
                ),
            }
            if event.name is not None:
                item["name"] = event.name
            events.append(item)
            continue
        if isinstance(event, ToolCallTraceEvent):
            events.append(
                {
                    "kind": "tool_call",
                    "tool_name": event.tool_name,
                    "call_id": event.call_id,
                    "arguments": (
                        event.parsed_arguments
                        if event.parsed_arguments is not None
                        else event.raw_arguments
                    ),
                }
            )
            continue
        if isinstance(event, ToolResultTraceEvent):
            tool_name = tool_names_by_call_id.get(event.call_id)
            events.append(
                {
                    "kind": "tool_result",
                    "tool_name": tool_name,
                    "call_id": event.call_id,
                    "status": event.status,
                    "output_summary": _normalize_tool_result_output(
                        event.output,
                        tool_name=tool_name,
                    ),
                }
            )
            continue
    if events:
        return events
    synthetic_openclaw = _build_synthetic_openclaw_process_trace(run_artifact)
    if synthetic_openclaw:
        return synthetic_openclaw
    return events


def _build_synthetic_openclaw_process_trace(run_artifact: RunArtifact) -> list[dict[str, Any]]:
    summary = _extract_openclaw_tool_summary(run_artifact)
    observable_summary = _extract_openclaw_observable_summary(run_artifact)
    if summary is None:
        return []
    tools = summary.get("tools")
    failures = summary.get("failures")
    if not isinstance(tools, list) or not tools:
        return []
    key_output_basenames = _observable_key_output_basenames(observable_summary)
    events: list[dict[str, Any]] = []
    for index, tool_name in enumerate(tools, start=1):
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue
        call_id = f"openclaw_tool_{index}"
        events.append(
            {
                "kind": "tool_call",
                "tool_name": tool_name,
                "call_id": call_id,
            }
        )
        status = "success"
        if isinstance(failures, int) and failures >= index:
            status = "error"
        output_summary: dict[str, Any] = {
            "content_type": "openclaw_tool_summary",
        }
        if tool_name in {"web_search", "web_fetch", "browser", "memory_search", "memory_get"}:
            pass
        if tool_name == "write" and key_output_basenames:
            output_summary["artifact_basenames"] = key_output_basenames
        events.append(
            {
                "kind": "tool_result",
                "tool_name": tool_name,
                "call_id": call_id,
                "status": status,
                "output_summary": output_summary,
            }
        )
    return events


def _render_trace_event(index: int, event: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not isinstance(event, dict):
        return [f"{index}. [unrecognized event]"]
    kind = event.get("kind", "unknown")
    lines.append(f"{index}. {kind}")
    if kind == "message":
        role = event.get("role", "unknown")
        content = event.get("content")
        lines.append(f"   role: {role}")
        if isinstance(content, dict):
            excerpt = content.get("text_excerpt") or content.get("text")
            if isinstance(excerpt, str) and excerpt.strip():
                lines.extend(_indent_block(excerpt.strip(), prefix="   "))
        elif isinstance(content, str) and content.strip():
            lines.extend(_indent_block(content.strip(), prefix="   "))
        return lines
    if kind == "tool_call":
        tool_name = event.get("tool_name", "unknown")
        arguments = event.get("arguments")
        lines.append(f"   tool: {tool_name}")
        if arguments is not None:
            lines.extend(_indent_block(_safe_pretty(arguments), prefix="   "))
        return lines
    if kind == "tool_result":
        tool_name = event.get("tool_name", "unknown")
        status = event.get("status", "unknown")
        summary = event.get("output_summary")
        lines.append(f"   tool: {tool_name}")
        lines.append(f"   status: {status}")
        if isinstance(summary, dict):
            lines.extend(_indent_block(_render_output_summary(summary), prefix="   "))
        return lines
    lines.extend(_indent_block(_safe_pretty(event), prefix="   "))
    return lines


def _render_output_summary(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    content_type = summary.get("content_type")
    if isinstance(content_type, str) and content_type.strip():
        lines.append(f"output: {content_type.strip()}")
    if content_type == "search_results":
        query = summary.get("query")
        if isinstance(query, str) and query.strip():
            lines.append(f"query: {query.strip()}")
        result_count = summary.get("result_count")
        if isinstance(result_count, int):
            lines.append(f"result_count: {result_count}")
        top_titles = summary.get("top_titles")
        if isinstance(top_titles, list) and top_titles:
            rendered = ", ".join(str(item) for item in top_titles if str(item).strip())
            if rendered:
                lines.append(f"top_titles: {rendered}")
        if summary.get("truncated") is True:
            lines.append("truncated: true")
        return "\n".join(lines)
    if isinstance(summary.get("char_count"), int):
        lines.append(f"char_count: {summary['char_count']}")
    if isinstance(summary.get("item_count"), int):
        lines.append(f"item_count: {summary['item_count']}")
    if isinstance(summary.get("artifact_basenames"), list) and summary["artifact_basenames"]:
        rendered_artifacts = ", ".join(
            str(item) for item in summary["artifact_basenames"] if str(item).strip()
        )
        if rendered_artifacts:
            lines.append(f"artifact_basenames: {rendered_artifacts}")
    if isinstance(summary.get("keys"), list) and summary["keys"]:
        rendered_keys = ", ".join(str(item) for item in summary["keys"] if str(item).strip())
        if rendered_keys:
            lines.append(f"keys: {rendered_keys}")
    if isinstance(summary.get("excerpt"), str) and summary["excerpt"].strip():
        lines.append(_truncate_text(summary["excerpt"].strip(), max_chars=1200))
    elif isinstance(summary.get("summary"), str) and summary["summary"].strip():
        lines.append(summary["summary"].strip())
    if summary.get("truncated") is True:
        lines.append("truncated: true")
    return "\n".join(lines)


def _indent_block(text: str, *, prefix: str) -> list[str]:
    return [f"{prefix}{line}" if line else prefix.rstrip() for line in text.splitlines()]


def _safe_pretty(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    except Exception:
        return _safe_repr(value)


def _fence_language(content_type: str) -> str:
    if content_type == "markdown":
        return "markdown"
    if content_type == "json":
        return "json"
    return ""


def _fenced_block(text: str, *, language: str = "") -> list[str]:
    fence = f"```{language}".rstrip()
    return [fence, *text.splitlines(), "```"]


def _build_artifact_excerpts(run_artifact: RunArtifact) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    artifacts: list[dict[str, Any]] = []
    for ref in run_artifact.output_artifacts:
        item = _artifact_excerpt(ref)
        key = (item["artifact_type"], item["basename"])
        if key in seen:
            continue
        seen.add(key)
        artifacts.append(item)

    openclaw_evidence = parse_openclaw_run_evidence(run_artifact.runner_metadata)
    if openclaw_evidence is not None:
        for ref in openclaw_evidence.key_output_artifacts:
            item = _artifact_excerpt(ref)
            key = (item["artifact_type"], item["basename"])
            if key in seen:
                continue
            seen.add(key)
            artifacts.append(item)
    return artifacts


def _artifact_excerpt(ref: OutputArtifactRef) -> dict[str, Any]:
    parsed = urlparse(ref.uri)
    basename = Path(parsed.path).name or ref.artifact_id
    return {
        "artifact_type": ref.artifact_type,
        "basename": basename,
        "excerpt": _read_text_excerpt(ref, max_chars=4000),
    }


def _build_material_failures(run_artifact: RunArtifact) -> list[dict[str, Any]]:
    if run_artifact.error is None:
        return []
    failure: dict[str, Any] = {
        "code": run_artifact.error.code,
        "message": run_artifact.error.message,
        "error_type": run_artifact.error.error_type,
        "retryable": run_artifact.error.retryable,
    }
    detail = _select_material_error_detail(run_artifact.error.metadata)
    if detail is not None:
        failure["detail"] = detail
    return [failure]


def _normalize_tool_result_output(output: Any, *, tool_name: str | None) -> Any:
    try:
        if _looks_like_search_tool(tool_name):
            summary = _summarize_search_output(output)
            if summary is not None:
                return summary
        return _normalize_value(output, depth=0)
    except Exception as exc:
        return {
            "content_type": "unrecognized",
            "summary": _safe_repr(output),
            "normalization_warning": f"{type(exc).__name__}: {exc}",
        }


def _normalize_value(value: Any, *, depth: int) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list | tuple):
        items = [_normalize_value(item, depth=depth + 1) for item in list(value)[:_MAX_LIST_ITEMS]]
        return {
            "content_type": "list",
            "item_count": len(value),
            "items": items,
            "truncated": len(value) > _MAX_LIST_ITEMS,
        }
    if isinstance(value, dict):
        normalized_items: dict[str, Any] = {}
        keys = list(value.keys())
        for key in keys[:_MAX_DICT_ITEMS]:
            normalized_items[str(key)] = _normalize_value(value[key], depth=depth + 1)
        return {
            "content_type": "object",
            "keys": [str(key) for key in keys],
            "values": normalized_items,
            "truncated": len(keys) > _MAX_DICT_ITEMS,
        }
    return {
        "content_type": type(value).__name__,
        "summary": _safe_repr(value),
    }


def _normalize_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    content_type = "text"
    parsed_json: Any | None = None
    if _looks_like_html(stripped):
        content_type = "html"
    else:
        try:
            parsed_json = json.loads(stripped)
        except Exception:
            parsed_json = None
        if parsed_json is not None:
            content_type = "json"
        elif _looks_like_log(stripped):
            content_type = "log"
        elif _looks_like_markdown(stripped):
            content_type = "markdown"
    payload: dict[str, Any] = {
        "content_type": content_type,
        "char_count": len(text),
        "excerpt": _truncate_text(text, max_chars=_MAX_TEXT_CHARS),
        "truncated": len(text) > _MAX_TEXT_CHARS,
    }
    if content_type == "json" and parsed_json is not None:
        payload["parsed_summary"] = _normalize_value(parsed_json, depth=1)
    return payload


def _format_visible_text(
    text: str | None,
    *,
    max_chars: int,
    field_name: str,
) -> dict[str, Any] | None:
    if text is None:
        return None
    normalized = _normalize_text(text)
    return {
        "content_type": normalized["content_type"],
        "char_count": normalized["char_count"],
        field_name: _truncate_text(text, max_chars=max_chars),
        "truncated": len(text) > max_chars,
    }


def _summarize_search_output(output: Any) -> dict[str, Any] | None:
    if not isinstance(output, dict):
        return None
    summary: dict[str, Any] = {
        "content_type": "search_results",
        "keys": [str(key) for key in output.keys()],
    }
    query = output.get("query") or output.get("q")
    if isinstance(query, str) and query.strip():
        summary["query"] = query
    results = output.get("results")
    if isinstance(results, list):
        summary["result_count"] = len(results)
        top_sources: list[str] = []
        top_titles: list[str] = []
        for item in results[:_MAX_LIST_ITEMS]:
            if not isinstance(item, dict):
                continue
            domain = _extract_domain(item.get("url") or item.get("link") or item.get("domain"))
            if domain is not None and domain not in top_sources:
                top_sources.append(domain)
            title = item.get("title")
            if isinstance(title, str) and title.strip():
                top_titles.append(_truncate_text(title, max_chars=120))
        if top_sources:
            summary["top_sources"] = top_sources
        if top_titles:
            summary["top_titles"] = top_titles
        summary["truncated"] = len(results) > _MAX_LIST_ITEMS
        return summary
    return None


def _looks_like_search_tool(tool_name: str | None) -> bool:
    if tool_name is None:
        return False
    lowered = tool_name.lower()
    return "search" in lowered or lowered in {"web", "browser.search"}


def _looks_like_html(text: str) -> bool:
    lowered = text.lower()
    return "<html" in lowered or "<body" in lowered or "<!doctype html" in lowered


def _looks_like_log(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    markers = sum(
        1
        for line in lines[:10]
        if any(
            token in line.lower()
            for token in ("[debug]", "[info]", "[error]", "traceback", "returncode:")
        )
    )
    return markers >= 2


def _looks_like_markdown(text: str) -> bool:
    return any(token in text for token in ("\n# ", "\n## ", "```", "- ", "* "))


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _extract_domain(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value)
    if parsed.netloc:
        return parsed.netloc
    if "." in value and " " not in value:
        return value
    return None


def _safe_repr(value: Any) -> str:
    try:
        rendered = repr(value)
    except Exception:
        rendered = f"<unrepresentable {type(value).__name__}>"
    return _truncate_text(rendered, max_chars=400)


def _select_material_error_detail(metadata: dict[str, Any]) -> str | None:
    for key in ("stderr", "detail", "message", "stdout"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if len(normalized) > 2000:
                return normalized[:2000] + "\n... [truncated]"
            return normalized
    return None


def _last_final_output(run_artifact: RunArtifact) -> str | None:
    for event in reversed(run_artifact.trace):
        if isinstance(event, FinalOutputTraceEvent):
            visible_text = _extract_observable_text(event.content)
            if visible_text is not None:
                return visible_text
    return None


def _extract_observable_text(content: Any) -> str | None:
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None
    openclaw_payload = _extract_openclaw_embedded_payload(stripped)
    if openclaw_payload is None:
        return stripped
    visible = _extract_openclaw_visible_text(openclaw_payload)
    if visible is not None:
        return visible
    return stripped


def _extract_openclaw_embedded_payload(content: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for start_index, char in enumerate(content):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(content[start_index:])
        except Exception:
            continue
        if isinstance(payload, dict) and (
            "payloads" in payload
            or "finalAssistantVisibleText" in payload
            or "finalPromptText" in payload
            or (isinstance(payload.get("meta"), dict) and "toolSummary" in payload["meta"])
        ):
            return payload
    return None


def _extract_openclaw_visible_text(payload: dict[str, Any]) -> str | None:
    direct = payload.get("finalAssistantVisibleText")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    payloads = payload.get("payloads")
    if isinstance(payloads, list):
        texts: list[str] = []
        for item in payloads:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        if texts:
            return "\n\n".join(texts)
    for key in ("content", "message", "response", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_openclaw_tool_summary(run_artifact: RunArtifact) -> dict[str, Any] | None:
    observable_summary = _extract_openclaw_observable_summary(run_artifact)
    if observable_summary is not None:
        tool_summary = observable_summary.get("tool_summary")
        if isinstance(tool_summary, dict):
            return tool_summary
    for event in reversed(run_artifact.trace):
        if not isinstance(event, FinalOutputTraceEvent):
            continue
        if not isinstance(event.content, str):
            continue
        payload = _extract_openclaw_embedded_payload(event.content.strip())
        if payload is None:
            continue
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            continue
        tool_summary = meta.get("toolSummary")
        if isinstance(tool_summary, dict):
            return tool_summary
    return None


def _extract_openclaw_observable_summary(run_artifact: RunArtifact) -> dict[str, Any] | None:
    evidence = parse_openclaw_run_evidence(run_artifact.runner_metadata)
    if evidence is None:
        return None
    metadata = evidence.metadata
    if not isinstance(metadata, dict):
        return None
    summary = metadata.get("observable_summary")
    return summary if isinstance(summary, dict) else None


def _observable_key_output_basenames(observable_summary: dict[str, Any] | None) -> list[str]:
    if observable_summary is None:
        return []
    value = observable_summary.get("key_output_basenames")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _read_text_excerpt(ref: OutputArtifactRef, *, max_chars: int) -> str | None:
    parsed = urlparse(ref.uri)
    if parsed.scheme != "file":
        return None
    path = Path(parsed.path)
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return ""
    try:
        text = raw[: max_chars * 4].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(text) > max_chars:
        return text[:max_chars] + "\n... [truncated]"
    return text
