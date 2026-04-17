"""Filesystem-backed storage for runs and evaluations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from personal_agent_eval.aggregation.models import FinalEvaluationResult
from personal_agent_eval.artifacts.run_artifact import ArtifactModel, RunArtifact
from personal_agent_eval.fingerprints import EvaluationFingerprintInput, RunFingerprintInput
from personal_agent_eval.judge.models import AggregatedJudgeResult
from personal_agent_eval.storage.models import (
    EvaluationStorageManifest,
    RunStorageManifest,
)

ArtifactModelT = TypeVar("ArtifactModelT", bound=ArtifactModel)


class FilesystemStorage:
    """Deterministic filesystem storage for run and evaluation artifacts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def runs_root(self) -> Path:
        """Return the root directory for run spaces."""
        return self.root / "outputs" / "runs"

    @property
    def evaluations_root(self) -> Path:
        """Return the root directory for evaluation spaces."""
        return self.root / "outputs" / "evaluations"

    def run_space_path(self, run_fingerprint: str) -> Path:
        """Return the directory for one run fingerprint space."""
        return self.runs_root / run_fingerprint

    def evaluation_space_path(self, evaluation_fingerprint: str) -> Path:
        """Return the directory for one evaluation fingerprint space."""
        return self.evaluations_root / evaluation_fingerprint

    def run_manifest_path(self, run_fingerprint: str) -> Path:
        """Return the run-space manifest path."""
        return self.run_space_path(run_fingerprint) / "manifest.json"

    def run_fingerprint_input_path(self, run_fingerprint: str) -> Path:
        """Return the run-space fingerprint payload path."""
        return self.run_space_path(run_fingerprint) / "fingerprint_input.json"

    def case_run_path(self, run_fingerprint: str, case_id: str) -> Path:
        """Return the stored run artifact path for one case."""
        return self.run_space_path(run_fingerprint) / "cases" / case_id / "run.json"

    def evaluation_manifest_path(self, evaluation_fingerprint: str) -> Path:
        """Return the evaluation-space manifest path."""
        return self.evaluation_space_path(evaluation_fingerprint) / "manifest.json"

    def evaluation_fingerprint_input_path(self, evaluation_fingerprint: str) -> Path:
        """Return the evaluation-space fingerprint payload path."""
        return self.evaluation_space_path(evaluation_fingerprint) / "fingerprint_input.json"

    def evaluation_run_space_path(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
    ) -> Path:
        """Return the nested evaluation directory for one run fingerprint."""
        return self.evaluation_space_path(evaluation_fingerprint) / "runs" / run_fingerprint

    def case_judge_path_for_run(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        case_id: str,
    ) -> Path:
        """Return the stored judge artifact path for one case within one run space."""
        return (
            self.evaluation_run_space_path(evaluation_fingerprint, run_fingerprint)
            / "cases"
            / case_id
            / "judge.json"
        )

    def case_final_result_path_for_run(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        case_id: str,
    ) -> Path:
        """Return the stored final evaluation result path for one case within one run space."""
        return (
            self.evaluation_run_space_path(evaluation_fingerprint, run_fingerprint)
            / "cases"
            / case_id
            / "final_result.json"
        )

    def write_run_manifest(self, manifest: RunStorageManifest) -> Path:
        """Write one run-space manifest."""
        return self._write_model(
            self.run_manifest_path(manifest.run_fingerprint),
            manifest,
        )

    def read_run_manifest(self, run_fingerprint: str) -> RunStorageManifest:
        """Read one run-space manifest."""
        return self._read_model(
            self.run_manifest_path(run_fingerprint),
            RunStorageManifest,
        )

    def write_run_fingerprint_input(self, record: RunFingerprintInput) -> Path:
        """Write one run fingerprint payload record."""
        if not isinstance(record, RunFingerprintInput):
            raise ValueError("write_run_fingerprint_input() requires RunFingerprintInput.")
        return self._write_model(
            self.run_fingerprint_input_path(record.fingerprint),
            record,
        )

    def read_run_fingerprint_input(self, run_fingerprint: str) -> RunFingerprintInput:
        """Read one run fingerprint payload record."""
        return self._read_model(
            self.run_fingerprint_input_path(run_fingerprint),
            RunFingerprintInput,
        )

    def write_case_run(self, run_fingerprint: str, artifact: RunArtifact) -> Path:
        """Write one per-case run artifact."""
        return self._write_model(
            self.case_run_path(run_fingerprint, artifact.identity.case_id),
            artifact,
        )

    def read_case_run(self, run_fingerprint: str, case_id: str) -> RunArtifact:
        """Read one per-case run artifact."""
        return self._read_model(self.case_run_path(run_fingerprint, case_id), RunArtifact)

    def has_run_manifest(self, run_fingerprint: str) -> bool:
        """Return whether a run manifest exists."""
        return self.run_manifest_path(run_fingerprint).is_file()

    def has_run_fingerprint_input(self, run_fingerprint: str) -> bool:
        """Return whether a run fingerprint payload exists."""
        return self.run_fingerprint_input_path(run_fingerprint).is_file()

    def has_case_run(self, run_fingerprint: str, case_id: str) -> bool:
        """Return whether a per-case run artifact exists."""
        return self.case_run_path(run_fingerprint, case_id).is_file()

    def write_evaluation_manifest(self, manifest: EvaluationStorageManifest) -> Path:
        """Write one evaluation-space manifest."""
        return self._write_model(
            self.evaluation_manifest_path(manifest.evaluation_fingerprint),
            manifest,
        )

    def read_evaluation_manifest(self, evaluation_fingerprint: str) -> EvaluationStorageManifest:
        """Read one evaluation-space manifest."""
        return self._read_model(
            self.evaluation_manifest_path(evaluation_fingerprint),
            EvaluationStorageManifest,
        )

    def write_evaluation_fingerprint_input(self, record: EvaluationFingerprintInput) -> Path:
        """Write one evaluation fingerprint payload record."""
        if not isinstance(record, EvaluationFingerprintInput):
            raise ValueError(
                "write_evaluation_fingerprint_input() requires EvaluationFingerprintInput."
            )
        return self._write_model(
            self.evaluation_fingerprint_input_path(record.fingerprint),
            record,
        )

    def read_evaluation_fingerprint_input(
        self,
        evaluation_fingerprint: str,
    ) -> EvaluationFingerprintInput:
        """Read one evaluation fingerprint payload record."""
        return self._read_model(
            self.evaluation_fingerprint_input_path(evaluation_fingerprint),
            EvaluationFingerprintInput,
        )

    def write_case_judge_result(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        case_id: str,
        result: AggregatedJudgeResult,
    ) -> Path:
        """Write one per-case aggregated judge result."""
        return self._write_model(
            self.case_judge_path_for_run(evaluation_fingerprint, run_fingerprint, case_id),
            result,
        )

    def read_case_judge_result(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        case_id: str,
    ) -> AggregatedJudgeResult:
        """Read one per-case aggregated judge result."""
        return self._read_model(
            self.case_judge_path_for_run(evaluation_fingerprint, run_fingerprint, case_id),
            AggregatedJudgeResult,
        )

    def write_case_final_result(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        result: FinalEvaluationResult,
    ) -> Path:
        """Write one per-case final evaluation result."""
        return self._write_model(
            self.case_final_result_path_for_run(
                evaluation_fingerprint,
                run_fingerprint,
                result.case_id,
            ),
            result,
        )

    def read_case_final_result(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        case_id: str,
    ) -> FinalEvaluationResult:
        """Read one per-case final evaluation result."""
        return self._read_model(
            self.case_final_result_path_for_run(evaluation_fingerprint, run_fingerprint, case_id),
            FinalEvaluationResult,
        )

    def has_evaluation_manifest(self, evaluation_fingerprint: str) -> bool:
        """Return whether an evaluation manifest exists."""
        return self.evaluation_manifest_path(evaluation_fingerprint).is_file()

    def has_evaluation_fingerprint_input(self, evaluation_fingerprint: str) -> bool:
        """Return whether an evaluation fingerprint payload exists."""
        return self.evaluation_fingerprint_input_path(evaluation_fingerprint).is_file()

    def has_case_judge_result(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        case_id: str,
    ) -> bool:
        """Return whether a per-case judge result exists."""
        return self.case_judge_path_for_run(
            evaluation_fingerprint,
            run_fingerprint,
            case_id,
        ).is_file()

    def has_case_final_result(
        self,
        evaluation_fingerprint: str,
        run_fingerprint: str,
        case_id: str,
    ) -> bool:
        """Return whether a per-case final result exists."""
        return self.case_final_result_path_for_run(
            evaluation_fingerprint,
            run_fingerprint,
            case_id,
        ).is_file()

    def _write_model(self, path: Path, model: ArtifactModel) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(model.to_json_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def _read_model(self, path: Path, model_type: type[ArtifactModelT]) -> ArtifactModelT:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(payload)
