"""OpenClaw workspace materialization helpers."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field

from personal_agent_eval.artifacts.run_artifact import ArtifactModel

OPENCLAW_STANDARD_WORKSPACE_FILES = (
    "AGENTS.md",
    "IDENTITY.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
)


class OpenClawWorkspaceManifestEntry(ArtifactModel):
    """One deterministic file entry in a materialized OpenClaw workspace."""

    relative_path: str
    source: Literal["template", "placeholder"]
    sha256: str
    size_bytes: int = Field(ge=0)


class OpenClawWorkspaceManifest(ArtifactModel):
    """Deterministic workspace manifest suitable for later fingerprint inputs."""

    entries: list[OpenClawWorkspaceManifestEntry] = Field(default_factory=list)
    placeholder_files: list[str] = Field(default_factory=list)


class MaterializedOpenClawWorkspace(ArtifactModel):
    """Filesystem result of copying and normalizing an OpenClaw workspace."""

    template_dir: Path
    workspace_dir: Path
    manifest: OpenClawWorkspaceManifest


def materialize_openclaw_workspace(
    *,
    template_dir: Path,
    workspace_dir: Path,
) -> MaterializedOpenClawWorkspace:
    """Copy an agent workspace template and inject deterministic placeholders."""
    resolved_template_dir = template_dir.expanduser().resolve()
    resolved_workspace_dir = workspace_dir.expanduser().resolve()

    if not resolved_template_dir.exists():
        raise ValueError(
            f"OpenClaw workspace template directory '{resolved_template_dir}' does not exist."
        )
    if not resolved_template_dir.is_dir():
        raise ValueError(
            f"OpenClaw workspace template path '{resolved_template_dir}' must be a directory."
        )

    _prepare_workspace_dir(resolved_workspace_dir)

    for source_path in _iter_template_files(resolved_template_dir):
        relative_path = source_path.relative_to(resolved_template_dir)
        destination_path = resolved_workspace_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination_path)

    placeholder_files: list[str] = []
    for file_name in OPENCLAW_STANDARD_WORKSPACE_FILES:
        destination_path = resolved_workspace_dir / file_name
        if destination_path.exists():
            continue
        destination_path.write_text(_placeholder_text(file_name), encoding="utf-8")
        placeholder_files.append(file_name)

    placeholder_paths = frozenset(placeholder_files)
    manifest_entries = [
        _manifest_entry_for_path(
            path=path,
            workspace_dir=resolved_workspace_dir,
            placeholder_paths=placeholder_paths,
        )
        for path in _iter_workspace_files(resolved_workspace_dir)
    ]
    return MaterializedOpenClawWorkspace(
        template_dir=resolved_template_dir,
        workspace_dir=resolved_workspace_dir,
        manifest=OpenClawWorkspaceManifest(
            entries=manifest_entries,
            placeholder_files=sorted(placeholder_files),
        ),
    )


def _prepare_workspace_dir(workspace_dir: Path) -> None:
    if workspace_dir.exists():
        if not workspace_dir.is_dir():
            raise ValueError(
                f"OpenClaw workspace destination '{workspace_dir}' must be a directory."
            )
        if any(workspace_dir.iterdir()):
            raise ValueError(
                f"OpenClaw workspace destination '{workspace_dir}' must be empty before "
                "materialization."
            )
        return
    workspace_dir.mkdir(parents=True, exist_ok=True)


def _iter_template_files(template_dir: Path) -> list[Path]:
    files = [path for path in template_dir.rglob("*") if path.is_file()]
    return sorted(files, key=lambda path: path.relative_to(template_dir).as_posix())


def _iter_workspace_files(workspace_dir: Path) -> list[Path]:
    files = [path for path in workspace_dir.rglob("*") if path.is_file()]
    return sorted(files, key=lambda path: path.relative_to(workspace_dir).as_posix())


def _manifest_entry_for_path(
    *,
    path: Path,
    workspace_dir: Path,
    placeholder_paths: frozenset[str],
) -> OpenClawWorkspaceManifestEntry:
    relative_path = path.relative_to(workspace_dir).as_posix()
    source: Literal["template", "placeholder"] = (
        "placeholder" if relative_path in placeholder_paths else "template"
    )
    payload = path.read_bytes()
    return OpenClawWorkspaceManifestEntry(
        relative_path=relative_path,
        source=source,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def _placeholder_text(file_name: str) -> str:
    title = file_name.removesuffix(".md")
    return "\n".join(
        [
            f"# {title}",
            "",
            "Benchmark-generated placeholder for OpenClaw workspace materialization.",
            "This file was missing from the reusable agent workspace template.",
            "",
        ]
    )
