from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent_eval.catalog import (
    CatalogError,
    discover_cases,
    discover_suites,
    expand_suite,
)


def test_discover_cases_loads_manifests_from_workspace_root(tmp_path: Path) -> None:
    _write_case(tmp_path, "beta_case", tags=["smoke"])
    _write_case(tmp_path, "alpha_case", tags=["regression"])

    cases = discover_cases(tmp_path)

    assert list(cases) == ["alpha_case", "beta_case"]
    assert cases["alpha_case"].root_path == tmp_path.resolve()
    assert cases["alpha_case"].case_path == (tmp_path / "configs" / "cases" / "alpha_case").resolve()
    assert cases["alpha_case"].test_path == (
        tmp_path / "configs" / "cases" / "alpha_case" / "test.yaml"
    ).resolve()
    assert cases["alpha_case"].config.case_id == "alpha_case"
    assert cases["alpha_case"].config.tags == ["regression"]


def test_discover_suites_loads_manifests_from_workspace_root(tmp_path: Path) -> None:
    _write_suite(tmp_path, "smoke_suite", include_case_ids=["alpha_case"])

    suites = discover_suites(tmp_path)

    assert list(suites) == ["smoke_suite"]
    assert suites["smoke_suite"].suite_path == (
        tmp_path / "configs" / "suites" / "smoke_suite.yaml"
    ).resolve()
    assert suites["smoke_suite"].config.case_selection.include_case_ids == ["alpha_case"]


def test_expand_suite_applies_selection_exclusion_and_explicit_priority(
    tmp_path: Path,
) -> None:
    _write_case(tmp_path, "alpha_case", tags=["smoke"])
    _write_case(tmp_path, "beta_case", tags=["smoke", "skip"])
    _write_case(tmp_path, "gamma_case", tags=["skip"])
    _write_suite(
        tmp_path,
        "selected_suite",
        include_case_ids=["gamma_case"],
        exclude_case_ids=["alpha_case", "gamma_case"],
        include_tags=["smoke"],
        exclude_tags=["skip"],
    )

    manifests = expand_suite(tmp_path, "selected_suite")

    assert [manifest.case_id for manifest in manifests] == ["gamma_case"]


def test_expand_suite_excludes_cases_when_no_include_filters_are_set(tmp_path: Path) -> None:
    _write_case(tmp_path, "alpha_case", tags=["smoke"])
    _write_case(tmp_path, "beta_case", tags=["regression"])
    _write_case(tmp_path, "gamma_case", tags=["skip"])
    _write_suite(
        tmp_path,
        "all_cases_suite",
        exclude_case_ids=["beta_case"],
        exclude_tags=["skip"],
    )

    manifests = expand_suite(tmp_path, "all_cases_suite")

    assert [manifest.case_id for manifest in manifests] == ["alpha_case"]


def test_discover_cases_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    _write_case(tmp_path, "shared_case", directory="first_case")
    _write_case(tmp_path, "shared_case", directory="second_case")

    with pytest.raises(CatalogError, match="Duplicate case_id 'shared_case'"):
        discover_cases(tmp_path)


@pytest.mark.parametrize("field_name", ["include_case_ids", "exclude_case_ids"])
def test_expand_suite_rejects_missing_case_references(tmp_path: Path, field_name: str) -> None:
    _write_case(tmp_path, "present_case")
    kwargs = {field_name: ["missing_case"]}
    _write_suite(tmp_path, "broken_suite", **kwargs)

    with pytest.raises(CatalogError, match="references unknown case_id values: missing_case"):
        expand_suite(tmp_path, "broken_suite")


def test_expand_suite_returns_cases_sorted_by_case_id(tmp_path: Path) -> None:
    _write_case(tmp_path, "zulu_case", tags=["smoke"])
    _write_case(tmp_path, "alpha_case", tags=["smoke"])
    _write_case(tmp_path, "mid_case", tags=["smoke"])
    _write_suite(tmp_path, "sorted_suite", include_tags=["smoke"])

    manifests = expand_suite(tmp_path, "sorted_suite")

    assert [manifest.case_id for manifest in manifests] == [
        "alpha_case",
        "mid_case",
        "zulu_case",
    ]


def _write_case(
    root_path: Path,
    case_id: str,
    *,
    directory: str | None = None,
    tags: list[str] | None = None,
) -> None:
    case_directory = root_path / "configs" / "cases" / (directory or case_id)
    case_directory.mkdir(parents=True, exist_ok=True)

    lines = [
        "schema_version: 1",
        f"case_id: {case_id}",
        f"title: {case_id.replace('_', ' ').title()}",
        "runner:",
        "  type: llm_probe",
        "input:",
        "  messages: []",
    ]
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {tag}" for tag in tags)

    (case_directory / "test.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_suite(
    root_path: Path,
    suite_id: str,
    *,
    include_case_ids: list[str] | None = None,
    exclude_case_ids: list[str] | None = None,
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
) -> None:
    suites_directory = root_path / "configs" / "suites"
    suites_directory.mkdir(parents=True, exist_ok=True)

    lines = [
        "schema_version: 1",
        f"suite_id: {suite_id}",
        f"title: {suite_id.replace('_', ' ').title()}",
    ]

    selection_lines = _render_selection_lines(
        include_case_ids=include_case_ids,
        exclude_case_ids=exclude_case_ids,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
    )
    if selection_lines:
        lines.append("case_selection:")
        lines.extend(selection_lines)

    (suites_directory / f"{suite_id}.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_selection_lines(
    *,
    include_case_ids: list[str] | None,
    exclude_case_ids: list[str] | None,
    include_tags: list[str] | None,
    exclude_tags: list[str] | None,
) -> list[str]:
    fields = [
        ("include_case_ids", include_case_ids or []),
        ("exclude_case_ids", exclude_case_ids or []),
        ("include_tags", include_tags or []),
        ("exclude_tags", exclude_tags or []),
    ]
    lines: list[str] = []
    for field_name, values in fields:
        if not values:
            continue
        lines.append(f"  {field_name}:")
        lines.extend(f"    - {value}" for value in values)
    return lines
