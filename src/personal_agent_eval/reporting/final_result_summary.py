"""Markdown summary rendering for final evaluation results."""

from __future__ import annotations

from collections.abc import Iterable

from personal_agent_eval.aggregation.models import FinalEvaluationResult
from personal_agent_eval.deterministic.models import DeterministicEvaluationResult
from personal_agent_eval.judge.models import AggregatedJudgeResult


def render_final_result_markdown(result: FinalEvaluationResult) -> str:
    """Render a human-readable Markdown summary for one final evaluation result."""
    overall_note = ""
    if result.judge_overall is not None:
        overall_note = " (judge overall)"
    lines: list[str] = [
        "# Final Evaluation Summary",
        "",
        "## Overview",
        f"- Case: `{result.case_id}`",
        f"- Run: `{result.run_id}`",
        f"- Final score{overall_note}: `{_format_score(result.final_score)}`",
        f"- Judge output snapshot: {_format_dimension_snapshot(result.judge_dimensions)}",
        f"- Security verdict: `{result.security.verdict}`",
        (
            "- Judge iterations: "
            f"{result.summary.judge_successful_iterations} successful, "
            f"{result.summary.judge_failed_iterations} failed"
        ),
        (
            "- Deterministic checks: "
            f"{result.summary.deterministic_passed_checks} passed, "
            f"{result.summary.deterministic_failed_checks} failed, "
            f"{result.summary.deterministic_error_checks} error"
        ),
    ]

    if result.judge_overall is not None and result.judge_overall.evidence:
        lines.extend(
            [
                "- Judge overall evidence:",
                *[f"  - {entry}" for entry in result.judge_overall.evidence if entry.strip()],
            ]
        )

    if result.warnings:
        lines.extend(
            [
                "- Warnings:",
                *[f"  - {warning}" for warning in result.warnings],
            ]
        )
    else:
        lines.append("- Warnings: none")

    lines.extend(
        [
            "",
            "## Dimension Breakdown",
            _render_dimension_table(result),
        ]
    )

    if result.security.warnings:
        lines.extend(
            [
                "",
                "## Security Notes",
                *[f"- {warning}" for warning in result.security.warnings],
            ]
        )

    lines.extend(
        [
            "",
            "## Raw Outputs",
            "- Technical JSON artifacts live in `raw_outputs/` next to this file.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_final_result_markdown_with_judge(
    result: FinalEvaluationResult,
    *,
    judge_result: AggregatedJudgeResult | None,
) -> str:
    """Render the final summary with the aggregated judge narrative when available."""
    lines = render_final_result_markdown(result).rstrip().splitlines()
    insertion_index = len(lines)
    for index, line in enumerate(lines):
        if line == "## Dimension Breakdown":
            insertion_index = index
            break

    if judge_result is not None and (
        judge_result.summary
        or judge_result.evidence is not None
        or judge_result.overall_score is not None
        or judge_result.overall_evidence
    ):
        judge_lines = ["", "## Judge Assessment", ""]
        if judge_result.summary:
            judge_lines.append(f"- Summary: {judge_result.summary}")
        if judge_result.overall_score is not None:
            judge_lines.append(f"- Overall score: `{_format_score(judge_result.overall_score)}`")
        if judge_result.overall_evidence:
            judge_lines.append("- Overall evidence:")
            judge_lines.extend(
                [f"  - {entry}" for entry in judge_result.overall_evidence if entry.strip()]
            )
        judge_evidence_lines = _render_judge_evidence(judge_result)
        if judge_evidence_lines:
            judge_lines.append("- Evidence:")
            judge_lines.extend(judge_evidence_lines)
        judge_lines.append("")
        lines[insertion_index:insertion_index] = judge_lines

    return "\n".join(lines).rstrip() + "\n"


def render_failed_evaluation_markdown(
    *,
    case_id: str,
    run_id: str,
    run_status: str,
    evaluation_status: str,
    deterministic_result: DeterministicEvaluationResult,
    judge_result: AggregatedJudgeResult | None,
    warnings: list[str],
) -> str:
    """Render a human-readable Markdown summary when no final result could be produced."""
    lines: list[str] = [
        "# Final Evaluation Summary",
        "",
        "## Overview",
        f"- Case: `{case_id}`",
        f"- Run: `{run_id}`",
        "- Final score: `not available`",
        f"- Run status: `{run_status}`",
        f"- Evaluation status: `{evaluation_status}`",
        (
            "- Deterministic checks: "
            f"{deterministic_result.summary.passed_checks} passed, "
            f"{deterministic_result.summary.failed_checks} failed, "
            f"{deterministic_result.summary.error_checks} error"
        ),
    ]

    if judge_result is None:
        lines.append("- Judge output: not available")
    else:
        lines.append(
            "- Judge output: "
            f"{judge_result.successful_iterations} successful iteration(s), "
            f"{judge_result.failed_iterations} failed iteration(s)"
        )
        if judge_result.summary is not None:
            lines.append(f"- Judge summary: {judge_result.summary}")

    if warnings:
        lines.extend(
            [
                "- Warnings:",
                *[f"  - {warning}" for warning in warnings],
            ]
        )
    else:
        lines.append("- Warnings: none")

        lines.extend(
            [
                "",
                "## Why There Is No Final Result",
                (
                    "- The workflow could not compute a final aggregated "
                    "evaluation artifact for this case."
                ),
                "- Check `raw_outputs/` for the raw judge result and prompt payload.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_judge_evidence(judge_result: AggregatedJudgeResult) -> list[str]:
    evidence = judge_result.evidence
    if evidence is None:
        return []
    lines: list[str] = []
    for name in ("task", "process", "autonomy", "closeness", "efficiency", "spark"):
        entries = getattr(evidence, name)
        if not entries:
            continue
        joined = "; ".join(entry.strip() for entry in entries if entry.strip())
        if joined:
            lines.append(f"  - `{name}`: {joined}")
    return lines


def _render_dimension_table(result: FinalEvaluationResult) -> str:
    headers = ["Dimension", "Deterministic", "Judge", "Final"]
    rows = [
        [
            name.title(),
            _format_optional_score(getattr(result.deterministic_dimensions, name)),
            _format_optional_score(getattr(result.judge_dimensions, name)),
            _format_optional_score(getattr(result.final_dimensions, name)),
        ]
        for name in ("task", "process", "autonomy", "closeness", "efficiency", "spark")
    ]
    return "\n".join([_markdown_table(headers, rows)])


def _markdown_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    header_row = list(headers)
    row_list = [list(row) for row in rows]
    widths = [len(cell) for cell in header_row]
    for row in row_list:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def _format_row(row: Iterable[str]) -> str:
        cells = list(row)
        return (
            "| "
            + " | ".join(cells[index].ljust(widths[index]) for index in range(len(cells)))
            + " |"
        )

    divider = "| " + " | ".join("-" * width for width in widths) + " |"
    lines = [_format_row(header_row), divider]
    lines.extend(_format_row(row) for row in row_list)
    return "\n".join(lines)


def _format_optional_score(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def _format_score(value: float) -> str:
    return f"{value:.2f}"


def _format_dimension_snapshot(dimensions: object) -> str:
    names = ("task", "process", "autonomy", "closeness", "efficiency", "spark")
    parts = [f"{name}={_format_optional_score(getattr(dimensions, name))}" for name in names]
    return ", ".join(parts)
