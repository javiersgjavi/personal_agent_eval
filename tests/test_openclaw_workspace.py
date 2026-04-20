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


def test_materialize_openclaw_workspace_rejects_non_empty_destination(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    template_dir.mkdir()
    (template_dir / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    (workspace_dir / "existing.txt").write_text("occupied\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be empty before materialization"):
        materialize_openclaw_workspace(template_dir=template_dir, workspace_dir=workspace_dir)
