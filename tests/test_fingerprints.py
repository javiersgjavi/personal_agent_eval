from __future__ import annotations

import shutil
from pathlib import Path

from personal_agent_eval.config import (
    load_evaluation_profile,
    load_openclaw_agent,
    load_run_profile,
    load_suite_config,
    load_test_config,
)
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import TestConfig
from personal_agent_eval.domains.openclaw import materialize_openclaw_workspace
from personal_agent_eval.fingerprints import (
    ReuseAction,
    build_evaluation_fingerprint_input,
    build_openclaw_agent_fingerprint_input,
    build_run_fingerprint_input,
    build_run_profile_fingerprint,
    decide_reuse,
    is_evaluation_reusable,
    is_run_reusable,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_run_fingerprint_is_stable_across_equivalent_case_paths(tmp_path: Path) -> None:
    original_case = FIXTURES_ROOT / "configs" / "cases" / "example_case"
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
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "default.yaml")
    suite = load_suite_config(FIXTURES_ROOT / "configs" / "suites" / "example_suite.yaml")
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
    test_config = load_test_config(
        FIXTURES_ROOT / "configs" / "cases" / "example_case" / "test.yaml"
    )
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "default.yaml")
    suite = load_suite_config(FIXTURES_ROOT / "configs" / "suites" / "example_suite.yaml")
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


def test_openclaw_agent_fingerprint_is_stable_across_equivalent_materializations(
    tmp_path: Path,
) -> None:
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    assert agent_config.workspace_dir is not None
    first_workspace = materialize_openclaw_workspace(
        template_dir=agent_config.workspace_dir,
        workspace_dir=tmp_path / "first" / "workspace",
    )
    second_workspace = materialize_openclaw_workspace(
        template_dir=agent_config.workspace_dir,
        workspace_dir=tmp_path / "second" / "workspace",
    )

    first_input = build_openclaw_agent_fingerprint_input(
        agent_config=agent_config,
        workspace_manifest=first_workspace.manifest,
    )
    second_input = build_openclaw_agent_fingerprint_input(
        agent_config=agent_config,
        workspace_manifest=second_workspace.manifest,
    )

    assert first_input.fingerprint == second_input.fingerprint
    assert first_input.payload.workspace_entries == second_input.payload.workspace_entries
    assert {entry.source for entry in first_input.payload.workspace_entries} == {
        "template",
        "placeholder",
    }


def test_openclaw_agent_fingerprint_changes_when_workspace_contents_change(tmp_path: Path) -> None:
    source_agent_dir = FIXTURES_ROOT / "configs" / "agents" / "support_agent"
    copied_agent_dir = tmp_path / "support_agent"
    shutil.copytree(source_agent_dir, copied_agent_dir)
    (copied_agent_dir / "workspace" / "AGENTS.md").write_text(
        "# Support Agent\n\nChanged workspace content.\n",
        encoding="utf-8",
    )

    original_agent = load_openclaw_agent(source_agent_dir)
    changed_agent = load_openclaw_agent(copied_agent_dir)
    assert original_agent.workspace_dir is not None
    assert changed_agent.workspace_dir is not None
    original_workspace = materialize_openclaw_workspace(
        template_dir=original_agent.workspace_dir,
        workspace_dir=tmp_path / "original-run" / "workspace",
    )
    changed_workspace = materialize_openclaw_workspace(
        template_dir=changed_agent.workspace_dir,
        workspace_dir=tmp_path / "changed-run" / "workspace",
    )

    original_input = build_openclaw_agent_fingerprint_input(
        agent_config=original_agent,
        workspace_manifest=original_workspace.manifest,
    )
    changed_input = build_openclaw_agent_fingerprint_input(
        agent_config=changed_agent,
        workspace_manifest=changed_workspace.manifest,
    )

    assert original_input.fingerprint != changed_input.fingerprint


def test_openclaw_run_fingerprint_uses_agent_identity_and_image_but_not_timeout(
    tmp_path: Path,
) -> None:
    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    assert run_profile.openclaw is not None
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    assert agent_config.workspace_dir is not None
    materialized_workspace = materialize_openclaw_workspace(
        template_dir=agent_config.workspace_dir,
        workspace_dir=tmp_path / "workspace",
    )
    agent_input = build_openclaw_agent_fingerprint_input(
        agent_config=agent_config,
        workspace_manifest=materialized_workspace.manifest,
    )
    model_selection = ModelConfig.model_validate(
        {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
    )

    base_input = build_run_fingerprint_input(
        test_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        openclaw_agent_fingerprint=agent_input.fingerprint,
    )
    changed_timeout_profile = run_profile.model_copy(
        update={
            "openclaw": run_profile.openclaw.model_copy(update={"timeout_seconds": 999}),
        }
    )
    changed_timeout_input = build_run_fingerprint_input(
        test_config=case_config,
        run_profile=changed_timeout_profile,
        model_selection=model_selection,
        openclaw_agent_fingerprint=agent_input.fingerprint,
    )
    changed_image_profile = run_profile.model_copy(
        update={
            "openclaw": run_profile.openclaw.model_copy(
                update={"image": "ghcr.io/openclaw/openclaw-base:9.9.9"}
            ),
        }
    )
    changed_image_input = build_run_fingerprint_input(
        test_config=case_config,
        run_profile=changed_image_profile,
        model_selection=model_selection,
        openclaw_agent_fingerprint=agent_input.fingerprint,
    )
    changed_agent_input = build_run_fingerprint_input(
        test_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        openclaw_agent_fingerprint="f" * 64,
    )

    assert base_input.payload.runner_config == {
        "agent_fingerprint": agent_input.fingerprint,
        "image": "ghcr.io/openclaw/openclaw-base:0.1.0",
    }
    assert base_input.fingerprint == changed_timeout_input.fingerprint
    assert base_input.fingerprint != changed_image_input.fingerprint
    assert base_input.fingerprint != changed_agent_input.fingerprint


def test_openclaw_run_fingerprint_requires_agent_fingerprint(tmp_path: Path) -> None:
    case_config = _write_openclaw_case(tmp_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    model_selection = ModelConfig.model_validate(
        {"model_id": "baseline_model", "requested_model": "openai/gpt-4o-mini"}
    )

    try:
        build_run_fingerprint_input(
            test_config=case_config,
            run_profile=run_profile,
            model_selection=model_selection,
        )
    except ValueError as exc:
        assert "requires an OpenClaw agent fingerprint" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected OpenClaw run fingerprinting to reject missing agent input.")


def test_run_profile_fingerprint_ignores_openclaw_timeout_but_changes_on_image() -> None:
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    assert run_profile.openclaw is not None

    base_fingerprint = build_run_profile_fingerprint(run_profile=run_profile)
    changed_timeout_fingerprint = build_run_profile_fingerprint(
        run_profile=run_profile.model_copy(
            update={
                "openclaw": run_profile.openclaw.model_copy(update={"timeout_seconds": 999}),
            }
        )
    )
    changed_image_fingerprint = build_run_profile_fingerprint(
        run_profile=run_profile.model_copy(
            update={
                "openclaw": run_profile.openclaw.model_copy(
                    update={"image": "ghcr.io/openclaw/openclaw-base:9.9.9"}
                ),
            }
        )
    )

    assert base_fingerprint == changed_timeout_fingerprint
    assert base_fingerprint != changed_image_fingerprint


def test_evaluation_fingerprint_ignores_profile_id_but_changes_on_semantic_changes() -> None:
    evaluation_profile = load_evaluation_profile(
        FIXTURES_ROOT / "configs" / "evaluation_profiles" / "default.yaml"
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


def _write_openclaw_case(tmp_path: Path) -> TestConfig:
    path = tmp_path / "openclaw_case.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: openclaw_case",
                "title: OpenClaw case",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: system",
                "      content: You are careful.",
                "    - role: user",
                "      content: Solve the task.",
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return load_test_config(path)
