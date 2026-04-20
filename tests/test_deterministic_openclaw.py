from __future__ import annotations

from pathlib import Path

from personal_agent_eval.artifacts import (
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
    inject_openclaw_run_evidence,
)
from personal_agent_eval.artifacts.openclaw_run_evidence import (
    OpenClawEvidenceArtifactTypes,
    OpenClawRunEvidence,
)
from personal_agent_eval.artifacts.run_artifact import MessageTraceEvent, OutputArtifactRef
from personal_agent_eval.config import load_openclaw_agent, load_run_profile, load_test_config
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.config.test_config import (
    DeterministicCheck,
    FinalResponsePresentCheck,
    OpenClawWorkspaceFilePresentCheck,
)
from personal_agent_eval.deterministic import evaluate_deterministic_checks
from personal_agent_eval.domains.openclaw import run_openclaw_case
from test_deterministic_evaluation import build_artifact
from test_openclaw_runner import FakeOpenClawExecutor

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "config"


def test_openclaw_workspace_file_present_harness_artifact(tmp_path: Path) -> None:
    case_path = tmp_path / "c.yaml"
    case_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "case_id: oc_det",
                "title: t",
                "runner:",
                "  type: openclaw",
                "input:",
                "  messages:",
                "    - role: user",
                "      content: Make report.md",
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
        run_id="r1",
        suite_id="s",
        case_config=case_config,
        run_profile=run_profile,
        model_selection=ModelConfig.model_validate({"model_id": "baseline_model"}),
        agent_config=agent_config,
        executor=FakeOpenClawExecutor(),
        runtime_root=tmp_path / "run",
    )
    check = DeterministicCheck(
        check_id="oc-file",
        declarative=OpenClawWorkspaceFilePresentCheck(
            kind="openclaw_workspace_file_present",
            relative_path="report.md",
            contains="# Report",
        ),
    )
    result = evaluate_deterministic_checks([check], artifact)
    assert result.passed is True
    assert result.checks[0].passed is True


def test_openclaw_workspace_file_present_fails_on_llm_probe_artifact() -> None:
    artifact = build_artifact()
    check = DeterministicCheck(
        check_id="oc-file",
        declarative=OpenClawWorkspaceFilePresentCheck(
            kind="openclaw_workspace_file_present",
            relative_path="x.md",
        ),
    )
    result = evaluate_deterministic_checks([check], artifact)
    assert result.passed is False
    assert "openclaw" in (result.checks[0].message or "").lower()


def test_final_response_present_reads_key_output_when_no_final_output(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# Report\n\nhello\n", encoding="utf-8")
    metadata: dict = {}
    evidence = OpenClawRunEvidence(
        agent_id="support_agent",
        key_output_artifacts=[
            OutputArtifactRef(
                artifact_id="openclaw_key_output_1",
                artifact_type=OpenClawEvidenceArtifactTypes.KEY_OUTPUT,
                uri=report.resolve().as_uri(),
                media_type="text/plain",
            )
        ],
    )
    inject_openclaw_run_evidence(metadata, evidence)

    artifact = RunArtifact(
        identity=RunArtifactIdentity(
            schema_version=1,
            run_id="r2",
            case_id="c",
            suite_id="s",
            run_profile_id="p",
            runner_type="openclaw",
        ),
        status=RunStatus.SUCCESS,
        request=RunRequestMetadata(requested_model="openai/x"),
        trace=[
            MessageTraceEvent(sequence=0, event_type="message", role="user", content="hi"),
        ],
        output_artifacts=[
            OutputArtifactRef(
                artifact_id="openclaw_key_output_1",
                artifact_type=OpenClawEvidenceArtifactTypes.KEY_OUTPUT,
                uri=report.resolve().as_uri(),
                media_type="text/plain",
            )
        ],
        runner_metadata=metadata,
    )
    check = DeterministicCheck(
        check_id="fr",
        declarative=FinalResponsePresentCheck(kind="final_response_present"),
    )
    result = evaluate_deterministic_checks([check], artifact)
    assert result.passed is True
