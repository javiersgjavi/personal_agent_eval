from __future__ import annotations

from pathlib import Path

from personal_agent_eval.catalog import discover_cases, expand_suite
from personal_agent_eval.config import load_run_profile, load_suite_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_repo_llm_probe_examples_suite_expands() -> None:
    expanded = expand_suite(REPO_ROOT, "llm_probe_examples")

    assert {item.case_id for item in expanded} == {
        "llm_probe_browser_example",
        "llm_probe_tool_example",
    }


def test_repo_openclaw_examples_suite_expands() -> None:
    expanded = expand_suite(REPO_ROOT, "openclaw_examples")

    assert {item.case_id for item in expanded} == {
        "openclaw_browser_example",
        "openclaw_tool_example",
    }


def test_repo_examples_use_expected_models_and_profiles() -> None:
    llm_probe_suite = load_suite_config(
        REPO_ROOT / "configs" / "suites" / "llm_probe_examples.yaml"
    )
    openclaw_suite = load_suite_config(REPO_ROOT / "configs" / "suites" / "openclaw_examples.yaml")
    llm_probe_profile = load_run_profile(
        REPO_ROOT / "configs" / "run_profiles" / "llm_probe_examples.yaml"
    )
    openclaw_profile = load_run_profile(
        REPO_ROOT / "configs" / "run_profiles" / "openclaw_examples.yaml"
    )

    assert llm_probe_suite.models[0].requested_model == "minimax/minimax-m2.7"
    assert openclaw_suite.models[0].requested_model == "minimax/minimax-m2.7"
    assert llm_probe_profile.run_profile_id == "llm_probe_examples"
    assert openclaw_profile.run_profile_id == "openclaw_examples"
    assert openclaw_profile.openclaw is not None
    assert openclaw_profile.openclaw.agent_id == "basic_agent"


def test_repo_discovers_public_example_cases() -> None:
    cases = discover_cases(REPO_ROOT)

    assert cases["llm_probe_tool_example"].config.runner.type == "llm_probe"
    assert cases["llm_probe_browser_example"].config.runner.type == "llm_probe"
    assert cases["openclaw_tool_example"].config.runner.type == "openclaw"
    assert cases["openclaw_browser_example"].config.runner.type == "openclaw"
