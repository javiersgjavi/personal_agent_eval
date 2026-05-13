"""Deterministic evaluation engine for canonical run artifacts."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from pydantic import TypeAdapter

from personal_agent_eval.artifacts import RunArtifact, ToolCallTraceEvent
from personal_agent_eval.artifacts.run_artifact import FinalOutputTraceEvent
from personal_agent_eval.config.test_config import (
    DeterministicCheck,
    FileContainsCheck,
    FileExistsCheck,
    FinalResponsePresentCheck,
    OpenClawWorkspaceFilePresentCheck,
    OutputArtifactPresentCheck,
    PathExistsCheck,
    PythonHook,
    StatusIsCheck,
    TestConfig,
    ToolCallCountCheck,
)
from personal_agent_eval.deterministic.models import (
    DeterministicCheckOutcome,
    DeterministicCheckResult,
    DeterministicEvaluationResult,
    DeterministicEvaluationSummary,
    DeterministicHookContext,
    HookCheckResult,
)
from personal_agent_eval.deterministic.openclaw_checks import (
    effective_final_response_text,
    output_artifact_resolves_to_workspace_file,
    read_output_artifact_text,
)

_HOOK_RESULT_ADAPTER = TypeAdapter(HookCheckResult)
CheckSource = Literal["declarative", "python_hook"]


class DeterministicEvaluator:
    """Evaluate deterministic checks against a canonical run artifact."""

    def __init__(self, *, allow_local_python_hooks: bool = True) -> None:
        self._allow_local_python_hooks = allow_local_python_hooks

    def evaluate_test_config(
        self,
        test_config: TestConfig,
        artifact: RunArtifact,
    ) -> DeterministicEvaluationResult:
        """Evaluate the deterministic checks declared in a test config."""
        results = [
            self._evaluate_check(
                check=check,
                artifact=artifact,
                case_source_path=test_config.source_path,
            )
            for check in test_config.deterministic_checks
        ]
        return self._build_evaluation_result(
            case_id=artifact.identity.case_id,
            run_id=artifact.identity.run_id,
            checks=results,
        )

    def evaluate_checks(
        self,
        checks: list[DeterministicCheck],
        artifact: RunArtifact,
        *,
        case_source_path: Path | None = None,
    ) -> DeterministicEvaluationResult:
        """Evaluate an explicit list of deterministic checks."""
        results = [
            self._evaluate_check(
                check=check,
                artifact=artifact,
                case_source_path=case_source_path,
            )
            for check in checks
        ]
        return self._build_evaluation_result(
            case_id=artifact.identity.case_id,
            run_id=artifact.identity.run_id,
            checks=results,
        )

    def _build_evaluation_result(
        self,
        *,
        case_id: str,
        run_id: str,
        checks: list[DeterministicCheckResult],
    ) -> DeterministicEvaluationResult:
        passed_checks = sum(result.outcome is DeterministicCheckOutcome.PASSED for result in checks)
        failed_checks = sum(result.outcome is DeterministicCheckOutcome.FAILED for result in checks)
        error_checks = sum(result.outcome is DeterministicCheckOutcome.ERROR for result in checks)
        summary = DeterministicEvaluationSummary(
            total_checks=len(checks),
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            error_checks=error_checks,
        )
        return DeterministicEvaluationResult(
            case_id=case_id,
            run_id=run_id,
            passed=failed_checks == 0 and error_checks == 0,
            summary=summary,
            checks=checks,
        )

    def _evaluate_check(
        self,
        *,
        check: DeterministicCheck,
        artifact: RunArtifact,
        case_source_path: Path | None,
    ) -> DeterministicCheckResult:
        if check.declarative is not None:
            return self._evaluate_declarative_check(check=check, artifact=artifact)

        assert check.python_hook is not None
        return self._evaluate_python_hook(
            check=check,
            hook_reference=check.python_hook,
            artifact=artifact,
            case_source_path=case_source_path,
        )

    def _evaluate_declarative_check(
        self,
        *,
        check: DeterministicCheck,
        artifact: RunArtifact,
    ) -> DeterministicCheckResult:
        declarative = check.declarative
        assert declarative is not None

        try:
            if isinstance(declarative, FinalResponsePresentCheck):
                return self._check_final_response_present(check, declarative, artifact)
            if isinstance(declarative, ToolCallCountCheck):
                return self._check_tool_call_count(check, declarative, artifact)
            if isinstance(declarative, FileExistsCheck):
                return self._check_file_exists(check, declarative)
            if isinstance(declarative, FileContainsCheck):
                return self._check_file_contains(check, declarative)
            if isinstance(declarative, PathExistsCheck):
                return self._check_path_exists(check, declarative)
            if isinstance(declarative, StatusIsCheck):
                return self._check_status_is(check, declarative, artifact)
            if isinstance(declarative, OutputArtifactPresentCheck):
                return self._check_output_artifact_present(check, declarative, artifact)
            if isinstance(declarative, OpenClawWorkspaceFilePresentCheck):
                return self._check_openclaw_workspace_file_present(check, declarative, artifact)
        except Exception as exc:
            return self._error_result(
                check=check,
                kind=declarative.kind,
                source="declarative",
                message=f"Deterministic check raised {exc.__class__.__name__}: {exc}",
            )

        return self._error_result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            message=f"Unsupported declarative check kind '{declarative.kind}'.",
        )

    def _check_final_response_present(
        self,
        check: DeterministicCheck,
        declarative: FinalResponsePresentCheck,
        artifact: RunArtifact,
    ) -> DeterministicCheckResult:
        final_outputs = [
            event
            for event in artifact.trace
            if isinstance(event, FinalOutputTraceEvent) and event.content is not None
        ]
        normalized_output = effective_final_response_text(artifact)
        passed = bool(normalized_output)
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=None if passed else "Run artifact does not include a non-empty final response.",
            outputs={
                "final_output_count": len(final_outputs),
                "content_length": len(normalized_output),
                "runner_type": artifact.identity.runner_type,
            },
        )

    def _check_tool_call_count(
        self,
        check: DeterministicCheck,
        declarative: ToolCallCountCheck,
        artifact: RunArtifact,
    ) -> DeterministicCheckResult:
        actual_count = sum(isinstance(event, ToolCallTraceEvent) for event in artifact.trace)
        passed = actual_count == declarative.count
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=(
                None if passed else "Recorded tool call count did not match the expected value."
            ),
            outputs={
                "expected_count": declarative.count,
                "actual_count": actual_count,
            },
        )

    def _check_file_exists(
        self,
        check: DeterministicCheck,
        declarative: FileExistsCheck,
    ) -> DeterministicCheckResult:
        passed = declarative.path.is_file()
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=None if passed else f"Expected file was not found at '{declarative.path}'.",
            outputs={"path": str(declarative.path)},
        )

    def _check_file_contains(
        self,
        check: DeterministicCheck,
        declarative: FileContainsCheck,
    ) -> DeterministicCheckResult:
        if not declarative.path.is_file():
            return self._result(
                check=check,
                kind=declarative.kind,
                source="declarative",
                passed=False,
                message=f"Expected file was not found at '{declarative.path}'.",
                outputs={"path": str(declarative.path), "expected_text": declarative.text},
            )

        content = declarative.path.read_text(encoding="utf-8")
        passed = declarative.text in content
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=None if passed else "Expected text was not present in the target file.",
            outputs={
                "path": str(declarative.path),
                "expected_text": declarative.text,
            },
        )

    def _check_path_exists(
        self,
        check: DeterministicCheck,
        declarative: PathExistsCheck,
    ) -> DeterministicCheckResult:
        passed = declarative.path.exists()
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=None if passed else f"Expected path was not found at '{declarative.path}'.",
            outputs={"path": str(declarative.path)},
        )

    def _check_status_is(
        self,
        check: DeterministicCheck,
        declarative: StatusIsCheck,
        artifact: RunArtifact,
    ) -> DeterministicCheckResult:
        actual_status = artifact.status.value
        passed = actual_status == declarative.status
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=None if passed else "Run status did not match the expected terminal state.",
            outputs={
                "expected_status": declarative.status,
                "actual_status": actual_status,
            },
        )

    def _check_output_artifact_present(
        self,
        check: DeterministicCheck,
        declarative: OutputArtifactPresentCheck,
        artifact: RunArtifact,
    ) -> DeterministicCheckResult:
        matches = [
            output_artifact
            for output_artifact in artifact.output_artifacts
            if self._output_artifact_matches(output_artifact, declarative)
        ]
        passed = bool(matches)
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=None if passed else "No output artifact matched the configured filters.",
            outputs={
                "artifact_id": declarative.artifact_id,
                "artifact_type": declarative.artifact_type,
                "uri": declarative.uri,
                "matched_count": len(matches),
            },
        )

    def _check_openclaw_workspace_file_present(
        self,
        check: DeterministicCheck,
        declarative: OpenClawWorkspaceFilePresentCheck,
        artifact: RunArtifact,
    ) -> DeterministicCheckResult:
        if artifact.identity.runner_type != "openclaw":
            return self._result(
                check=check,
                kind=declarative.kind,
                source="declarative",
                passed=False,
                message="openclaw_workspace_file_present applies only to runner.type='openclaw'.",
                outputs={"relative_path": declarative.relative_path},
            )
        matches = [
            ref
            for ref in artifact.output_artifacts
            if output_artifact_resolves_to_workspace_file(ref, declarative.relative_path)
        ]
        if not matches:
            return self._result(
                check=check,
                kind=declarative.kind,
                source="declarative",
                passed=False,
                message="No output artifact matched the configured workspace relative path.",
                outputs={"relative_path": declarative.relative_path, "matched_count": 0},
            )
        if declarative.contains is None:
            if declarative.contains_all or declarative.contains_any:
                texts = [read_output_artifact_text(ref, max_bytes=512_000) or "" for ref in matches]
                passed = any(_matches_normalized_content(declarative, text) for text in texts)
                return self._result(
                    check=check,
                    kind=declarative.kind,
                    source="declarative",
                    passed=passed,
                    message=None
                    if passed
                    else "Matched workspace file did not satisfy normalized content matchers.",
                    outputs={
                        "relative_path": declarative.relative_path,
                        "matched_count": len(matches),
                        "contains_all": declarative.contains_all,
                        "contains_any": declarative.contains_any,
                    },
                )
            return self._result(
                check=check,
                kind=declarative.kind,
                source="declarative",
                passed=True,
                message=None,
                outputs={"relative_path": declarative.relative_path, "matched_count": len(matches)},
            )
        texts = [read_output_artifact_text(ref, max_bytes=512_000) or "" for ref in matches]
        passed = any(declarative.contains in text for text in texts)
        return self._result(
            check=check,
            kind=declarative.kind,
            source="declarative",
            passed=passed,
            message=None
            if passed
            else "Matched workspace file did not contain the expected substring.",
            outputs={
                "relative_path": declarative.relative_path,
                "matched_count": len(matches),
                "contains": declarative.contains,
            },
        )

    def _output_artifact_matches(
        self,
        output_artifact: Any,
        declarative: OutputArtifactPresentCheck,
    ) -> bool:
        if (
            declarative.artifact_id is not None
            and output_artifact.artifact_id != declarative.artifact_id
        ):
            return False
        if (
            declarative.artifact_type is not None
            and output_artifact.artifact_type != declarative.artifact_type
        ):
            return False
        return declarative.uri is None or output_artifact.uri == declarative.uri

    def _evaluate_python_hook(
        self,
        *,
        check: DeterministicCheck,
        hook_reference: PythonHook,
        artifact: RunArtifact,
        case_source_path: Path | None,
    ) -> DeterministicCheckResult:
        try:
            hook_callable = self._load_hook_callable(hook_reference)
            hook_context = DeterministicHookContext(
                check_id=check.check_id,
                description=check.description,
                case_source_path=(None if case_source_path is None else str(case_source_path)),
            )
            raw_result = self._invoke_hook(hook_callable, artifact, hook_context)
            normalized = self._normalize_hook_result(raw_result)
        except Exception as exc:
            return self._error_result(
                check=check,
                kind="python_hook",
                source="python_hook",
                message=f"Python hook raised {exc.__class__.__name__}: {exc}",
            )

        return DeterministicCheckResult(
            check_id=check.check_id,
            kind="python_hook",
            source="python_hook",
            outcome=(
                DeterministicCheckOutcome.PASSED
                if normalized.passed
                else DeterministicCheckOutcome.FAILED
            ),
            passed=normalized.passed,
            description=check.description,
            message=normalized.message,
            metadata=normalized.metadata,
            outputs=normalized.outputs,
        )

    def _load_hook_callable(self, hook_reference: PythonHook) -> Any:
        if hook_reference.import_path is not None:
            module = importlib.import_module(hook_reference.import_path)
        else:
            assert hook_reference.path is not None
            if not self._allow_local_python_hooks:
                raise PermissionError("Local Python hooks are disabled by evaluator policy.")
            module = self._load_module_from_path(hook_reference.path)

        try:
            hook_callable = getattr(module, hook_reference.callable_name)
        except AttributeError as exc:
            raise AttributeError(
                f"Hook callable '{hook_reference.callable_name}' was not found."
            ) from exc

        if not callable(hook_callable):
            raise TypeError(f"Hook reference '{hook_reference.callable_name}' is not callable.")
        return hook_callable

    def _load_module_from_path(self, path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(
            f"personal_agent_eval_deterministic_hook_{abs(hash(path))}",
            path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load hook module from '{path}'.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _invoke_hook(
        self,
        hook_callable: Any,
        artifact: RunArtifact,
        hook_context: DeterministicHookContext,
    ) -> object:
        signature = inspect.signature(hook_callable)
        positional_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(positional_params) == 0:
            return hook_callable()
        if len(positional_params) == 1:
            return hook_callable(artifact)
        return hook_callable(artifact, hook_context)

    def _normalize_hook_result(self, raw_result: object) -> HookCheckResult:
        if isinstance(raw_result, bool):
            return HookCheckResult(passed=raw_result)
        if isinstance(raw_result, HookCheckResult):
            return raw_result
        if isinstance(raw_result, DeterministicCheckResult):
            return HookCheckResult(
                passed=raw_result.passed,
                message=raw_result.message,
                metadata=raw_result.metadata,
                outputs=raw_result.outputs,
            )
        if isinstance(raw_result, dict):
            return _HOOK_RESULT_ADAPTER.validate_python(raw_result)
        raise TypeError(
            "Python deterministic hooks must return a bool, HookCheckResult, "
            "DeterministicCheckResult, or a compatible mapping."
        )

    def _result(
        self,
        *,
        check: DeterministicCheck,
        kind: str,
        source: CheckSource,
        passed: bool,
        message: str | None,
        outputs: dict[str, Any],
    ) -> DeterministicCheckResult:
        return DeterministicCheckResult(
            check_id=check.check_id,
            kind=kind,
            source=source,
            outcome=(
                DeterministicCheckOutcome.PASSED if passed else DeterministicCheckOutcome.FAILED
            ),
            passed=passed,
            description=check.description,
            message=message,
            outputs=outputs,
        )

    def _error_result(
        self,
        *,
        check: DeterministicCheck,
        kind: str,
        source: CheckSource,
        message: str,
    ) -> DeterministicCheckResult:
        return DeterministicCheckResult(
            check_id=check.check_id,
            kind=kind,
            source=source,
            outcome=DeterministicCheckOutcome.ERROR,
            passed=False,
            description=check.description,
            message=message,
        )


def _matches_normalized_content(
    declarative: OpenClawWorkspaceFilePresentCheck,
    text: str,
) -> bool:
    normalized_text = _normalize_match_text(text)
    required_terms = [_normalize_match_text(term) for term in declarative.contains_all]
    optional_terms = [_normalize_match_text(term) for term in declarative.contains_any]
    return all(term in normalized_text for term in required_terms) and (
        not optional_terms or any(term in normalized_text for term in optional_terms)
    )


def _normalize_match_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def evaluate_test_config_deterministic_checks(
    test_config: TestConfig,
    artifact: RunArtifact,
    *,
    allow_local_python_hooks: bool = True,
) -> DeterministicEvaluationResult:
    """Convenience wrapper around :class:`DeterministicEvaluator`."""
    evaluator = DeterministicEvaluator(
        allow_local_python_hooks=allow_local_python_hooks,
    )
    return evaluator.evaluate_test_config(test_config, artifact)


def evaluate_deterministic_checks(
    checks: list[DeterministicCheck],
    artifact: RunArtifact,
    *,
    allow_local_python_hooks: bool = True,
    case_source_path: Path | None = None,
) -> DeterministicEvaluationResult:
    """Evaluate an explicit list of deterministic checks."""
    evaluator = DeterministicEvaluator(
        allow_local_python_hooks=allow_local_python_hooks,
    )
    return evaluator.evaluate_checks(
        checks,
        artifact,
        case_source_path=case_source_path,
    )
