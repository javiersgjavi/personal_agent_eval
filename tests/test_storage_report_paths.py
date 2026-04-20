from __future__ import annotations

from pathlib import Path

from personal_agent_eval.artifacts import (
    OpenClawEvidenceArtifactTypes,
    OpenClawRunEvidence,
    OutputArtifactRef,
    RunArtifact,
    RunArtifactIdentity,
    RunRequestMetadata,
    RunStatus,
    with_openclaw_run_evidence,
)
from personal_agent_eval.fingerprints import RunFingerprintInput, RunFingerprintPayload
from personal_agent_eval.storage import FilesystemStorage, RunStorageManifest
from personal_agent_eval.storage.models import RunCaseStorageManifest
from personal_agent_eval.storage.report_paths import (
    build_openclaw_workflow_evidence_summary,
    file_uri_relative_to_storage_root,
)


def test_run_case_storage_relative_paths(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    rel = storage.run_case_storage_relative_paths(
        suite_id="my_suite",
        run_profile_fingerprint="f" * 64,
        model_id="vendor/model",
        case_id="case_a",
        repetition_index=0,
    )
    root = tmp_path.resolve()
    assert rel["run_artifact"] == storage.case_run_path(
        "my_suite", "f" * 64, "vendor/model", "case_a", 0
    ).resolve().relative_to(root).as_posix()
    assert rel["run_artifacts_dir"].endswith("run_1.artifacts")
    assert rel["run_fingerprint_input"].endswith("run_1.fingerprint_input.json")


def test_file_uri_relative_to_storage_root(tmp_path: Path) -> None:
    f = tmp_path / "deep" / "a.txt"
    f.parent.mkdir(parents=True)
    f.write_text("x", encoding="utf-8")
    rel = file_uri_relative_to_storage_root(uri=f.resolve().as_uri(), storage_root=tmp_path)
    assert rel == "deep/a.txt"


def test_build_openclaw_workflow_evidence_summary_maps_types(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    evidence = OpenClawRunEvidence(
        agent_id="support_agent",
        container_image="ghcr.io/x:y",
        generated_openclaw_config=OutputArtifactRef(
            artifact_id="c1",
            artifact_type=OpenClawEvidenceArtifactTypes.GENERATED_OPENCLAW_CONFIG,
            uri=cfg.resolve().as_uri(),
        ),
    )
    artifact = with_openclaw_run_evidence(
        RunArtifact(
            identity=RunArtifactIdentity(
                schema_version=1,
                run_id="r1",
                case_id="c",
                suite_id="s",
                run_profile_id="rp",
                runner_type="openclaw",
            ),
            status=RunStatus.SUCCESS,
            request=RunRequestMetadata(requested_model="m"),
        ),
        evidence,
    )
    summary = build_openclaw_workflow_evidence_summary(tmp_path, artifact)
    assert summary is not None
    assert summary.agent_id == "support_agent"
    assert summary.container_image == "ghcr.io/x:y"
    assert OpenClawEvidenceArtifactTypes.GENERATED_OPENCLAW_CONFIG in summary.evidence_paths
    assert summary.evidence_paths[
        OpenClawEvidenceArtifactTypes.GENERATED_OPENCLAW_CONFIG
    ].endswith("cfg.json")


def test_write_case_run_manifest_records_openclaw_fields(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    suite_id = "example_suite"
    run_profile_fp = "d" * 64
    run_fp = "a" * 64
    evidence = OpenClawRunEvidence(agent_id="support_agent")
    run_artifact = with_openclaw_run_evidence(
        RunArtifact(
            identity=RunArtifactIdentity(
                schema_version=1,
                run_id="run_oc",
                case_id="example_case",
                suite_id=suite_id,
                run_profile_id="default",
                runner_type="openclaw",
            ),
            status=RunStatus.SUCCESS,
            request=RunRequestMetadata(requested_model="openai/gpt"),
        ),
        evidence,
    )
    storage.write_run_manifest(
        RunStorageManifest(
            suite_id=suite_id,
            run_profile_id="default",
            run_profile_fingerprint=run_profile_fp,
            runner_type="openclaw",
            run_repetitions=1,
        )
    )
    storage.write_case_run(
        suite_id=suite_id,
        run_profile_id="default",
        run_profile_fingerprint=run_profile_fp,
        model_id="baseline_model",
        repetition_index=0,
        run_fingerprint=run_fp,
        artifact=run_artifact,
        fingerprint_input=RunFingerprintInput(
            fingerprint=run_fp,
            payload=RunFingerprintPayload(
                runner_type="openclaw",
                requested_model="openai/gpt",
            ),
        ),
    )
    manifest_path = storage.run_case_manifest_path(
        suite_id, run_profile_fp, "baseline_model", "example_case"
    )
    loaded = RunCaseStorageManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert loaded.runner_type == "openclaw"
    assert loaded.openclaw_agent_id == "support_agent"
