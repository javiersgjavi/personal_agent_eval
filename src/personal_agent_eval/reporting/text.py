"""Small terminal-friendly formatting helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render a plain-text table with aligned columns."""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    header_line = "  ".join(
        header.ljust(widths[index]) for index, header in enumerate(headers)
    )
    divider_line = "  ".join("-" * width for width in widths)
    row_lines = [
        "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([header_line, divider_line, *row_lines])


def render_bar(label: str, value: float | None, *, width: int = 20) -> str:
    """Render one simple ASCII bar line on a 0-10 scale."""
    if value is None:
        return f"{label.ljust(12)} {'-' * width} n/a"

    filled = max(0, min(width, round((value / 10.0) * width)))
    bar = "#" * filled + "-" * (width - filled)
    return f"{label.ljust(12)} {bar} {value:.2f}"


def join_sections(sections: Iterable[str]) -> str:
    """Join non-empty rendered sections with a blank line."""
    return "\n\n".join(section for section in sections if section.strip())

