"""Canonical test config schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import (
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from personal_agent_eval.config._base import (
    ID_PATTERN,
    ConfigError,
    ConfigModel,
    load_yaml_mapping,
)


class MessageSource(ConfigModel):
    """Reference an external YAML or JSON message payload."""

    path: Path
    format: Literal["yaml", "json"] | None = None

    @field_validator("path", mode="before")
    @classmethod
    def _coerce_path(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value)
        return value

    @field_validator("path")
    @classmethod
    def _resolve_path(cls, value: Path, info: ValidationInfo) -> Path:
        base_path = info.context.get("base_path") if info.context else None
        if base_path is None:
            return value.expanduser().resolve()
        return (base_path / value).expanduser().resolve()


class Message(ConfigModel):
    """An input message, either inline or external."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    source: MessageSource | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _validate_message_source(self) -> Message:
        if self.content is None and self.source is None:
            raise ValueError("A message requires either inline 'content' or a 'source' reference.")
        if self.content is not None and self.source is not None:
            raise ValueError("A message cannot define both 'content' and 'source'.")
        return self


class RunnerConfig(ConfigModel):
    """Runner selector and runner-specific options."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: Literal["llm_probe", "openclaw"]


class TestInput(ConfigModel):
    """Canonical test input block."""

    messages: list[Message] = Field(default_factory=list)
    attachments: list[Path] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attachments", mode="before")
    @classmethod
    def _normalize_attachments(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("attachments")
    @classmethod
    def _resolve_attachments(cls, value: list[Path], info: ValidationInfo) -> list[Path]:
        base_path = info.context.get("base_path") if info.context else None
        if base_path is None:
            return [path.expanduser().resolve() for path in value]
        return [(base_path / path).expanduser().resolve() for path in value]


class Expectation(ConfigModel):
    """An expectation statement with optional metadata."""

    text: str
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Expectations(ConfigModel):
    """Hard and soft expectation groups."""

    hard_expectations: list[Expectation] = Field(default_factory=list)
    soft_expectations: list[Expectation] = Field(default_factory=list)


class DeclarativeCheck(ConfigModel):
    """A deterministic declarative assertion."""

    kind: Literal["contains_text", "matches_regex", "json_path_equals"]
    target: Literal["final_output", "full_trace", "metadata"] = "final_output"
    value: str
    description: str | None = None


class PythonHook(ConfigModel):
    """A Python hook reference for a deterministic check."""

    import_path: str | None = None
    path: Path | None = None
    callable_name: str

    @field_validator("path", mode="before")
    @classmethod
    def _coerce_hook_path(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value)
        return value

    @field_validator("path")
    @classmethod
    def _resolve_hook_path(cls, value: Path | None, info: ValidationInfo) -> Path | None:
        if value is None:
            return None
        base_path = info.context.get("base_path") if info.context else None
        if base_path is None:
            return value.expanduser().resolve()
        return (base_path / value).expanduser().resolve()

    @model_validator(mode="after")
    def _validate_hook_reference(self) -> PythonHook:
        if self.import_path is None and self.path is None:
            raise ValueError("A Python hook requires either 'import_path' or 'path'.")
        if self.import_path is not None and self.path is not None:
            raise ValueError("A Python hook cannot define both 'import_path' and 'path'.")
        return self


class DeterministicCheck(ConfigModel):
    """Declarative or custom deterministic check."""

    check_id: str = Field(pattern=ID_PATTERN)
    description: str | None = None
    declarative: DeclarativeCheck | None = None
    python_hook: PythonHook | None = None

    @model_validator(mode="after")
    def _validate_check_variant(self) -> DeterministicCheck:
        if self.declarative is None and self.python_hook is None:
            raise ValueError(
                "A deterministic check requires either 'declarative' or 'python_hook'."
            )
        if self.declarative is not None and self.python_hook is not None:
            raise ValueError(
                "A deterministic check cannot define both 'declarative' and 'python_hook'."
            )
        return self


class TestConfig(ConfigModel):
    """Canonical case config."""

    schema_version: Literal[1]
    case_id: str = Field(pattern=ID_PATTERN)
    title: str
    runner: RunnerConfig
    input: TestInput
    expectations: Expectations = Field(default_factory=Expectations)
    deterministic_checks: list[DeterministicCheck] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        deduplicated = {tag.strip() for tag in value if tag.strip()}
        return sorted(deduplicated)


def load_test_config(path: str | Path) -> TestConfig:
    """Load and validate a canonical test config."""
    payload, resolved_path = load_yaml_mapping(path)

    try:
        config = TestConfig.model_validate(payload, context={"base_path": resolved_path.parent})
    except ValidationError as exc:
        raise ConfigError(f"Invalid test config '{resolved_path}': {exc}") from exc

    return config.with_source_path(resolved_path)
