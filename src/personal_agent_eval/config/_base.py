"""Shared config helpers and base classes."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, PrivateAttr

SCHEMA_VERSION = 1
ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"


class ConfigError(ValueError):
    """Raised when a config file cannot be parsed or validated."""


class ConfigModel(BaseModel):
    """Base class for canonical config objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    _source_path: Path | None = PrivateAttr(default=None)

    @property
    def source_path(self) -> Path | None:
        """Return the source YAML file used to build this config."""
        return self._source_path

    def with_source_path(self, source_path: Path) -> Self:
        """Attach the source path after validation."""
        self._source_path = source_path
        return self


def load_yaml_mapping(path: str | Path) -> tuple[dict[str, Any], Path]:
    """Load a YAML file and require a top-level mapping."""
    resolved_path = Path(path).expanduser().resolve()

    try:
        content = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        message = f"Unable to read config file '{resolved_path}': {exc.strerror or exc!s}"
        raise ConfigError(message) from exc

    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in '{resolved_path}': {exc}") from exc

    if loaded is None:
        return {}, resolved_path

    if not isinstance(loaded, Mapping):
        raise ConfigError(
            f"Config file '{resolved_path}' must contain a top-level mapping, got "
            f"{type(loaded).__name__}."
        )

    return dict(loaded), resolved_path
