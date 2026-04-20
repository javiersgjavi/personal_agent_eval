from __future__ import annotations

from typing import Any, cast

import pytest

from personal_agent_eval.aggregation.models import DimensionScores
from personal_agent_eval.reporting import WorkflowReporter
from personal_agent_eval.workflow import (
    EvaluationAction,
    RunAction,
    UsageSummary,
    WorkflowCaseResult,
    WorkflowResult,
    WorkflowSummary,
)
from personal_agent_eval.workflow.models import OpenClawWorkflowEvidenceSummary

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
    assert minimax_summary.total_usage.input_tokens == 280
    assert minimax_summary.total_usage.output_tokens == 90
    assert minimax_summary.total_usage.cost_usd == pytest.approx(0.008)
    assert minimax_summary.run_cost_usd == pytest.approx(0.003)
    assert minimax_summary.evaluation_cost_usd == pytest.approx(0.005)

    assert report.run_cost_usd == pytest.approx(0.006)
    assert report.evaluation_cost_usd == pytest.approx(0.0095)
    assert report.total_cost_usd == pytest.approx(0.0155)

    gpt_summary = next(
        summary for summary in report.model_summaries if summary.model_id == "openai/gpt-5.4"
    )
    assert gpt_summary.case_count == 1
    assert gpt_summary.average_final_score == 8.2
    assert gpt_summary.total_usage.input_tokens == 220
    assert gpt_summary.run_cost_usd == pytest.approx(0.003)
    assert gpt_summary.evaluation_cost_usd == pytest.approx(0.0045)
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
    assert "RUN_COST" in output
    assert "EVAL_COST" in output
    assert "TOTAL_COST" in output
    assert "LATENCY_S" in output
    assert "AVG_LATENCY_S" in output
    assert "Cost (USD) — runs:" in output
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


def test_structured_report_includes_openclaw_storage_fields_when_present() -> None:
    oc = OpenClawWorkflowEvidenceSummary(
        agent_id="support_agent",
        container_image="ghcr.io/openclaw/openclaw-base:0.1.0",
        evidence_paths={
            "openclaw_generated_config": (
                "outputs/runs/suit_s/run_profile_aaaaaa/m/c/run_1.artifacts/x--openclaw.json"
            ),
        },
    )
    result = WorkflowResult(
        command="run",
        workspace_root="/w",
        suite_id="s",
        run_profile_id="rp",
        results=[
            WorkflowCaseResult(
                model_id="m",
                case_id="c",
                run_fingerprint=RUN_FP_A,
                run_action=RunAction.EXECUTED,
                run_status="success",
                runner_type="openclaw",
                stored_run_artifact_path="outputs/runs/suit_s/run_profile_aaaaaa/m/c/run_1.json",
                stored_run_fingerprint_input_path=(
                    "outputs/runs/suit_s/run_profile_aaaaaa/m/c/run_1.fingerprint_input.json"
                ),
                stored_run_artifacts_dir="outputs/runs/suit_s/run_profile_aaaaaa/m/c/run_1.artifacts",
                openclaw_evidence=oc,
            ),
        ],
        summary=WorkflowSummary(
            models_requested=1,
            cases_requested=1,
            model_case_pairs=1,
            runs_executed=1,
            runs_reused=0,
            evaluations_executed=0,
            evaluations_reused=0,
            final_results_recomputed=0,
        ),
    )
    row = cast(dict[str, Any], WorkflowReporter().build_report(result).case_results[0])
    assert row["runner_type"] == "openclaw"
    assert cast(str, row["stored_run_artifact_path"]).endswith("run_1.json")
    oc_row = cast(dict[str, Any], row["openclaw_evidence"])
    assert oc_row["agent_id"] == "support_agent"
    assert "openclaw_generated_config" in cast(dict[str, Any], oc_row["evidence_paths"])


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
                run_latency_seconds=12.5,
                final_dimensions=DimensionScores(
                    task=8.0,
                    process=7.2,
                    autonomy=7.0,
                    closeness=6.5,
                    efficiency=6.8,
                    spark=6.0,
                ),
                run_usage=UsageSummary(
                    input_tokens=50,
                    output_tokens=20,
                    total_tokens=70,
                    cost_usd=0.002,
                ),
                evaluation_usage=UsageSummary(
                    input_tokens=70,
                    output_tokens=20,
                    total_tokens=90,
                    cost_usd=0.003,
                ),
                usage=UsageSummary(
                    input_tokens=120,
                    output_tokens=40,
                    total_tokens=160,
                    cost_usd=0.005,
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
                run_latency_seconds=9.0,
                final_dimensions=DimensionScores(
                    task=7.0,
                    process=6.8,
                    autonomy=6.5,
                    closeness=6.0,
                    efficiency=6.0,
                    spark=5.5,
                ),
                run_usage=UsageSummary(
                    input_tokens=60,
                    output_tokens=20,
                    total_tokens=80,
                    cost_usd=0.001,
                ),
                evaluation_usage=UsageSummary(
                    input_tokens=100,
                    output_tokens=30,
                    total_tokens=130,
                    cost_usd=0.002,
                ),
                usage=UsageSummary(
                    input_tokens=160,
                    output_tokens=50,
                    total_tokens=210,
                    cost_usd=0.003,
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
                run_latency_seconds=22.0,
                final_dimensions=DimensionScores(
                    task=8.8,
                    process=8.1,
                    autonomy=8.0,
                    closeness=7.4,
                    efficiency=7.8,
                    spark=7.2,
                ),
                run_usage=UsageSummary(
                    input_tokens=90,
                    output_tokens=40,
                    total_tokens=130,
                    cost_usd=0.003,
                ),
                evaluation_usage=UsageSummary(
                    input_tokens=130,
                    output_tokens=40,
                    total_tokens=170,
                    cost_usd=0.0045,
                ),
                usage=UsageSummary(
                    input_tokens=220,
                    output_tokens=80,
                    total_tokens=300,
                    cost_usd=0.0075,
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
            run_cost_usd=0.006,
            evaluation_cost_usd=0.0095,
            total_cost_usd=0.0155,
        ),
    )
