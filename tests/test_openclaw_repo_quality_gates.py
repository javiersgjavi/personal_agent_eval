"""Quality gates using the bundled workspace fixture (mirrors a full configs/ tree)."""

from __future__ import annotations

from pathlib import Path

from personal_agent_eval.catalog import discover_cases, discover_suites, expand_suite
from personal_agent_eval.config import (
    load_openclaw_agent,
    load_run_profile,
    load_suite_config,
    load_test_config,
)
from personal_agent_eval.domains.openclaw import materialize_openclaw_workspace
from personal_agent_eval.domains.openclaw.resolution import (
    openrouter_primary_model_ref,
    render_openclaw_json,
    resolve_openclaw_config,
)
from personal_agent_eval.fingerprints import (
    build_openclaw_agent_fingerprint_input,
    build_run_fingerprint_input,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_WORKSPACE_ROOT = REPO_ROOT / "tests" / "fixtures" / "bundled_workspace"


def test_repo_discovers_openclaw_smoke_case_without_duplicate_ids() -> None:
    cases = discover_cases(BUNDLED_WORKSPACE_ROOT)
    assert "openclaw_smoke" in cases
    assert cases["openclaw_smoke"].config.runner.type == "openclaw"


def test_repo_openclaw_smoke_suite_expands() -> None:
    expanded = expand_suite(BUNDLED_WORKSPACE_ROOT, "openclaw_smoke_suite")
    assert len(expanded) == 1
    assert expanded[0].case_id == "openclaw_smoke"


def test_repo_support_agent_loads() -> None:
    agent = load_openclaw_agent(BUNDLED_WORKSPACE_ROOT / "configs" / "agents" / "support_agent")
    assert agent.agent_id == "support_agent"
    assert agent.workspace_dir is not None
    assert (agent.workspace_dir / "AGENTS.md").is_file()


def test_repo_tapas_agent_loads() -> None:
    agent = load_openclaw_agent(BUNDLED_WORKSPACE_ROOT / "configs" / "agents" / "tapas")
    assert agent.agent_id == "tapas"
    assert agent.workspace_dir is not None
    assert (agent.workspace_dir / "AGENTS.md").is_file()


def test_repo_openclaw_run_profile_has_openclaw_block() -> None:
    profile = load_run_profile(
        BUNDLED_WORKSPACE_ROOT / "configs" / "run_profiles" / "openclaw_smoke.yaml"
    )
    assert profile.openclaw is not None
    assert profile.openclaw.agent_id == "support_agent"


def test_repo_openclaw_tapas_run_profile_points_at_tapas_agent() -> None:
    profile = load_run_profile(
        BUNDLED_WORKSPACE_ROOT / "configs" / "run_profiles" / "openclaw_tapas.yaml"
    )
    assert profile.openclaw is not None
    assert profile.openclaw.agent_id == "tapas"


def test_repo_openclaw_smoke_fingerprint_is_stable(tmp_path: Path) -> None:
    case = load_test_config(
        BUNDLED_WORKSPACE_ROOT / "configs" / "cases" / "openclaw_smoke" / "test.yaml"
    )
    run_profile = load_run_profile(
        BUNDLED_WORKSPACE_ROOT / "configs" / "run_profiles" / "openclaw_smoke.yaml"
    )
    suite = load_suite_config(
        BUNDLED_WORKSPACE_ROOT / "configs" / "suites" / "openclaw_smoke_suite.yaml"
    )
    model = suite.models[0]
    agent = load_openclaw_agent(BUNDLED_WORKSPACE_ROOT / "configs" / "agents" / "support_agent")
    assert agent.workspace_dir is not None
    materialized = materialize_openclaw_workspace(
        template_dir=agent.workspace_dir,
        workspace_dir=tmp_path / "ws",
    )
    agent_input = build_openclaw_agent_fingerprint_input(
        agent_config=agent,
        workspace_manifest=materialized.manifest,
    )
    first = build_run_fingerprint_input(
        test_config=case,
        run_profile=run_profile,
        model_selection=model,
        openclaw_agent_fingerprint=agent_input.fingerprint,
    )
    second = build_run_fingerprint_input(
        test_config=case,
        run_profile=run_profile,
        model_selection=model,
        openclaw_agent_fingerprint=agent_input.fingerprint,
    )
    assert first.fingerprint == second.fingerprint


def test_repo_resolve_openclaw_config_matches_agent_and_model(tmp_path: Path) -> None:
    case = load_test_config(
        BUNDLED_WORKSPACE_ROOT / "configs" / "cases" / "openclaw_smoke" / "test.yaml"
    )
    run_profile = load_run_profile(
        BUNDLED_WORKSPACE_ROOT / "configs" / "run_profiles" / "openclaw_smoke.yaml"
    )
    suite = load_suite_config(
        BUNDLED_WORKSPACE_ROOT / "configs" / "suites" / "openclaw_smoke_suite.yaml"
    )
    agent = load_openclaw_agent(BUNDLED_WORKSPACE_ROOT / "configs" / "agents" / "support_agent")
    assert agent.workspace_dir is not None
    materialized = materialize_openclaw_workspace(
        template_dir=agent.workspace_dir,
        workspace_dir=tmp_path / "ws",
    )
    resolved = resolve_openclaw_config(
        case_config=case,
        run_profile=run_profile,
        model_selection=suite.models[0],
        agent_config=agent,
        workspace_dir=materialized.workspace_dir,
        state_dir=tmp_path / "state",
    )
    assert resolved.agent_id == "support_agent"
    assert resolved.requested_model == "openai/gpt-example"
    assert resolved.openclaw_primary_model_ref == "openrouter/openai/gpt-example"
    assert resolved.container_image == "ghcr.io/openclaw/openclaw-base:0.1.0"
    assert resolved.openclaw_workspace_path_in_config == str(materialized.workspace_dir.resolve())
    generated = render_openclaw_json(resolved)
    assert generated.models["default"] == "openrouter/openai/gpt-example"
    assert generated.agents.defaults["model"]["primary"] == "openrouter/openai/gpt-example"


def test_repo_legacy_minimax_suite_models_map_to_openrouter_refs() -> None:
    suite = load_suite_config(
        BUNDLED_WORKSPACE_ROOT / "configs" / "suites" / "legacy_h1_h4_x7_h8_minimax.yaml"
    )
    m27 = next(m for m in suite.models if m.model_id == "minimax_m27")
    raw_m27 = m27.model_dump(mode="json").get("requested_model") or ""
    assert openrouter_primary_model_ref(raw_m27) == "openrouter/minimax/minimax-m2.7"
    glm = next(m for m in suite.models if m.model_id == "glm5_turbo")
    raw_glm = glm.model_dump(mode="json").get("requested_model") or ""
    assert openrouter_primary_model_ref(raw_glm) == "openrouter/z-ai/glm-5-turbo"


def test_repo_suite_ids_are_unique() -> None:
    suites = discover_suites(BUNDLED_WORKSPACE_ROOT)
    assert "openclaw_smoke_suite" in suites
