"""Filesystem discovery for cases and suites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personal_agent_eval.config import (
    SuiteConfig,
    TestConfig,
    load_suite_config,
    load_test_config,
)


class CatalogError(ValueError):
    """Raised when catalog discovery or suite expansion fails."""


@dataclass(frozen=True, slots=True)
class CaseManifest:
    """A discovered and validated case config."""

    root_path: Path
    case_id: str
    case_path: Path
    test_path: Path
    config: TestConfig


@dataclass(frozen=True, slots=True)
class SuiteManifest:
    """A discovered and validated suite config."""

    root_path: Path
    suite_id: str
    suite_path: Path
    config: SuiteConfig


def discover_cases(root_path: str | Path) -> dict[str, CaseManifest]:
    """Discover all case manifests under a workspace root."""
    resolved_root = Path(root_path).expanduser().resolve()
    manifests_by_id: dict[str, CaseManifest] = {}

    for test_path in sorted((resolved_root / "configs" / "cases").glob("*/test.yaml")):
        config = load_test_config(test_path)
        manifest = CaseManifest(
            root_path=resolved_root,
            case_id=config.case_id,
            case_path=test_path.parent,
            test_path=test_path,
            config=config,
        )
        existing = manifests_by_id.get(manifest.case_id)
        if existing is not None:
            raise CatalogError(
                "Duplicate case_id "
                f"'{manifest.case_id}' discovered in '{existing.test_path}' and '{test_path}'."
            )
        manifests_by_id[manifest.case_id] = manifest

    return dict(sorted(manifests_by_id.items()))


def discover_suites(root_path: str | Path) -> dict[str, SuiteManifest]:
    """Discover all suite manifests under a workspace root."""
    resolved_root = Path(root_path).expanduser().resolve()
    manifests_by_id: dict[str, SuiteManifest] = {}

    for suite_path in sorted((resolved_root / "configs" / "suites").glob("*.yaml")):
        config = load_suite_config(suite_path)
        manifest = SuiteManifest(
            root_path=resolved_root,
            suite_id=config.suite_id,
            suite_path=suite_path,
            config=config,
        )
        manifests_by_id[manifest.suite_id] = manifest

    return dict(sorted(manifests_by_id.items()))


def expand_suite(root_path: str | Path, suite_id: str) -> list[CaseManifest]:
    """Expand a suite into a deterministic ordered list of case manifests."""
    cases = discover_cases(root_path)
    suites = discover_suites(root_path)

    suite = suites.get(suite_id)
    if suite is None:
        available = ", ".join(sorted(suites)) or "<none>"
        raise CatalogError(
            f"Suite '{suite_id}' was not found under '{Path(root_path).expanduser().resolve()}'. "
            f"Available suites: {available}."
        )

    _validate_case_references(cases=cases, suite=suite)

    selection = suite.config.case_selection
    explicit_case_ids = list(dict.fromkeys(selection.include_case_ids))
    excluded_case_ids = set(selection.exclude_case_ids)
    include_tags = set(selection.include_tags)
    exclude_tags = set(selection.exclude_tags)

    selected: dict[str, CaseManifest] = {case_id: cases[case_id] for case_id in explicit_case_ids}

    for case_id, manifest in cases.items():
        if case_id in selected:
            continue
        if explicit_case_ids:
            matches_include = bool(include_tags) and _matches_any_tag(manifest, include_tags)
            if not matches_include:
                continue
        elif include_tags and not _matches_any_tag(manifest, include_tags):
            continue

        if case_id in excluded_case_ids:
            continue
        if exclude_tags and _matches_any_tag(manifest, exclude_tags):
            continue

        selected[case_id] = manifest

    return [selected[case_id] for case_id in sorted(selected)]


def _matches_any_tag(manifest: CaseManifest, tags: set[str]) -> bool:
    return bool(set(manifest.config.tags) & tags)


def _validate_case_references(*, cases: dict[str, CaseManifest], suite: SuiteManifest) -> None:
    referenced_case_ids = set(suite.config.case_selection.include_case_ids) | set(
        suite.config.case_selection.exclude_case_ids
    )
    missing_case_ids = sorted(case_id for case_id in referenced_case_ids if case_id not in cases)
    if missing_case_ids:
        missing = ", ".join(missing_case_ids)
        raise CatalogError(
            f"Suite '{suite.suite_id}' references unknown case_id values: {missing}."
        )
