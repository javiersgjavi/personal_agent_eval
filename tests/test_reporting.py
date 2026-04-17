from __future__ import annotations

from personal_agent_eval.aggregation.models import DimensionScores
from personal_agent_eval.reporting import WorkflowReporter
from personal_agent_eval.workflow import (
    EvaluationAction,
    RunAction,
    WorkflowCaseResult,
    WorkflowResult,
    WorkflowSummary,
)

RUN_FP_A = "a" * 64
RUN_FP_B = "b" * 64
EVAL_FP_A = "c" * 64
EVAL_FP_B = "d" * 64


def test_build_report_groups_by_model_and_summarizes_scores() -> None:
    report = WorkflowReporter().build_report(_workflow_result_fixture())

    assert report.suite_id == "benchmark_suite"
    assert len(report.case_results) == 3
    assert len(report.model_summaries) == 2

    minimax_summary = next(
        summary for summary in report.model_summaries if summary.model_id == "minimax/minimax-m2.7"
    )
    assert minimax_summary.case_count == 2
    assert minimax_summary.run_reused == 1
    assert minimax_summary.run_executed == 1
    assert minimax_summary.evaluation_executed == 2
    assert minimax_summary.average_final_score == 7.0
    assert minimax_summary.average_dimensions.task == 7.5

    gpt_summary = next(
        summary for summary in report.model_summaries if summary.model_id == "openai/gpt-5.4"
    )
    assert gpt_summary.case_count == 1
    assert gpt_summary.average_final_score == 8.2
    assert gpt_summary.warning_count == 0


def test_render_cli_contains_tables_and_ascii_charts() -> None:
    output = WorkflowReporter().render_cli(_workflow_result_fixture())

    assert "Case Results" in output
    assert "Model Summary" in output
    assert "Dimension Bars" in output
    assert "Model Comparison" in output
    assert "minimax/minimax-m2.7" in output
    assert "openai/gpt-5.4" in output
    assert "task" in output
    assert "#" in output


def test_structured_report_is_json_serializable_and_preserves_fingerprints() -> None:
    report = WorkflowReporter().build_report(_workflow_result_fixture())
    payload = report.to_json_dict()

    assert payload["suite_id"] == "benchmark_suite"
    first_case = payload["case_results"][0]
    assert first_case["run_fingerprint"] == RUN_FP_A
    assert first_case["evaluation_fingerprint"] == EVAL_FP_A
    assert payload["model_summaries"][0]["model_id"] in {
        "minimax/minimax-m2.7",
        "openai/gpt-5.4",
    }


def _workflow_result_fixture() -> WorkflowResult:
    return WorkflowResult(
        command="report",
        workspace_root="/tmp/workspace",
        suite_id="benchmark_suite",
        run_profile_id="default_run",
        evaluation_profile_id="default_eval",
        results=[
            WorkflowCaseResult(
                model_id="minimax/minimax-m2.7",
                case_id="case_alpha",
                run_action=RunAction.REUSED,
                evaluation_action=EvaluationAction.EXECUTED,
                run_status="success",
                evaluation_status="success",
                run_fingerprint=RUN_FP_A,
                evaluation_fingerprint=EVAL_FP_A,
                final_score=7.4,
                final_dimensions=DimensionScores(
                    task=8.0,
                    process=7.2,
                    autonomy=7.0,
                    closeness=6.5,
                    efficiency=6.8,
                    spark=6.0,
                ),
                warnings=["Judge iteration 2 failed and was excluded."],
            ),
            WorkflowCaseResult(
                model_id="minimax/minimax-m2.7",
                case_id="case_beta",
                run_action=RunAction.EXECUTED,
                evaluation_action=EvaluationAction.EXECUTED,
                run_status="success",
                evaluation_status="success",
                run_fingerprint=RUN_FP_A,
                evaluation_fingerprint=EVAL_FP_A,
                final_score=6.6,
                final_dimensions=DimensionScores(
                    task=7.0,
                    process=6.8,
                    autonomy=6.5,
                    closeness=6.0,
                    efficiency=6.0,
                    spark=5.5,
                ),
                warnings=[],
            ),
            WorkflowCaseResult(
                model_id="openai/gpt-5.4",
                case_id="case_alpha",
                run_action=RunAction.EXECUTED,
                evaluation_action=EvaluationAction.REUSED,
                run_status="success",
                evaluation_status="success",
                run_fingerprint=RUN_FP_B,
                evaluation_fingerprint=EVAL_FP_B,
                final_score=8.2,
                final_dimensions=DimensionScores(
                    task=8.8,
                    process=8.1,
                    autonomy=8.0,
                    closeness=7.4,
                    efficiency=7.8,
                    spark=7.2,
                ),
                warnings=[],
            ),
        ],
        summary=WorkflowSummary(
            models_requested=2,
            cases_requested=2,
            model_case_pairs=3,
            runs_executed=2,
            runs_reused=1,
            evaluations_executed=2,
            evaluations_reused=1,
            final_results_recomputed=0,
        ),
    )
