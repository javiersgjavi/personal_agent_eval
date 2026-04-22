from __future__ import annotations

from pathlib import Path

from personal_agent_eval.config import load_test_config
from personal_agent_eval.judge.subject_view import (
    build_judge_subject_view,
    render_judge_user_text,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_render_judge_user_text_includes_rubric_tables_when_present() -> None:
    test_config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )
    view = build_judge_subject_view(
        test_config=test_config,
        run_artifact=_minimal_success_artifact(),
        deterministic_summary={
            "passed_checks": 0,
            "failed_checks": 0,
            "error_checks": 0,
            "total_checks": 0,
        },
    )
    rendered = render_judge_user_text(view)
    assert "Rubric (optional guidance)" in rendered
    assert "Scale anchors" in rendered
    assert "| Score | Meaning |" in rendered
    assert "Criteria" in rendered
    assert "| Criterion | What “high” looks like | What “low” looks like |" in rendered


def test_render_judge_user_text_omits_rubric_section_when_missing() -> None:
    test_config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )
    test_config = test_config.model_copy(update={"rubric": None})
    view = build_judge_subject_view(
        test_config=test_config,
        run_artifact=_minimal_success_artifact(),
        deterministic_summary=None,
    )
    rendered = render_judge_user_text(view)
    assert "Rubric (optional guidance)" not in rendered


def _minimal_success_artifact():
    # Import locally to keep this test focused on prompt rendering.
    from personal_agent_eval.artifacts import RunStatus
    from personal_agent_eval.artifacts.run_artifact import (
        MessageTraceEvent,
        RunArtifact,
        RunArtifactIdentity,
        RunRequestMetadata,
    )

    return RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="run_001",
            case_id="example_case",
            suite_id="example_suite",
            run_profile_id="default",
            runner_type="llm_probe",
        ),
        status=RunStatus.SUCCESS,
        request=RunRequestMetadata(requested_model="minimax/minimax-m2.7"),
        trace=[
            MessageTraceEvent(
                sequence=0,
                event_type="message",
                role="assistant",
                content="done",
            )
        ],
    )
