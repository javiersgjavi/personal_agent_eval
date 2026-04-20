from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent_eval.domains.openclaw import (
    OPENCLAW_STANDARD_WORKSPACE_FILES,
    materialize_openclaw_workspace,
)


def test_materialize_openclaw_workspace_copies_files_and_injects_placeholders(
    tmp_path: Path,
) -> None:
    template_dir = tmp_path / "template"
    docs_dir = template_dir / "docs"
    docs_dir.mkdir(parents=True)
    (template_dir / "AGENTS.md").write_text("# Custom agent\n", encoding="utf-8")
    (docs_dir / "guide.txt").write_text("hello workspace\n", encoding="utf-8")

    materialized = materialize_openclaw_workspace(
        template_dir=template_dir,
        workspace_dir=tmp_path / "runs" / "workspace",
    )

    assert materialized.template_dir == template_dir.resolve()
    assert materialized.workspace_dir == (tmp_path / "runs" / "workspace").resolve()
    assert (materialized.workspace_dir / "AGENTS.md").read_text(
        encoding="utf-8"
    ) == "# Custom agent\n"
    assert (materialized.workspace_dir / "docs" / "guide.txt").read_text(
        encoding="utf-8"
    ) == "hello workspace\n"
    assert materialized.manifest.placeholder_files == [
        "IDENTITY.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
    ]
    assert [entry.relative_path for entry in materialized.manifest.entries] == [
        "AGENTS.md",
        "IDENTITY.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
        "docs/guide.txt",
    ]
    assert {entry.relative_path: entry.source for entry in materialized.manifest.entries} == {
        "AGENTS.md": "template",
        "IDENTITY.md": "placeholder",
        "SOUL.md": "placeholder",
        "TOOLS.md": "placeholder",
        "USER.md": "placeholder",
        "docs/guide.txt": "template",
    }
    for file_name in materialized.manifest.placeholder_files:
        placeholder_text = (materialized.workspace_dir / file_name).read_text(encoding="utf-8")
        assert "Benchmark-generated placeholder" in placeholder_text


def test_materialize_openclaw_workspace_manifest_is_deterministic(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    nested_dir = template_dir / "nested"
    nested_dir.mkdir(parents=True)
    (nested_dir / "b.txt").write_text("second\n", encoding="utf-8")
    (template_dir / "z-last.txt").write_text("third\n", encoding="utf-8")
    (template_dir / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")

    first = materialize_openclaw_workspace(
        template_dir=template_dir,
        workspace_dir=tmp_path / "run-a" / "workspace",
    )
    second = materialize_openclaw_workspace(
        template_dir=template_dir,
        workspace_dir=tmp_path / "run-b" / "workspace",
    )

    assert first.manifest == second.manifest
    assert first.manifest.placeholder_files == sorted(
        set(OPENCLAW_STANDARD_WORKSPACE_FILES) - {"AGENTS.md"}
    )


def test_materialize_openclaw_workspace_preserves_large_utf8_files_intact(
    tmp_path: Path,
) -> None:
    """Large AGENTS.md / TOOLS.md copy byte-for-byte (OpenClaw reads them from the workspace)."""
    template_dir = tmp_path / "template"
    template_dir.mkdir()
    # > typical OpenClaw default bootstrap per-file caps; materialization must not truncate.
    large_agents = ("δημοτικό\n" * 8_000) + "END_AGENTS\n"
    large_tools = ("Z" * 35_000) + "\nEND_TOOLS\n"
    (template_dir / "AGENTS.md").write_text(large_agents, encoding="utf-8")
    (template_dir / "TOOLS.md").write_text(large_tools, encoding="utf-8")

    materialized = materialize_openclaw_workspace(
        template_dir=template_dir,
        workspace_dir=tmp_path / "workspace-out",
    )

    out_agents = materialized.workspace_dir / "AGENTS.md"
    out_tools = materialized.workspace_dir / "TOOLS.md"
    assert out_agents.read_bytes() == large_agents.encode("utf-8")
    assert out_tools.read_bytes() == large_tools.encode("utf-8")
    assert out_agents.read_text(encoding="utf-8") == large_agents
    assert out_tools.read_text(encoding="utf-8") == large_tools

    by_path = {e.relative_path: e for e in materialized.manifest.entries}
    assert by_path["AGENTS.md"].size_bytes == len(large_agents.encode("utf-8"))
    assert by_path["TOOLS.md"].size_bytes == len(large_tools.encode("utf-8"))
    assert by_path["AGENTS.md"].source == "template"
    assert by_path["TOOLS.md"].source == "template"


def test_materialize_openclaw_workspace_rejects_non_empty_destination(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    template_dir.mkdir()
    (template_dir / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "existing.txt").write_text("occupied\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be empty before materialization"):
        materialize_openclaw_workspace(template_dir=template_dir, workspace_dir=workspace_dir)
