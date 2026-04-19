"""Rendering and shaping for workflow report outputs."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from personal_agent_eval.aggregation.models import DimensionScores
from personal_agent_eval.reporting.models import ModelSummary, StructuredReport
from personal_agent_eval.reporting.text import join_sections, render_bar, render_table
from personal_agent_eval.workflow import (
    EvaluationAction,
    RunAction,
    UsageSummary,
    WorkflowCaseResult,
    WorkflowResult,
)

DIMENSION_NAMES = (
    "task",
    "process",
    "autonomy",
    "closeness",
    "efficiency",
    "spark",
)


class WorkflowReporter:
    """Pure transformation and rendering utilities for workflow results."""

    def build_report(self, workflow_result: WorkflowResult) -> StructuredReport:
        """Convert a workflow result into a stable structured reporting payload."""
        summaries = [
            self._build_model_summary(model_id, case_results)
            for model_id, case_results in sorted(
                self._group_by_model(workflow_result.results).items(),
                key=lambda item: item[0],
            )
        ]
        summary = workflow_result.summary
        return StructuredReport(
            suite_id=workflow_result.suite_id,
            run_profile_id=workflow_result.run_profile_id,
            evaluation_profile_id=workflow_result.evaluation_profile_id,
            case_results=[case.to_json_dict() for case in workflow_result.results],
            model_summaries=summaries,
            run_cost_usd=summary.run_cost_usd,
            evaluation_cost_usd=summary.evaluation_cost_usd,
            total_cost_usd=summary.total_cost_usd,
        )

    def render_cli(self, workflow_result: WorkflowResult) -> str:
        """Render the full V1 terminal report from a workflow result."""
        report = self.build_report(workflow_result)
        sections = (
            self._render_header(report),
            self.render_case_table(report),
            self.render_model_summary_table(report),
            self.render_dimension_charts(report),
            self.render_model_comparison_chart(report),
        )
        return join_sections(sections)

    def render_case_table(self, report: StructuredReport) -> str:
        """Render the per-model per-case table."""
        rows = [
            [
                case.model_id,
                case.case_id,
                case.run_action.value,
                case.evaluation_action.value,
                f"{case.final_score:.2f}" if case.final_score is not None else "n/a",
                (
                    f"{case.run_latency_seconds:.1f}s"
                    if case.run_latency_seconds is not None
                    else "n/a"
                ),
                str(case.usage.input_tokens),
                str(case.usage.output_tokens),
                self._format_cost(case.run_usage.cost_usd),
                self._format_cost(case.evaluation_usage.cost_usd),
                self._format_cost(case.usage.cost_usd),
                str(len(case.warnings)),
            ]
            for case in sorted(
                self._workflow_cases(report),
                key=lambda item: (item.model_id, item.case_id),
            )
        ]
        return join_sections(
            [
                "Case Results",
                render_table(
                    [
                        "MODEL",
                        "CASE",
                        "RUN",
                        "EVAL",
                        "SCORE",
                        "LATENCY_S",
                        "IN_TOK",
                        "OUT_TOK",
                        "RUN_COST",
                        "EVAL_COST",
                        "TOTAL_COST",
                        "WARNINGS",
                    ],
                    rows,
                ),
            ]
        )

    def render_model_summary_table(self, report: StructuredReport) -> str:
        """Render one summary row per model."""
        rows = [
            [
                summary.model_id,
                str(summary.case_count),
                self._format_optional_score(summary.average_final_score),
                str(summary.run_reused),
                str(summary.run_executed),
                str(summary.run_skipped),
                str(summary.evaluation_reused),
                str(summary.evaluation_executed),
                str(summary.evaluation_skipped),
                (
                    f"{summary.average_latency_seconds:.1f}s"
                    if summary.average_latency_seconds is not None
                    else "n/a"
                ),
                str(summary.total_usage.input_tokens),
                str(summary.total_usage.output_tokens),
                self._format_cost(summary.run_cost_usd),
                self._format_cost(summary.evaluation_cost_usd),
                self._format_cost(summary.total_usage.cost_usd),
                str(summary.warning_count),
            ]
            for summary in report.model_summaries
        ]
        return join_sections(
            [
                "Model Summary",
                render_table(
                    [
                        "MODEL",
                        "CASES",
                        "AVG_SCORE",
                        "RUNS_REUSED",
                        "RUNS_EXECUTED",
                        "RUNS_SKIPPED",
                        "EVALS_REUSED",
                        "EVALS_EXECUTED",
                        "EVALS_SKIPPED",
                        "AVG_LATENCY_S",
                        "IN_TOK",
                        "OUT_TOK",
                        "RUN_COST",
                        "EVAL_COST",
                        "TOTAL_COST",
                        "WARNINGS",
                    ],
                    rows,
                ),
            ]
        )

    def render_dimension_charts(self, report: StructuredReport) -> str:
        """Render per-model average dimension bars."""
        sections: list[str] = ["Dimension Bars"]
        for summary in report.model_summaries:
            sections.append(f"Model: {summary.model_id}")
            for name in DIMENSION_NAMES:
                sections.append(render_bar(name, getattr(summary.average_dimensions, name)))
        return join_sections(sections)

    def render_model_comparison_chart(self, report: StructuredReport) -> str:
        """Render a simple final-score comparison chart by model."""
        lines = ["Model Comparison"]
        for summary in sorted(
            report.model_summaries,
            key=lambda item: (
                item.average_final_score is None,
                -(item.average_final_score or 0.0),
                item.model_id,
            ),
        ):
            lines.append(render_bar(summary.model_id, summary.average_final_score))
        return "\n".join(lines)

    def _render_header(self, report: StructuredReport) -> str:
        return "\n".join(
            [
                f"Suite: {report.suite_id}",
                f"Run profile: {report.run_profile_id or 'n/a'}",
                f"Evaluation profile: {report.evaluation_profile_id or 'n/a'}",
                f"Models: {len(report.model_summaries)}",
                f"Cases: {len(report.case_results)}",
                f"Cost (USD) — runs: {self._format_cost(report.run_cost_usd)}",
                f"Cost (USD) — evaluation: {self._format_cost(report.evaluation_cost_usd)}",
                f"Cost (USD) — total: {self._format_cost(report.total_cost_usd)}",
            ]
        )

    def _build_model_summary(
        self,
        model_id: str,
        case_results: list[WorkflowCaseResult],
    ) -> ModelSummary:
        scored_values = [case.final_score for case in case_results if case.final_score is not None]
        dimension_values = {name: [] for name in DIMENSION_NAMES}
        for case in case_results:
            if case.final_dimensions is None:
                continue
            for name in DIMENSION_NAMES:
                value = getattr(case.final_dimensions, name)
                if value is not None:
                    dimension_values[name].append(value)

        return ModelSummary(
            model_id=model_id,
            case_count=len(case_results),
            run_executed=sum(case.run_action is RunAction.EXECUTED for case in case_results),
            run_reused=sum(case.run_action is RunAction.REUSED for case in case_results),
            run_skipped=sum(case.run_action is RunAction.SKIPPED for case in case_results),
            evaluation_executed=sum(
                case.evaluation_action is EvaluationAction.EXECUTED for case in case_results
            ),
            evaluation_reused=sum(
                case.evaluation_action is EvaluationAction.REUSED for case in case_results
            ),
            evaluation_skipped=sum(
                case.evaluation_action is EvaluationAction.SKIPPED for case in case_results
            ),
            scored_case_count=len(scored_values),
            average_final_score=mean(scored_values) if scored_values else None,
            average_dimensions=DimensionScores(
                **{
                    name: mean(values) if values else None
                    for name, values in dimension_values.items()
                }
            ),
            total_usage=self._sum_usage(case_results),
            average_latency_seconds=self._average_latency(case_results),
            run_cost_usd=sum(case.run_usage.cost_usd for case in case_results),
            evaluation_cost_usd=sum(case.evaluation_usage.cost_usd for case in case_results),
            warning_count=sum(len(case.warnings) for case in case_results),
        )

    def _group_by_model(
        self,
        case_results: list[WorkflowCaseResult],
    ) -> dict[str, list[WorkflowCaseResult]]:
        grouped: dict[str, list[WorkflowCaseResult]] = defaultdict(list)
        for case in case_results:
            grouped[case.model_id].append(case)
        return dict(grouped)

    def _workflow_cases(self, report: StructuredReport) -> list[WorkflowCaseResult]:
        return [WorkflowCaseResult.model_validate(case) for case in report.case_results]

    def _format_optional_score(self, value: float | None) -> str:
        return f"{value:.2f}" if value is not None else "n/a"

    def _format_cost(self, value: float) -> str:
        return f"{value:.5f}"

    def _average_latency(self, case_results: list[WorkflowCaseResult]) -> float | None:
        values = [
            case.run_latency_seconds
            for case in case_results
            if case.run_latency_seconds is not None
        ]
        return mean(values) if values else None

    def _sum_usage(self, case_results: list[WorkflowCaseResult]) -> UsageSummary:
        return UsageSummary(
            input_tokens=sum(case.usage.input_tokens for case in case_results),
            output_tokens=sum(case.usage.output_tokens for case in case_results),
            total_tokens=sum(case.usage.total_tokens for case in case_results),
            reasoning_tokens=sum(case.usage.reasoning_tokens for case in case_results),
            cached_input_tokens=sum(case.usage.cached_input_tokens for case in case_results),
            cache_write_tokens=sum(case.usage.cache_write_tokens for case in case_results),
            cost_usd=sum(case.usage.cost_usd for case in case_results),
        )
