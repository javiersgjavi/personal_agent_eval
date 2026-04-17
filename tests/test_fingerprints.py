from __future__ import annotations

from pathlib import Path

from personal_agent_eval.config import (
    load_evaluation_profile,
    load_run_profile,
    load_suite_config,
    load_test_config,
)
from personal_agent_eval.fingerprints import (
    ReuseAction,
    build_evaluation_fingerprint_input,
    build_run_fingerprint_input,
    decide_reuse,
    is_evaluation_reusable,
    is_run_reusable,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_run_fingerprint_is_stable_across_equivalent_case_paths(tmp_path: Path) -> None:
    original_case = FIXTURES_ROOT / "cases" / "example_case"
    copied_case = tmp_path / "copied_case"
    copied_case.mkdir(parents=True)
    (copied_case / "artifacts").mkdir()
    (copied_case / "hooks").mkdir()

    (copied_case / "messages.yaml").write_text(
        (original_case / "messages.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (copied_case / "artifacts" / "prompt.txt").write_text(
        (original_case / "artifacts" / "prompt.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (copied_case / "hooks" / "custom_check.py").write_text(
        (original_case / "hooks" / "custom_check.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (copied_case / "test.yaml").write_text(
        (original_case / "test.yaml")
        .read_text(encoding="utf-8")
        .replace("case_id: example_case", "case_id: copied_case"),
        encoding="utf-8",
    )

    original_test = load_test_config(original_case / "test.yaml")
    copied_test = load_test_config(copied_case / "test.yaml")
    run_profile = load_run_profile(FIXTURES_ROOT / "run_profiles" / "default.yaml")
    suite = load_suite_config(FIXTURES_ROOT / "suites" / "example_suite.yaml")
    model_selection = suite.models[0]

    original_input = build_run_fingerprint_input(
        test_config=original_test,
        run_profile=run_profile,
        model_selection=model_selection,
    )
    copied_input = build_run_fingerprint_input(
        test_config=copied_test,
        run_profile=run_profile,
        model_selection=model_selection,
    )

    assert original_input.fingerprint == copied_input.fingerprint
    assert original_input.payload.input_messages == copied_input.payload.input_messages
    assert original_input.payload.attachments == copied_input.payload.attachments


def test_run_fingerprint_changes_when_execution_settings_change() -> None:
    test_config = load_test_config(FIXTURES_ROOT / "cases" / "example_case" / "test.yaml")
    run_profile = load_run_profile(FIXTURES_ROOT / "run_profiles" / "default.yaml")
    suite = load_suite_config(FIXTURES_ROOT / "suites" / "example_suite.yaml")
    model_selection = suite.models[0]

    base_input = build_run_fingerprint_input(
        test_config=test_config,
        run_profile=run_profile,
        model_selection=model_selection,
    )
    changed_profile = run_profile.model_copy(
        update={"runner_defaults": {**run_profile.runner_defaults, "timeout_seconds": 45}}
    )
    changed_input = build_run_fingerprint_input(
        test_config=test_config,
        run_profile=changed_profile,
        model_selection=model_selection,
    )

    assert base_input.fingerprint != changed_input.fingerprint


def test_evaluation_fingerprint_ignores_profile_id_but_changes_on_semantic_changes() -> None:
    evaluation_profile = load_evaluation_profile(
        FIXTURES_ROOT / "evaluation_profiles" / "default.yaml"
    )

    renamed_profile = evaluation_profile.model_copy(
        update={
            "evaluation_profile_id": "renamed",
            "title": "Renamed profile",
        }
    )
    reordered_profile = evaluation_profile.model_copy(
        update={
            "judges": list(reversed(evaluation_profile.judges)),
            "judge_runs": list(reversed(evaluation_profile.judge_runs)),
            "anchors": evaluation_profile.anchors.model_copy(
                update={"references": list(reversed(evaluation_profile.anchors.references))}
            ),
        }
    )
    changed_profile = evaluation_profile.model_copy(
        update={
            "final_aggregation": evaluation_profile.final_aggregation.model_copy(
                update={
                    "final_score_weights": (
                        evaluation_profile.final_aggregation.final_score_weights.model_copy(
                            update={"task": 0.5}
                        )
                    )
                }
            )
        }
    )

    base_input = build_evaluation_fingerprint_input(evaluation_profile=evaluation_profile)
    renamed_input = build_evaluation_fingerprint_input(evaluation_profile=renamed_profile)
    reordered_input = build_evaluation_fingerprint_input(evaluation_profile=reordered_profile)
    changed_input = build_evaluation_fingerprint_input(evaluation_profile=changed_profile)

    assert base_input.fingerprint == renamed_input.fingerprint
    assert base_input.fingerprint == reordered_input.fingerprint
    assert base_input.fingerprint != changed_input.fingerprint


def test_reuse_decision_helpers_follow_v1_rules() -> None:
    same_everything = decide_reuse(
        requested_run_fingerprint="a" * 64,
        requested_evaluation_fingerprint="b" * 64,
        stored_run_fingerprint="a" * 64,
        stored_evaluation_fingerprint="b" * 64,
    )
    same_run_new_eval = decide_reuse(
        requested_run_fingerprint="a" * 64,
        requested_evaluation_fingerprint="c" * 64,
        stored_run_fingerprint="a" * 64,
        stored_evaluation_fingerprint="b" * 64,
    )
    new_run = decide_reuse(
        requested_run_fingerprint="d" * 64,
        requested_evaluation_fingerprint="b" * 64,
        stored_run_fingerprint="a" * 64,
        stored_evaluation_fingerprint="b" * 64,
    )

    assert same_everything.action is ReuseAction.REUSE_ALL
    assert same_everything.run_reusable is True
    assert same_everything.evaluation_reusable is True
    assert same_run_new_eval.action is ReuseAction.REUSE_RUN_ONLY
    assert same_run_new_eval.run_reusable is True
    assert same_run_new_eval.evaluation_reusable is False
    assert new_run.action is ReuseAction.EXECUTE_NEW_RUN
    assert new_run.run_reusable is False
    assert new_run.evaluation_reusable is False
    assert is_run_reusable(
        requested_run_fingerprint="a" * 64,
        stored_run_fingerprint="a" * 64,
    )
    assert is_evaluation_reusable(
        requested_run_fingerprint="a" * 64,
        requested_evaluation_fingerprint="b" * 64,
        stored_run_fingerprint="a" * 64,
        stored_evaluation_fingerprint="b" * 64,
    )
