"""OpenClaw harness execution and evidence capture."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol

from personal_agent_eval.artifacts import (
    LlmExecutionParameters,
    OpenClawEvidenceArtifactTypes,
    OpenClawRunEvidence,
    OutputArtifactRef,
    ProviderMetadata,
    RunArtifact,
    RunArtifactIdentity,
    RunError,
    RunRequestMetadata,
    RunStatus,
    RunTiming,
    with_openclaw_run_evidence,
)
from personal_agent_eval.artifacts.run_artifact import (
    FinalOutputTraceEvent,
    MessageTraceEvent,
    RunnerTraceEvent,
    TraceEvent,
    UsageMetadata,
)
from personal_agent_eval.config import OpenClawAgentConfig, RunProfileConfig, TestConfig
from personal_agent_eval.config.suite_config import ModelConfig
from personal_agent_eval.domains.openclaw.resolution import (
    ResolvedOpenClawConfig,
    render_openclaw_json_text,
    resolve_openclaw_config,
)
from personal_agent_eval.domains.openclaw.workspace import materialize_openclaw_workspace

MessageRole = Literal["system", "user", "assistant", "tool"]


class OpenClawExecutor(Protocol):
    """Minimal command surface needed by the benchmark harness."""

    def validate_config(
        self,
        *,
        config_path: Path,
        env: Mapping[str, str],
    ) -> OpenClawCommandResult:
        """Validate one generated OpenClaw config."""

    def run_agent(
        self,
        *,
        agent_id: str,
        message: str,
        config_path: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> OpenClawCommandResult:
        """Run one local OpenClaw agent turn."""


@dataclass(frozen=True, slots=True)
class OpenClawCommandResult:
    """Captured result of one OpenClaw CLI invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class SubprocessOpenClawExecutor:
    """Best-effort subprocess-backed OpenClaw executor."""

    def validate_config(
        self,
        *,
        config_path: Path,
        env: Mapping[str, str],
    ) -> OpenClawCommandResult:
        del config_path
        return _run_subprocess(
            ["openclaw", "config", "validate", "--json"],
            env=env,
            timeout_seconds=30,
        )

    def run_agent(
        self,
        *,
        agent_id: str,
        message: str,
        config_path: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> OpenClawCommandResult:
        del config_path
        return _run_subprocess(
            [
                "openclaw",
                "agent",
                "--local",
                "--json",
                "--agent",
                agent_id,
                "--message",
                message,
                "--timeout",
                str(timeout_seconds),
            ],
            env=env,
            timeout_seconds=timeout_seconds,
        )


def run_openclaw_case(
    *,
    run_id: str,
    suite_id: str,
    case_config: TestConfig,
    run_profile: RunProfileConfig,
    model_selection: ModelConfig,
    agent_config: OpenClawAgentConfig,
    executor: OpenClawExecutor | None = None,
    runtime_root: Path | None = None,
    queued_at: datetime | None = None,
) -> RunArtifact:
    """Run one OpenClaw case and capture external evidence refs."""
    if case_config.runner.type != "openclaw":
        raise ValueError("run_openclaw_case() requires runner.type='openclaw'.")
    if run_profile.openclaw is None:
        raise ValueError("OpenClaw execution requires run_profile.openclaw.")
    if agent_config.workspace_dir is None:
        raise ValueError("OpenClaw execution requires agent_config.workspace_dir.")

    executor = executor or SubprocessOpenClawExecutor()
    queued_timestamp = queued_at or datetime.now(UTC)
    started_at = datetime.now(UTC)
    started_monotonic = perf_counter()

    harness_root = _prepare_runtime_root(runtime_root)
    workspace_dir = harness_root / "workspace"
    state_dir = harness_root / "state"
    generated_config_path = harness_root / "openclaw.json"
    raw_trace_path = harness_root / "raw_session_trace.json"
    command_log_path = harness_root / "openclaw.log"
    workspace_snapshot_path = harness_root / "workspace_snapshot.tar.gz"
    workspace_diff_path = harness_root / "workspace.diff"

    trace_builder = _TraceBuilder()
    resolved_config = resolve_openclaw_config(
        case_config=case_config,
        run_profile=run_profile,
        model_selection=model_selection,
        agent_config=agent_config,
        workspace_dir=workspace_dir,
        state_dir=state_dir,
    )
    request = _build_request_model(
        case_config=case_config,
        model_selection=model_selection,
        run_profile=run_profile,
        agent_config=agent_config,
        resolved_config=resolved_config,
    )
    provider = ProviderMetadata(gateway="openclaw")
    identity = RunArtifactIdentity(
        schema_version=1,
        run_id=run_id,
        case_id=case_config.case_id,
        suite_id=suite_id,
        run_profile_id=run_profile.run_profile_id,
        runner_type="openclaw",
    )

    materialized_workspace = materialize_openclaw_workspace(
        template_dir=agent_config.workspace_dir,
        workspace_dir=workspace_dir,
    )
    trace_builder.add_runner_event(
        name="workspace_materialized",
        detail="Materialized OpenClaw workspace template.",
        metadata={
            "workspace_dir": str(workspace_dir),
            "placeholder_files": materialized_workspace.manifest.placeholder_files,
        },
    )

    for message in resolved_config.case_messages:
        trace_builder.add_message(
            role=message.role,
            content=message.content,
            name=message.name,
            metadata=message.metadata,
        )

    generated_config_path.write_text(render_openclaw_json_text(resolved_config), encoding="utf-8")
    env = _build_openclaw_environment(config_path=generated_config_path, state_dir=state_dir)
    validation_result = executor.validate_config(config_path=generated_config_path, env=env)
    _append_command_log(
        command_log_path,
        command_name="validate",
        result=validation_result,
    )
    trace_builder.add_runner_event(
        name="config_validated",
        detail="Validated generated OpenClaw config.",
        metadata={"returncode": validation_result.returncode},
    )

    if validation_result.returncode != 0:
        _write_text_payload(raw_trace_path, validation_result.stdout or validation_result.stderr)
        _write_workspace_artifacts(
            template_dir=agent_config.workspace_dir,
            workspace_dir=workspace_dir,
            snapshot_path=workspace_snapshot_path,
            diff_path=workspace_diff_path,
        )
        artifact = _build_terminal_artifact(
            identity=identity,
            status=RunStatus.INVALID,
            timing=_build_timing(
                queued_at=queued_timestamp,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
            request_model=request,
            trace=trace_builder.events,
            provider=provider,
            error=RunError(
                code="openclaw_config_invalid",
                message="Generated OpenClaw config failed validation.",
                error_type="OpenClawConfigValidationError",
                retryable=False,
                metadata={"stderr": validation_result.stderr, "stdout": validation_result.stdout},
            ),
        )
        return _attach_openclaw_evidence(
            artifact=artifact,
            agent_id=agent_config.agent_id,
            container_image=run_profile.openclaw.image,
            generated_config_path=generated_config_path,
            raw_trace_path=raw_trace_path,
            log_path=command_log_path,
            workspace_snapshot_path=workspace_snapshot_path,
            workspace_diff_path=workspace_diff_path,
            key_output_paths=[],
        )

    task_message = _render_task_message(resolved_config)
    trace_builder.add_runner_event(
        name="agent_invoked",
        detail="Running OpenClaw local agent turn.",
        metadata={"agent_id": resolved_config.agent_id},
    )
    run_result = executor.run_agent(
        agent_id=resolved_config.agent_id,
        message=task_message,
        config_path=generated_config_path,
        env=env,
        timeout_seconds=run_profile.openclaw.timeout_seconds,
    )
    _append_command_log(command_log_path, command_name="run_agent", result=run_result)
    _write_text_payload(raw_trace_path, run_result.stdout or run_result.stderr)

    final_output = _extract_final_output(run_result.stdout)
    if final_output is not None:
        trace_builder.add_final_output(final_output)

    _write_workspace_artifacts(
        template_dir=agent_config.workspace_dir,
        workspace_dir=workspace_dir,
        snapshot_path=workspace_snapshot_path,
        diff_path=workspace_diff_path,
    )
    key_output_paths = _resolve_key_output_paths(
        workspace_dir=workspace_dir,
        openclaw_hints=resolved_config.case_openclaw_hints,
    )

    if run_result.timed_out:
        status = RunStatus.TIMED_OUT
        error = RunError(
            code="openclaw_timeout",
            message="OpenClaw agent execution exceeded the configured timeout.",
            error_type="TimeoutExpired",
            retryable=False,
        )
    elif run_result.returncode != 0:
        status = RunStatus.FAILED
        error = RunError(
            code="openclaw_execution_failed",
            message="OpenClaw agent execution returned a non-zero exit code.",
            error_type="OpenClawExecutionError",
            retryable=False,
            metadata={"returncode": run_result.returncode, "stderr": run_result.stderr},
        )
    else:
        status = RunStatus.SUCCESS
        error = None

    artifact = RunArtifact(
        identity=identity,
        status=status,
        timing=_build_timing(
            queued_at=queued_timestamp,
            started_at=started_at,
            started_monotonic=started_monotonic,
        ),
        request=request,
        provider=provider.model_copy(update={"metadata": {"returncode": run_result.returncode}}),
        usage=UsageMetadata(),
        trace=trace_builder.events,
        error=error,
        output_artifacts=[
            _artifact_ref_for_path(
                path=path,
                artifact_id=f"openclaw_key_output_{index + 1}",
                artifact_type=OpenClawEvidenceArtifactTypes.KEY_OUTPUT,
                media_type=_media_type_for_path(path),
            )
            for index, path in enumerate(key_output_paths)
        ],
    )
    return _attach_openclaw_evidence(
        artifact=artifact,
        agent_id=agent_config.agent_id,
        container_image=run_profile.openclaw.image,
        generated_config_path=generated_config_path,
        raw_trace_path=raw_trace_path,
        log_path=command_log_path,
        workspace_snapshot_path=workspace_snapshot_path,
        workspace_diff_path=workspace_diff_path,
        key_output_paths=key_output_paths,
    )


def _prepare_runtime_root(runtime_root: Path | None) -> Path:
    if runtime_root is not None:
        resolved = runtime_root.expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
    return Path(tempfile.mkdtemp(prefix="pae-openclaw-")).resolve()


def _build_openclaw_environment(*, config_path: Path, state_dir: Path) -> dict[str, str]:
    state_dir.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "OPENCLAW_CONFIG_PATH": str(config_path),
        "OPENCLAW_STATE_DIR": str(state_dir),
    }


def _build_request_model(
    *,
    case_config: TestConfig,
    model_selection: ModelConfig,
    run_profile: RunProfileConfig,
    agent_config: OpenClawAgentConfig,
    resolved_config: ResolvedOpenClawConfig,
) -> RunRequestMetadata:
    return RunRequestMetadata(
        requested_model=resolved_config.requested_model,
        gateway="openclaw",
        execution_parameters=LlmExecutionParameters(
            timeout_seconds=float(run_profile.openclaw.timeout_seconds)
            if run_profile.openclaw is not None
            else None
        ),
        metadata={
            "case_metadata": dict(case_config.metadata),
            "input_context": dict(case_config.input.context),
            "attachments": [str(path) for path in case_config.input.attachments],
            "requested_runner_config": case_config.runner.model_dump(mode="json"),
            "model_selection": model_selection.model_dump(mode="json"),
            "openclaw": {
                "agent_id": agent_config.agent_id,
                "container_image": run_profile.openclaw.image if run_profile.openclaw else None,
            },
        },
    )


def _render_task_message(resolved_config: ResolvedOpenClawConfig) -> str:
    sections: list[str] = []
    for index, message in enumerate(resolved_config.case_messages, start=1):
        content = message.content or ""
        header = f"[{index}] {message.role}"
        if message.name:
            header += f" ({message.name})"
        sections.extend([header, content, ""])

    for attachment in resolved_config.case_attachments:
        raw_bytes = attachment.read_bytes()
        sections.extend(
            [
                f"[attachment] {attachment.name}",
                raw_bytes.decode("utf-8", errors="replace"),
                "",
            ]
        )

    if resolved_config.case_openclaw_hints:
        sections.extend(
            [
                "[openclaw_hints]",
                json.dumps(resolved_config.case_openclaw_hints, indent=2, sort_keys=True),
                "",
            ]
        )
    return "\n".join(sections).strip()


def _extract_final_output(stdout: str) -> str | None:
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(payload, Mapping):
        for key in ("content", "message", "response", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return stripped


def _resolve_key_output_paths(
    *,
    workspace_dir: Path,
    openclaw_hints: Mapping[str, Any],
) -> list[Path]:
    expected_artifact = openclaw_hints.get("expected_artifact")
    if isinstance(expected_artifact, str):
        candidate = (workspace_dir / expected_artifact).resolve()
        return [candidate] if candidate.is_file() else []
    if isinstance(expected_artifact, list):
        resolved: list[Path] = []
        for item in expected_artifact:
            if not isinstance(item, str):
                continue
            candidate = (workspace_dir / item).resolve()
            if candidate.is_file():
                resolved.append(candidate)
        return resolved
    return []


def _write_workspace_artifacts(
    *,
    template_dir: Path,
    workspace_dir: Path,
    snapshot_path: Path,
    diff_path: Path,
) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(snapshot_path, "w:gz") as archive:
        archive.add(workspace_dir, arcname="workspace")
    diff_path.write_text(
        _build_workspace_diff(template_dir=template_dir, workspace_dir=workspace_dir),
        encoding="utf-8",
    )


def _build_workspace_diff(*, template_dir: Path, workspace_dir: Path) -> str:
    template_files = _read_text_file_map(template_dir)
    workspace_files = _read_text_file_map(workspace_dir)
    all_paths = sorted(set(template_files) | set(workspace_files))
    chunks: list[str] = []
    for relative_path in all_paths:
        before = template_files.get(relative_path, "").splitlines()
        after = workspace_files.get(relative_path, "").splitlines()
        if before == after:
            continue
        chunks.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"template/{relative_path}",
                tofile=f"workspace/{relative_path}",
                lineterm="",
            )
        )
    return "\n".join(chunks) + ("\n" if chunks else "")


def _read_text_file_map(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    files = sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.as_posix(),
    )
    for path in files:
        mapping[path.relative_to(root).as_posix()] = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    return mapping


def _attach_openclaw_evidence(
    *,
    artifact: RunArtifact,
    agent_id: str,
    container_image: str,
    generated_config_path: Path,
    raw_trace_path: Path,
    log_path: Path,
    workspace_snapshot_path: Path,
    workspace_diff_path: Path,
    key_output_paths: list[Path],
) -> RunArtifact:
    evidence = OpenClawRunEvidence(
        agent_id=agent_id,
        container_image=container_image,
        generated_openclaw_config=_artifact_ref_for_path(
            path=generated_config_path,
            artifact_id="openclaw_config",
            artifact_type=OpenClawEvidenceArtifactTypes.GENERATED_OPENCLAW_CONFIG,
            media_type="application/json",
        ),
        raw_session_trace=_artifact_ref_for_path(
            path=raw_trace_path,
            artifact_id="openclaw_raw_trace",
            artifact_type=OpenClawEvidenceArtifactTypes.RAW_SESSION_TRACE,
            media_type="application/json",
        ),
        openclaw_logs=_artifact_ref_for_path(
            path=log_path,
            artifact_id="openclaw_logs",
            artifact_type=OpenClawEvidenceArtifactTypes.OPENCLAW_LOGS,
            media_type="text/plain",
        ),
        workspace_snapshot=_artifact_ref_for_path(
            path=workspace_snapshot_path,
            artifact_id="openclaw_workspace_snapshot",
            artifact_type=OpenClawEvidenceArtifactTypes.WORKSPACE_SNAPSHOT,
            media_type="application/gzip",
        ),
        workspace_diff=_artifact_ref_for_path(
            path=workspace_diff_path,
            artifact_id="openclaw_workspace_diff",
            artifact_type=OpenClawEvidenceArtifactTypes.WORKSPACE_DIFF,
            media_type="text/x-diff",
        ),
        key_output_artifacts=[
            _artifact_ref_for_path(
                path=path,
                artifact_id=f"openclaw_key_output_{index + 1}",
                artifact_type=OpenClawEvidenceArtifactTypes.KEY_OUTPUT,
                media_type=_media_type_for_path(path),
            )
            for index, path in enumerate(key_output_paths)
        ],
    )
    return with_openclaw_run_evidence(artifact, evidence)


def _artifact_ref_for_path(
    *,
    path: Path,
    artifact_id: str,
    artifact_type: str,
    media_type: str | None,
) -> OutputArtifactRef:
    payload = path.read_bytes()
    return OutputArtifactRef(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        uri=path.resolve().as_uri(),
        media_type=media_type,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _media_type_for_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".diff"}:
        return "text/plain"
    if suffix == ".json":
        return "application/json"
    return None


def _write_text_payload(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _append_command_log(
    path: Path,
    *,
    command_name: str,
    result: OpenClawCommandResult,
) -> None:
    chunks = [
        f"## {command_name}",
        f"returncode: {result.returncode}",
        f"timed_out: {result.timed_out}",
        "",
        "[stdout]",
        result.stdout,
        "",
        "[stderr]",
        result.stderr,
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(chunks))


def _build_terminal_artifact(
    *,
    identity: RunArtifactIdentity,
    status: RunStatus,
    timing: RunTiming,
    request_model: RunRequestMetadata,
    trace: list[TraceEvent],
    provider: ProviderMetadata,
    error: RunError,
) -> RunArtifact:
    return RunArtifact(
        identity=identity,
        status=status,
        timing=timing,
        request=request_model,
        provider=provider,
        usage=UsageMetadata(),
        trace=trace,
        error=error,
    )


def _build_timing(
    *,
    queued_at: datetime,
    started_at: datetime,
    started_monotonic: float,
) -> RunTiming:
    completed_at = datetime.now(UTC)
    return RunTiming(
        queued_at=queued_at,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=max(0.0, perf_counter() - started_monotonic),
    )


class _TraceBuilder:
    """Append-only builder for contiguous trace events."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def add_message(
        self,
        *,
        role: MessageRole,
        content: str | None,
        name: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.events.append(
            MessageTraceEvent(
                sequence=len(self.events),
                event_type="message",
                role=role,
                content=content,
                name=name,
                metadata=metadata,
            )
        )

    def add_runner_event(self, *, name: str, detail: str | None, metadata: dict[str, Any]) -> None:
        self.events.append(
            RunnerTraceEvent(
                sequence=len(self.events),
                event_type="runner",
                name=name,
                detail=detail,
                metadata=metadata,
            )
        )

    def add_final_output(self, content: str) -> None:
        self.events.append(
            FinalOutputTraceEvent(
                sequence=len(self.events),
                event_type="final_output",
                content=content,
            )
        )


def _run_subprocess(
    argv: list[str],
    *,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> OpenClawCommandResult:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            env=dict(env),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return OpenClawCommandResult(
            returncode=124,
            stdout=_coerce_subprocess_output(exc.stdout),
            stderr=_coerce_subprocess_output(exc.stderr),
            timed_out=True,
        )
    return OpenClawCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
    )


def _coerce_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
