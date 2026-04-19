from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent_eval.reporting import WorkflowReporter
from personal_agent_eval.reporting.score_cost_chart import render_score_cost_chart_png
from personal_agent_eval.workflow import (
    EvaluationAction,
    RunAction,
    UsageSummary,
    WorkflowCaseResult,
    WorkflowResult,
    WorkflowSummary,
)


def _minimal_report_workflow() -> WorkflowResult:
    return WorkflowResult(
        command="report",
        workspace_root="/tmp/workspace",
        suite_id="s",
        run_profile_id="rp",
        evaluation_profile_id="ep",
        results=[
            WorkflowCaseResult(
                model_id="vendor/model-a",
                case_id="c1",
                run_fingerprint="a" * 64,
                evaluation_fingerprint="b" * 64,
                run_action=RunAction.EXECUTED,
                evaluation_action=EvaluationAction.EXECUTED,
                run_status="success",
                evaluation_status="success",
                final_score=7.5,
                run_latency_seconds=15.0,
                run_usage=UsageSummary(cost_usd=0.01),
                evaluation_usage=UsageSummary(cost_usd=0.02),
                usage=UsageSummary(cost_usd=0.03),
            ),
            WorkflowCaseResult(
                model_id="vendor/model-b",
                case_id="c1",
                run_fingerprint="a" * 64,
                evaluation_fingerprint="b" * 64,
                run_action=RunAction.EXECUTED,
                evaluation_action=EvaluationAction.EXECUTED,
                run_status="success",
                evaluation_status="success",
                final_score=8.0,
                run_latency_seconds=45.0,
                run_usage=UsageSummary(cost_usd=0.05),
                evaluation_usage=UsageSummary(cost_usd=0.10),
                usage=UsageSummary(cost_usd=0.15),
            ),
        ],
        summary=WorkflowSummary(
            models_requested=2,
            cases_requested=1,
            model_case_pairs=2,
            runs_executed=2,
            runs_reused=0,
            evaluations_executed=2,
            evaluations_reused=0,
            final_results_recomputed=0,
            run_cost_usd=0.06,
            evaluation_cost_usd=0.12,
            total_cost_usd=0.18,
        ),
    )


def test_render_score_cost_chart_writes_png(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")

    report = WorkflowReporter().build_report(_minimal_report_workflow())
    out = tmp_path / "chart.png"
    render_score_cost_chart_png(report, out, footnote="Test footnote")
    assert out.is_file()
    assert out.stat().st_size > 2000


def test_render_score_cost_chart_raises_without_scores(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")

    wf = _minimal_report_workflow()
    wf = wf.model_copy(
        update={
            "results": [
                wf.results[0].model_copy(update={"final_score": None}),
                wf.results[1].model_copy(update={"final_score": None}),
            ]
        }
    )
    report = WorkflowReporter().build_report(wf)
    with pytest.raises(ValueError, match="cannot render the score/cost chart"):
        render_score_cost_chart_png(report, tmp_path / "x.png")
