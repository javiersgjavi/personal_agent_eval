from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers.docker_subprocess_stub import patch_openclaw_docker_run
from personal_agent_eval.config import load_openclaw_agent, load_run_profile, load_test_config
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.domains.openclaw import run_openclaw_case
from personal_agent_eval.judge.orchestrator import build_judge_messages
from personal_agent_eval.judge.subject_redaction import redact_run_artifact_for_judge

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_redact_includes_openclaw_judge_context_with_excerpts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_openclaw_docker_run(monkeypatch)
    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: oc_judge_ctx",
                "title: ctx",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: user",
                "      content: Write report.md",
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    case_config = load_test_config(case_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_ctx",
        suite_id="suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate({"model_id": "baseline_model"}),
        agent_config=agent_config,
        runtime_root=tmp_path / "rt",
    )

    redacted = redact_run_artifact_for_judge(artifact)
    meta = redacted.get("runner_metadata")
    assert isinstance(meta, dict)
    ctx = meta.get("openclaw_judge_context")
    assert isinstance(ctx, dict)
    assert ctx.get("agent_id") == "support_agent"
    diff = ctx.get("workspace_diff_excerpt")
    assert isinstance(diff, str) and "report.md" in diff
    keys = ctx.get("key_output_excerpts")
    assert isinstance(keys, list) and keys
    assert any(item.get("basename") == "report.md" for item in keys if isinstance(item, dict))


def test_build_judge_messages_embeds_openclaw_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_openclaw_docker_run(monkeypatch)
    case_path = tmp_path / "case2.yaml"
    case_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: oc_judge_msg",
                "title: msg",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: user",
                "      content: Write report.md",
                "  context:",
                "    openclaw:",
                "      expected_artifact: report.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    case_config = load_test_config(case_path)
    run_profile = load_run_profile(FIXTURES_ROOT / "configs" / "run_profiles" / "openclaw.yaml")
    agent_config = load_openclaw_agent(FIXTURES_ROOT / "configs" / "agents" / "support_agent")
    artifact = run_openclaw_case(
        run_id="run_msg",
        suite_id="suite",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate({"model_id": "baseline_model"}),
        agent_config=agent_config,
        runtime_root=tmp_path / "rt2",
    )
    messages = build_judge_messages(
        judge_name="j1",
        judge_model="m1",
        test_config=case_config,
        run_artifact=artifact,
        system_prompt="Return JSON only.",
        deterministic_summary={"passed": True},
    )
    payload = json.loads(messages[1]["content"])
    run_part = payload["run_artifact"]
    assert "openclaw_judge_context" in run_part.get("runner_metadata", {})
