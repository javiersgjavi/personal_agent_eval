"""Canonical test config schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

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


class RubricScale(ConfigModel):
    """Optional judge rubric scale definition."""

    min: float = Field(default=0, ge=0)
    max: float = Field(default=10, ge=0)
    anchors: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_scale(self) -> RubricScale:
        if self.max <= self.min:
            raise ValueError("'rubric.scale.max' must be greater than 'rubric.scale.min'.")
        return self


class RubricCriterion(ConfigModel):
    """One rubric criterion (general guidance, not a deterministic check)."""

    name: str = Field(min_length=1)
    what_good_looks_like: str = Field(min_length=1)
    what_bad_looks_like: str = Field(min_length=1)


class Rubric(ConfigModel):
    """Optional general rubric shown to the judge."""

    version: Literal[1] = 1
    scale: RubricScale = Field(default_factory=RubricScale)
    criteria: list[RubricCriterion] = Field(default_factory=list)
    scoring_instructions: str | None = None


class _ResolvedPathCheck(ConfigModel):
    """Base model for declarative checks that resolve a local path."""

    path: Path

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


class FinalResponsePresentCheck(ConfigModel):
    """Require a non-empty final response in the run trace."""

    kind: Literal["final_response_present"]


class ToolCallCountCheck(ConfigModel):
    """Require an exact number of recorded tool calls."""

    kind: Literal["tool_call_count"]
    count: int = Field(ge=0)


class FileExistsCheck(_ResolvedPathCheck):
    """Require a file path to exist and be a regular file."""

    kind: Literal["file_exists"]


class FileContainsCheck(_ResolvedPathCheck):
    """Require a file path to exist and contain the provided text."""

    kind: Literal["file_contains"]
    text: str


class PathExistsCheck(_ResolvedPathCheck):
    """Require a filesystem path to exist."""

    kind: Literal["path_exists"]


class StatusIsCheck(ConfigModel):
    """Require a specific terminal run status."""

    kind: Literal["status_is"]
    status: Literal["success", "failed", "timed_out", "invalid", "provider_error"]


class OutputArtifactPresentCheck(ConfigModel):
    """Require a matching output artifact reference on the run artifact."""

    kind: Literal["output_artifact_present"]
    artifact_id: str | None = Field(default=None, pattern=ID_PATTERN)
    artifact_type: str | None = Field(default=None, pattern=ID_PATTERN)
    uri: str | None = None

    @model_validator(mode="after")
    def _validate_match_fields(self) -> OutputArtifactPresentCheck:
        if self.artifact_id is None and self.artifact_type is None and self.uri is None:
            raise ValueError(
                "An output artifact presence check requires at least one matcher field."
            )
        return self


class OpenClawWorkspaceFilePresentCheck(ConfigModel):
    """Require a workspace file (OpenClaw key output) recorded on the run artifact.

    Matches :class:`OutputArtifactRef` entries whose ``file://`` path ends with the given
    ``relative_path`` (or shares the same basename). Intended for ``runner.type: openclaw`` runs
    where outputs live as persisted file refs rather than case-relative paths.
    """

    kind: Literal["openclaw_workspace_file_present"]
    relative_path: str = Field(min_length=1)
    contains: str | None = None


type DeclarativeCheck = Annotated[
    FinalResponsePresentCheck
    | ToolCallCountCheck
    | FileExistsCheck
    | FileContainsCheck
    | PathExistsCheck
    | StatusIsCheck
    | OutputArtifactPresentCheck
    | OpenClawWorkspaceFilePresentCheck,
    Field(discriminator="kind"),
]


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
    dimensions: list[Literal["task", "process", "autonomy", "closeness", "efficiency", "spark"]] = (
        Field(default_factory=list)
    )
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

    @field_validator("dimensions")
    @classmethod
    def _normalize_dimensions(
        cls,
        value: list[Literal["task", "process", "autonomy", "closeness", "efficiency", "spark"]],
    ) -> list[Literal["task", "process", "autonomy", "closeness", "efficiency", "spark"]]:
        return sorted(set(value))


class TestConfig(ConfigModel):
    """Canonical case config."""

    schema_version: Literal[1]
    case_id: str = Field(pattern=ID_PATTERN)
    title: str
    runner: RunnerConfig
    input: TestInput
    expectations: Expectations = Field(default_factory=Expectations)
    rubric: Rubric | None = None
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
