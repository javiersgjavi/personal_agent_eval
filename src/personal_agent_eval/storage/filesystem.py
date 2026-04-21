"""Filesystem-backed storage for suite-scoped runs and evaluations."""

from __future__ import annotations

import json
import re
import shutil
from hashlib import sha256
from pathlib import Path
from typing import TypeVar
from urllib.parse import unquote, urlparse

from personal_agent_eval.aggregation.models import FinalEvaluationResult
from personal_agent_eval.artifacts import (
    OutputArtifactRef,
    parse_openclaw_run_evidence,
    with_openclaw_run_evidence,
)
from personal_agent_eval.artifacts.run_artifact import ArtifactModel, RunArtifact
from personal_agent_eval.fingerprints import EvaluationFingerprintInput, RunFingerprintInput
from personal_agent_eval.judge.models import AggregatedJudgeResult
from personal_agent_eval.reporting.final_result_summary import render_final_result_markdown
from personal_agent_eval.storage.models import (
    EvaluationCaseStorageManifest,
    EvaluationIterationRecord,
    EvaluationStorageManifest,
    RunCaseStorageManifest,
    RunIterationRecord,
    RunStorageManifest,
)

ArtifactModelT = TypeVar("ArtifactModelT", bound=ArtifactModel)
SHORT_FINGERPRINT_LENGTH = 6


class FilesystemStorage:
    """Deterministic filesystem storage for suite-scoped run and evaluation campaigns."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def runs_root(self) -> Path:
        return self.root / "outputs" / "runs"

    @property
    def evaluations_root(self) -> Path:
        return self.root / "outputs" / "evaluations"

    def run_campaign_path(self, suite_id: str, run_profile_fingerprint: str) -> Path:
        return (
            self.runs_root
            / self._suite_path_label(suite_id)
            / self._run_profile_path_label(run_profile_fingerprint)
        )

    def evaluation_campaign_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
    ) -> Path:
        return (
            self.evaluations_root
            / self._suite_path_label(suite_id)
            / self._evaluation_profile_fingerprint_path_label(run_profile_fingerprint)
            / self._evaluation_campaign_label(
                evaluation_profile_id,
                evaluation_fingerprint,
            )
        )

    def run_manifest_path(self, suite_id: str, run_profile_fingerprint: str) -> Path:
        return self.run_campaign_path(suite_id, run_profile_fingerprint) / "manifest.json"

    def evaluation_manifest_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
    ) -> Path:
        return (
            self.evaluation_campaign_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
            )
            / "manifest.json"
        )

    def evaluation_fingerprint_input_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
    ) -> Path:
        return (
            self.evaluation_campaign_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
            )
            / "fingerprint_input.json"
        )

    def run_case_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
    ) -> Path:
        return (
            self.run_campaign_path(suite_id, run_profile_fingerprint)
            / self._path_label(model_id)
            / case_id
        )

    def evaluation_case_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
    ) -> Path:
        return (
            self.evaluation_campaign_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
            )
            / self._path_label(model_id)
            / case_id
        )

    def run_case_manifest_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
    ) -> Path:
        return (
            self.run_case_path(suite_id, run_profile_fingerprint, model_id, case_id)
            / "manifest.json"
        )

    def evaluation_case_manifest_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
    ) -> Path:
        return (
            self.evaluation_case_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            )
            / "manifest.json"
        )

    def case_run_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.run_case_path(suite_id, run_profile_fingerprint, model_id, case_id)
            / f"run_{repetition_index + 1}.json"
        )

    def case_run_fingerprint_input_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.run_case_path(suite_id, run_profile_fingerprint, model_id, case_id)
            / f"run_{repetition_index + 1}.fingerprint_input.json"
        )

    def case_run_artifacts_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.run_case_path(suite_id, run_profile_fingerprint, model_id, case_id)
            / f"run_{repetition_index + 1}.artifacts"
        )

    def run_case_storage_relative_paths(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> dict[str, str]:
        """Paths under ``self.root`` for the canonical run bundle (POSIX, relative)."""
        root = self.root.resolve()
        run_json = self.case_run_path(
            suite_id,
            run_profile_fingerprint,
            model_id,
            case_id,
            repetition_index,
        ).resolve()
        fp_input = self.case_run_fingerprint_input_path(
            suite_id,
            run_profile_fingerprint,
            model_id,
            case_id,
            repetition_index,
        ).resolve()
        bundle = self.case_run_artifacts_path(
            suite_id,
            run_profile_fingerprint,
            model_id,
            case_id,
            repetition_index,
        ).resolve()
        return {
            "run_artifact": run_json.relative_to(root).as_posix(),
            "run_fingerprint_input": fp_input.relative_to(root).as_posix(),
            "run_artifacts_dir": bundle.relative_to(root).as_posix(),
        }

    def case_judge_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.evaluation_case_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            )
            / "raw_outputs"
            / f"judge_{repetition_index + 1}.json"
        )

    def case_judge_prompt_user_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.evaluation_case_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            )
            / "raw_outputs"
            / f"judge_{repetition_index + 1}.prompt.user.json"
        )

    def case_judge_prompt_debug_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.evaluation_case_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            )
            / f"judge_{repetition_index + 1}.prompt.debug.md"
        )

    def case_summary_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.evaluation_case_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            )
            / f"summary_{repetition_index + 1}.md"
        )

    def case_final_result_path(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> Path:
        return (
            self.evaluation_case_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            )
            / "raw_outputs"
            / f"final_result_{repetition_index + 1}.json"
        )

    def has_run_manifest(self, suite_id: str, run_profile_fingerprint: str) -> bool:
        path = self.run_manifest_path(suite_id, run_profile_fingerprint)
        return self._has_matching_fingerprint(
            path,
            "run_profile_fingerprint",
            run_profile_fingerprint,
        )

    def write_run_manifest(self, manifest: RunStorageManifest) -> Path:
        return self._write_model(
            self.run_manifest_path(manifest.suite_id, manifest.run_profile_fingerprint),
            manifest,
        )

    def read_run_manifest(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
    ) -> RunStorageManifest:
        return self._read_model(
            self.run_manifest_path(suite_id, run_profile_fingerprint),
            RunStorageManifest,
        )

    def write_case_run(
        self,
        *,
        suite_id: str,
        run_profile_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        repetition_index: int,
        run_fingerprint: str,
        artifact: RunArtifact,
        fingerprint_input: RunFingerprintInput,
    ) -> Path:
        if not isinstance(fingerprint_input, RunFingerprintInput):
            raise ValueError("write_case_run() requires RunFingerprintInput.")
        artifact = self._persist_run_artifact_assets(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            model_id=model_id,
            repetition_index=repetition_index,
            artifact=artifact,
        )
        path = self._write_model(
            self.case_run_path(
                suite_id,
                run_profile_fingerprint,
                model_id,
                artifact.identity.case_id,
                repetition_index,
            ),
            artifact,
        )
        self._write_model(
            self.case_run_fingerprint_input_path(
                suite_id,
                run_profile_fingerprint,
                model_id,
                artifact.identity.case_id,
                repetition_index,
            ),
            fingerprint_input,
        )
        manifest_path = self.run_case_manifest_path(
            suite_id,
            run_profile_fingerprint,
            model_id,
            artifact.identity.case_id,
        )
        manifest = self._read_optional_model(manifest_path, RunCaseStorageManifest)
        if manifest is None:
            manifest = RunCaseStorageManifest(
                suite_id=suite_id,
                run_profile_id=run_profile_id,
                run_profile_fingerprint=run_profile_fingerprint,
                model_id=model_id,
                case_id=artifact.identity.case_id,
            )
        oc_evidence = parse_openclaw_run_evidence(artifact.runner_metadata)
        manifest = manifest.model_copy(
            update={
                "iterations": self._replace_run_iteration(
                    manifest.iterations,
                    RunIterationRecord(
                        repetition_index=repetition_index,
                        run_fingerprint=run_fingerprint,
                    ),
                ),
                "runner_type": artifact.identity.runner_type,
                "openclaw_agent_id": oc_evidence.agent_id if oc_evidence is not None else None,
            }
        )
        self._write_model(manifest_path, manifest)
        return path

    def has_case_run(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
        run_fingerprint: str,
    ) -> bool:
        manifest = self._read_optional_model(
            self.run_case_manifest_path(suite_id, run_profile_fingerprint, model_id, case_id),
            RunCaseStorageManifest,
        )
        if manifest is None:
            return False
        for iteration in manifest.iterations:
            if (
                iteration.repetition_index == repetition_index
                and iteration.run_fingerprint == run_fingerprint
            ):
                return self.case_run_path(
                    suite_id,
                    run_profile_fingerprint,
                    model_id,
                    case_id,
                    repetition_index,
                ).is_file()
        return False

    def read_case_run(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> RunArtifact:
        return self._read_model(
            self.case_run_path(
                suite_id,
                run_profile_fingerprint,
                model_id,
                case_id,
                repetition_index,
            ),
            RunArtifact,
        )

    def has_evaluation_manifest(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
    ) -> bool:
        path = self.evaluation_manifest_path(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
        )
        return self._has_matching_fingerprint(
            path,
            "evaluation_fingerprint",
            evaluation_fingerprint,
        )

    def write_evaluation_manifest(self, manifest: EvaluationStorageManifest) -> Path:
        return self._write_model(
            self.evaluation_manifest_path(
                manifest.suite_id,
                manifest.run_profile_fingerprint,
                manifest.evaluation_profile_id,
                manifest.evaluation_fingerprint,
            ),
            manifest,
        )

    def read_evaluation_manifest(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
    ) -> EvaluationStorageManifest:
        return self._read_model(
            self.evaluation_manifest_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
            ),
            EvaluationStorageManifest,
        )

    def has_evaluation_fingerprint_input(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
    ) -> bool:
        path = self.evaluation_fingerprint_input_path(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
        )
        return self._has_matching_fingerprint(path, "fingerprint", evaluation_fingerprint)

    def write_evaluation_fingerprint_input(
        self,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        record: EvaluationFingerprintInput,
    ) -> Path:
        if not isinstance(record, EvaluationFingerprintInput):
            raise ValueError(
                "write_evaluation_fingerprint_input() requires EvaluationFingerprintInput."
            )
        return self._write_model(
            self.evaluation_fingerprint_input_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                record.fingerprint,
            ),
            record,
        )

    def write_case_judge_result(
        self,
        *,
        suite_id: str,
        run_profile_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
        run_fingerprint: str,
        result: AggregatedJudgeResult,
    ) -> Path:
        path = self._write_model(
            self.case_judge_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
                repetition_index,
            ),
            result,
            sort_keys=False,
        )
        self._upsert_evaluation_case_manifest(
            suite_id=suite_id,
            run_profile_id=run_profile_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model_id,
            case_id=case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        )
        self._persist_case_judge_prompt(
            suite_id=suite_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model_id,
            case_id=case_id,
            repetition_index=repetition_index,
            result=result,
        )
        return path

    def has_case_judge_result(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
        run_fingerprint: str,
    ) -> bool:
        manifest = self._read_optional_model(
            self.evaluation_case_manifest_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            ),
            EvaluationCaseStorageManifest,
        )
        if manifest is None:
            return False
        for iteration in manifest.iterations:
            if (
                iteration.repetition_index == repetition_index
                and iteration.run_fingerprint == run_fingerprint
                and iteration.evaluation_fingerprint == evaluation_fingerprint
            ):
                return self.case_judge_path(
                    suite_id,
                    run_profile_fingerprint,
                    manifest.evaluation_profile_id,
                    evaluation_fingerprint,
                    model_id,
                    case_id,
                    repetition_index,
                ).is_file()
        return False

    def read_case_judge_result(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> AggregatedJudgeResult:
        return self._read_model(
            self.case_judge_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
                repetition_index,
            ),
            AggregatedJudgeResult,
        )

    def write_case_final_result(
        self,
        *,
        suite_id: str,
        run_profile_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        repetition_index: int,
        run_fingerprint: str,
        result: FinalEvaluationResult,
    ) -> Path:
        path = self._write_model(
            self.case_final_result_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                result.case_id,
                repetition_index,
            ),
            result,
        )
        self._write_text(
            self.case_summary_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                result.case_id,
                repetition_index,
            ),
            render_final_result_markdown(result),
        )
        self._upsert_evaluation_case_manifest(
            suite_id=suite_id,
            run_profile_id=run_profile_id,
            run_profile_fingerprint=run_profile_fingerprint,
            evaluation_profile_id=evaluation_profile_id,
            evaluation_fingerprint=evaluation_fingerprint,
            model_id=model_id,
            case_id=result.case_id,
            repetition_index=repetition_index,
            run_fingerprint=run_fingerprint,
        )
        return path

    def write_case_summary_text(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
        content: str,
    ) -> Path:
        return self._write_text(
            self.case_summary_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
                repetition_index,
            ),
            content,
        )

    def has_case_final_result(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
        run_fingerprint: str,
    ) -> bool:
        manifest = self._read_optional_model(
            self.evaluation_case_manifest_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
            ),
            EvaluationCaseStorageManifest,
        )
        if manifest is None:
            return False
        for iteration in manifest.iterations:
            if (
                iteration.repetition_index == repetition_index
                and iteration.run_fingerprint == run_fingerprint
                and iteration.evaluation_fingerprint == evaluation_fingerprint
            ):
                return self.case_final_result_path(
                    suite_id,
                    run_profile_fingerprint,
                    manifest.evaluation_profile_id,
                    evaluation_fingerprint,
                    model_id,
                    case_id,
                    repetition_index,
                ).is_file()
        return False

    def read_case_final_result(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
    ) -> FinalEvaluationResult:
        return self._read_model(
            self.case_final_result_path(
                suite_id,
                run_profile_fingerprint,
                evaluation_profile_id,
                evaluation_fingerprint,
                model_id,
                case_id,
                repetition_index,
            ),
            FinalEvaluationResult,
        )

    def _upsert_evaluation_case_manifest(
        self,
        *,
        suite_id: str,
        run_profile_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
        run_fingerprint: str,
    ) -> None:
        manifest_path = self.evaluation_case_manifest_path(
            suite_id,
            run_profile_fingerprint,
            evaluation_profile_id,
            evaluation_fingerprint,
            model_id,
            case_id,
        )
        manifest = self._read_optional_model(manifest_path, EvaluationCaseStorageManifest)
        if manifest is None:
            manifest = EvaluationCaseStorageManifest(
                suite_id=suite_id,
                run_profile_id=run_profile_id,
                run_profile_fingerprint=run_profile_fingerprint,
                evaluation_profile_id=evaluation_profile_id,
                evaluation_fingerprint=evaluation_fingerprint,
                model_id=model_id,
                case_id=case_id,
            )
        manifest = manifest.model_copy(
            update={
                "iterations": self._replace_evaluation_iteration(
                    manifest.iterations,
                    EvaluationIterationRecord(
                        repetition_index=repetition_index,
                        run_fingerprint=run_fingerprint,
                        evaluation_fingerprint=evaluation_fingerprint,
                    ),
                )
            }
        )
        self._write_model(manifest_path, manifest)

    def _replace_run_iteration(
        self,
        iterations: list[RunIterationRecord],
        replacement: RunIterationRecord,
    ) -> list[RunIterationRecord]:
        retained = [
            item for item in iterations if item.repetition_index != replacement.repetition_index
        ]
        retained.append(replacement)
        return sorted(retained, key=lambda item: item.repetition_index)

    def _replace_evaluation_iteration(
        self,
        iterations: list[EvaluationIterationRecord],
        replacement: EvaluationIterationRecord,
    ) -> list[EvaluationIterationRecord]:
        retained = [
            item for item in iterations if item.repetition_index != replacement.repetition_index
        ]
        retained.append(replacement)
        return sorted(retained, key=lambda item: item.repetition_index)

    def _persist_run_artifact_assets(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        model_id: str,
        repetition_index: int,
        artifact: RunArtifact,
    ) -> RunArtifact:
        artifacts_dir = self.case_run_artifacts_path(
            suite_id,
            run_profile_fingerprint,
            model_id,
            artifact.identity.case_id,
            repetition_index,
        )
        output_artifacts = [
            self._persist_output_artifact_ref(artifacts_dir=artifacts_dir, ref=ref)
            for ref in artifact.output_artifacts
        ]
        openclaw_evidence = parse_openclaw_run_evidence(artifact.runner_metadata)
        updated_artifact = artifact.model_copy(update={"output_artifacts": output_artifacts})
        if openclaw_evidence is None:
            return updated_artifact

        persisted_evidence = openclaw_evidence.model_copy(
            update={
                "generated_openclaw_config": self._persist_optional_output_artifact_ref(
                    artifacts_dir=artifacts_dir,
                    ref=openclaw_evidence.generated_openclaw_config,
                ),
                "raw_session_trace": self._persist_optional_output_artifact_ref(
                    artifacts_dir=artifacts_dir,
                    ref=openclaw_evidence.raw_session_trace,
                ),
                "openclaw_logs": self._persist_optional_output_artifact_ref(
                    artifacts_dir=artifacts_dir,
                    ref=openclaw_evidence.openclaw_logs,
                ),
                "workspace_snapshot": self._persist_optional_output_artifact_ref(
                    artifacts_dir=artifacts_dir,
                    ref=openclaw_evidence.workspace_snapshot,
                ),
                "workspace_diff": self._persist_optional_output_artifact_ref(
                    artifacts_dir=artifacts_dir,
                    ref=openclaw_evidence.workspace_diff,
                ),
                "key_output_artifacts": [
                    self._persist_output_artifact_ref(artifacts_dir=artifacts_dir, ref=ref)
                    for ref in openclaw_evidence.key_output_artifacts
                ],
            }
        )
        return with_openclaw_run_evidence(updated_artifact, persisted_evidence)

    def _persist_case_judge_prompt(
        self,
        *,
        suite_id: str,
        run_profile_fingerprint: str,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
        model_id: str,
        case_id: str,
        repetition_index: int,
        result: AggregatedJudgeResult,
    ) -> None:
        raw_result = next(
            (item for item in result.raw_results if item.request_messages),
            None,
        )
        if raw_result is None:
            return
        system_text: str | None = None
        user_text: str | None = None
        for message in raw_result.request_messages:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(content, str):
                continue
            if role == "system" and system_text is None:
                system_text = content
            elif role == "user" and user_text is None:
                user_text = content
        if system_text is not None or user_text is not None:
            debug_sections: list[str] = []
            if system_text is not None:
                debug_sections.extend(
                    [
                        "SYSTEM PROMPT:",
                        system_text,
                    ]
                )
            if user_text is not None:
                if debug_sections:
                    debug_sections.append("")
                debug_sections.extend(
                    [
                        "USER PROMPT:",
                        user_text,
                    ]
                )
            self._write_text(
                self.case_judge_prompt_debug_path(
                    suite_id,
                    run_profile_fingerprint,
                    evaluation_profile_id,
                    evaluation_fingerprint,
                    model_id,
                    case_id,
                    repetition_index,
                ),
                "\n".join(debug_sections).rstrip() + "\n",
            )
        if raw_result.prompt_payload is not None:
            self._write_text(
                self.case_judge_prompt_user_path(
                    suite_id,
                    run_profile_fingerprint,
                    evaluation_profile_id,
                    evaluation_fingerprint,
                    model_id,
                    case_id,
                    repetition_index,
                ),
                json.dumps(raw_result.prompt_payload, indent=2, sort_keys=True, ensure_ascii=False),
            )

    def _persist_optional_output_artifact_ref(
        self,
        *,
        artifacts_dir: Path,
        ref: OutputArtifactRef | None,
    ) -> OutputArtifactRef | None:
        if ref is None:
            return None
        return self._persist_output_artifact_ref(artifacts_dir=artifacts_dir, ref=ref)

    def _persist_output_artifact_ref(
        self,
        *,
        artifacts_dir: Path,
        ref: OutputArtifactRef,
    ) -> OutputArtifactRef:
        source_path = self._local_file_uri_to_path(ref.uri)
        if source_path is None or not source_path.is_file():
            return ref

        destination_name = f"{self._path_label(ref.artifact_id)}--{source_path.name}"
        destination_path = artifacts_dir / destination_name
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.resolve() != destination_path.resolve():
            shutil.copy2(source_path, destination_path)

        payload = destination_path.read_bytes()
        return ref.model_copy(
            update={
                "uri": destination_path.resolve().as_uri(),
                "byte_size": len(payload),
                "sha256": sha256(payload).hexdigest(),
            }
        )

    def _local_file_uri_to_path(self, uri: str) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return None
        if parsed.netloc not in {"", "localhost"}:
            return None
        return Path(unquote(parsed.path))

    def _short_fingerprint(self, fingerprint: str) -> str:
        normalized = fingerprint.strip().lower()
        if len(normalized) < SHORT_FINGERPRINT_LENGTH:
            minimum = SHORT_FINGERPRINT_LENGTH
            raise ValueError(f"Fingerprint '{fingerprint}' must be at least {minimum} characters.")
        return normalized[:SHORT_FINGERPRINT_LENGTH]

    def _path_label(self, raw_value: str) -> str:
        compact = raw_value.strip()
        if not compact:
            raise ValueError("Path label cannot be empty.")
        return re.sub(r"[^A-Za-z0-9._-]+", "_", compact)

    def _suite_path_label(self, suite_id: str) -> str:
        return f"suit_{self._path_label(suite_id)}"

    def _run_profile_path_label(self, run_profile_fingerprint: str) -> str:
        return f"run_profile_{self._short_fingerprint(run_profile_fingerprint)}"

    def _evaluation_profile_fingerprint_path_label(
        self,
        run_profile_fingerprint: str,
    ) -> str:
        return f"evaluation_profile_{self._short_fingerprint(run_profile_fingerprint)}"

    def _evaluation_campaign_label(
        self,
        evaluation_profile_id: str,
        evaluation_fingerprint: str,
    ) -> str:
        return (
            f"eval_profile_{self._path_label(evaluation_profile_id)}_"
            f"{self._short_fingerprint(evaluation_fingerprint)}"
        )

    def _has_matching_fingerprint(self, path: Path, field_name: str, expected_value: str) -> bool:
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed_value = payload.get(field_name)
        if observed_value != expected_value:
            raise ValueError(
                f"Storage path collision at '{path}': expected {field_name}='{expected_value}', "
                f"observed '{observed_value}'."
            )
        return True

    def _write_model(self, path: Path, model: ArtifactModel, *, sort_keys: bool = True) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                model.to_json_dict(),
                indent=2,
                sort_keys=sort_keys,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _write_text(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if content.endswith("\n"):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(content + "\n", encoding="utf-8")
        return path

    def _read_model(self, path: Path, model_type: type[ArtifactModelT]) -> ArtifactModelT:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(payload)

    def _read_optional_model(
        self,
        path: Path,
        model_type: type[ArtifactModelT],
    ) -> ArtifactModelT | None:
        if not path.is_file():
            return None
        return self._read_model(path, model_type)
