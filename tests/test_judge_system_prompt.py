"""Tests for judge system prompt resolution from evaluation profiles."""

from pathlib import Path

import pytest

from personal_agent_eval.config import ConfigError, load_evaluation_profile
from personal_agent_eval.judge.system_prompt import (
    DEFAULT_JUDGE_SYSTEM_PROMPT_BASENAME,
    DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH,
    resolve_judge_system_prompt_details,
    resolve_judge_system_prompt_text,
)


def test_resolve_uses_judge_system_default_from_prompts_subdirectory(tmp_path: Path) -> None:
    prof_dir = tmp_path / "evaluation_profiles"
    prompts_dir = prof_dir / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / DEFAULT_JUDGE_SYSTEM_PROMPT_BASENAME).write_text(
        "Hello\nWorld\n",
        encoding="utf-8",
    )
    (prof_dir / "minimal.yaml").write_text(
        """schema_version: 1
evaluation_profile_id: minimal
title: Minimal
""",
        encoding="utf-8",
    )
    cfg = load_evaluation_profile(prof_dir / "minimal.yaml")
    assert resolve_judge_system_prompt_text(cfg) == "Hello World"
    assert resolve_judge_system_prompt_details(cfg) == {
        "source": f"default:{DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH.as_posix()}",
        "text": "Hello World",
    }


def test_resolve_repo_evaluation_profile_uses_configs_default_file() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_evaluation_profile(
        repo_root / "configs" / "evaluation_profiles" / "judge_gpt54_mini.yaml"
    )
    text = resolve_judge_system_prompt_text(cfg)
    assert "strict evaluation judge" in text
    assert "`dimensions`" in text
    assert (
        resolve_judge_system_prompt_details(cfg)["source"]
        == "path:prompts/judge_system_default.txt"
    )


def test_resolve_judge_system_prompt_from_path_relative_to_profile(tmp_path: Path) -> None:
    prof_dir = tmp_path / "configs" / "evaluation_profiles"
    prof_dir.mkdir(parents=True)
    prompts = prof_dir / "prompts"
    prompts.mkdir()
    (prompts / "mine.txt").write_text("Line one\nLine two\n", encoding="utf-8")
    (prof_dir / "with_path.yaml").write_text(
        """schema_version: 1
evaluation_profile_id: path_prompt
title: Path prompt
judge_system_prompt_path: prompts/mine.txt
""",
        encoding="utf-8",
    )
    cfg = load_evaluation_profile(prof_dir / "with_path.yaml")
    assert resolve_judge_system_prompt_text(cfg) == "Line one Line two"
    assert resolve_judge_system_prompt_details(cfg)["source"] == "path:prompts/mine.txt"


def test_resolve_judge_system_prompt_inline_in_yaml(tmp_path: Path) -> None:
    prof_dir = tmp_path / "configs" / "evaluation_profiles"
    prof_dir.mkdir(parents=True)
    (prof_dir / "inline.yaml").write_text(
        """schema_version: 1
evaluation_profile_id: inline_prompt
title: Inline prompt
judge_system_prompt: |
  First line
  Second line
""",
        encoding="utf-8",
    )
    cfg = load_evaluation_profile(prof_dir / "inline.yaml")
    assert resolve_judge_system_prompt_text(cfg) == "First line Second line"


def test_resolve_judge_system_prompt_path_missing_file_raises(tmp_path: Path) -> None:
    prof_dir = tmp_path / "configs" / "evaluation_profiles"
    prof_dir.mkdir(parents=True)
    (prof_dir / "bad.yaml").write_text(
        """schema_version: 1
evaluation_profile_id: missing_prompt
title: Missing
judge_system_prompt_path: prompts/nope.txt
""",
        encoding="utf-8",
    )
    cfg = load_evaluation_profile(prof_dir / "bad.yaml")
    with pytest.raises(ConfigError, match="not found"):
        resolve_judge_system_prompt_text(cfg)


def test_resolve_without_default_file_raises(tmp_path: Path) -> None:
    prof_dir = tmp_path / "configs" / "evaluation_profiles"
    prof_dir.mkdir(parents=True)
    (prof_dir / "no_default.yaml").write_text(
        """schema_version: 1
evaluation_profile_id: no_default
title: No default file
""",
        encoding="utf-8",
    )
    cfg = load_evaluation_profile(prof_dir / "no_default.yaml")
    with pytest.raises(ConfigError, match=DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH.as_posix()):
        resolve_judge_system_prompt_text(cfg)
