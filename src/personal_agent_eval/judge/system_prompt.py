"""Judge system prompt resolution from evaluation profiles."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from personal_agent_eval.config._base import ConfigError
from personal_agent_eval.config.evaluation_profile import EvaluationProfileConfig

DEFAULT_JUDGE_SYSTEM_PROMPT_BASENAME = "judge_system_default.md"
DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH = Path("prompts") / DEFAULT_JUDGE_SYSTEM_PROMPT_BASENAME


def _normalize_multiline_prompt(raw: str) -> str:
    """Join non-empty lines with a single space (allows readable wrapped .txt files)."""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return " ".join(lines)


def _read_prompt_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".md":
        text = raw.strip().replace("\r\n", "\n").replace("\r", "\n")
    else:
        text = _normalize_multiline_prompt(raw)
    if not text:
        raise ConfigError(f"Judge system prompt file is empty: {path}")
    return text


def _resolve_prompt_file_path(profile: EvaluationProfileConfig, relative_path: str) -> Path:
    base = profile.source_path
    if base is None:
        raise ConfigError(
            "judge_system_prompt_path requires the evaluation profile to be loaded from a file."
        )
    file_path = (base.parent / relative_path).expanduser()
    try:
        resolved = file_path.resolve()
    except OSError as exc:
        raise ConfigError(f"Invalid judge system prompt path '{file_path}': {exc}") from exc
    if not resolved.is_file():
        raise ConfigError(f"Judge system prompt file not found: {resolved}")
    return resolved


def resolve_judge_system_prompt_details(profile: EvaluationProfileConfig) -> dict[str, str]:
    """Resolve the exact prompt text and its source descriptor for ``profile``."""
    if profile.judge_system_prompt is not None and profile.judge_system_prompt.strip():
        return {
            "source": "inline",
            "text": _normalize_multiline_prompt(profile.judge_system_prompt),
        }
    if profile.judge_system_prompt_path is not None and profile.judge_system_prompt_path.strip():
        resolved = _resolve_prompt_file_path(profile, profile.judge_system_prompt_path.strip())
        return {
            "source": f"path:{profile.judge_system_prompt_path}",
            "text": _read_prompt_file(resolved),
        }

    base = profile.source_path
    if base is None:
        raise ConfigError(
            "Set judge_system_prompt or judge_system_prompt_path on the evaluation profile. "
            "Recommended: put the shared prompt in "
            f"'{DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH.as_posix()}' "
            "and reference it from the YAML."
        )
    implicit = (base.parent / DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH).expanduser()
    try:
        implicit_resolved = implicit.resolve()
    except OSError as exc:
        raise ConfigError(f"Invalid implicit judge system prompt path '{implicit}': {exc}") from exc
    if implicit_resolved.is_file():
        return {
            "source": f"default:{DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH.as_posix()}",
            "text": _read_prompt_file(implicit_resolved),
        }
    raise ConfigError(
        "Missing judge system prompt: set 'judge_system_prompt' or "
        "'judge_system_prompt_path' in the profile. Recommended shared location: "
        f"'{DEFAULT_JUDGE_SYSTEM_PROMPT_RELATIVE_PATH.as_posix()}'."
    )


def resolve_judge_system_prompt_text(profile: EvaluationProfileConfig) -> str:
    """Resolve the judge system prompt for ``profile``.

    Resolution order:

    1. ``judge_system_prompt`` (inline YAML multiline string).
    2. ``judge_system_prompt_path`` (UTF-8 file path relative to the profile YAML).
    3. Otherwise, if the profile was loaded from a file, the shared default at
       ``prompts/judge_system_default.md`` relative to that YAML.

    If none of the above apply, a :class:`ConfigError` is raised.
    """
    return resolve_judge_system_prompt_details(profile)["text"]


def judge_system_prompt_fingerprint_material(profile: EvaluationProfileConfig) -> dict[str, Any]:
    """Return a JSON-serializable blob for evaluation fingerprinting."""
    details = resolve_judge_system_prompt_details(profile)
    text = details["text"]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"source": details["source"], "sha256": digest}
