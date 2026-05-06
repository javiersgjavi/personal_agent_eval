"""Scatter chart: benchmark score vs estimated subject-run cost per model."""

from __future__ import annotations

import logging
from pathlib import Path

from personal_agent_eval.reporting.models import ModelSummary, StructuredReport

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "Model comparison: final quality vs estimated subject-run cost"
DEFAULT_SUBTITLE = (
    "(Higher score is better; further left is lower estimated cost; bubble size is latency)"
)
DEFAULT_XLABEL = "Estimated subject-model cost to run the benchmark ($)"
DEFAULT_YLABEL = "Overall benchmark score (0 to 10)"

# Bubble area range (matplotlib scatter `s` is in points²)
_BUBBLE_MIN = 90
_BUBBLE_MAX = 520
_BUBBLE_DEFAULT = 210


def _short_model_label(model_id: str, *, max_len: int = 26) -> str:
    tail = model_id.split("/")[-1] if "/" in model_id else model_id
    return tail if len(tail) <= max_len else f"{tail[: max_len - 1]}\u2026"


def _collect_points(
    summaries: list[ModelSummary],
) -> tuple[list[str], list[float], list[float], list[float | None]]:
    labels: list[str] = []
    costs: list[float] = []
    scores: list[float] = []
    latencies: list[float | None] = []
    for summary in summaries:
        if summary.average_final_score is None:
            continue
        labels.append(summary.model_id)
        costs.append(summary.run_cost_usd)
        scores.append(float(summary.average_final_score))
        latencies.append(summary.average_latency_seconds)
    return labels, costs, scores, latencies


def _scale_latencies(latencies: list[float | None]) -> list[float]:
    known = [v for v in latencies if v is not None]
    if len(known) < 2:
        return [_BUBBLE_DEFAULT] * len(latencies)
    lo, hi = min(known), max(known)
    if lo == hi:
        return [(_BUBBLE_MIN + _BUBBLE_MAX) / 2] * len(latencies)
    sizes = []
    for value in latencies:
        if value is None:
            sizes.append(_BUBBLE_DEFAULT)
        else:
            sizes.append(_BUBBLE_MIN + (_BUBBLE_MAX - _BUBBLE_MIN) * (value - lo) / (hi - lo))
    return sizes


def _label_offsets(costs: list[float]) -> list[tuple[int, int]]:
    x_min = min(costs)
    x_max = max(costs)
    x_range = x_max - x_min or 1.0
    vertical = [12, -16, 18, -20, 4, -8, 24, -24]
    offsets: list[tuple[int, int]] = []
    for index, x_value in enumerate(costs):
        if x_value <= x_min + x_range * 0.12:
            dx = 14
        elif x_value >= x_max - x_range * 0.12:
            dx = -14
        else:
            dx = 14 if index % 2 else -14
        offsets.append((dx, vertical[index % len(vertical)]))
    return offsets


def render_score_cost_chart_png(
    report: StructuredReport,
    output_path: Path,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    xlabel: str | None = None,
    ylabel: str | None = None,
    footnote: str | None = None,
    dpi: int = 130,
    figsize: tuple[float, float] = (12.0, 8.0),
) -> Path:
    """Write a score-vs-cost scatter chart PNG for each model.

    Returns the resolved output path.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import colormaps
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Plotting requires matplotlib. Install with: "
            "`pip install 'personal-agent-eval[charts]'` "
            "or `uv sync --extra charts`."
        ) from exc

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    labels, costs, scores, latencies = _collect_points(report.model_summaries)
    if not scores:
        raise ValueError(
            "No model has an average score (average_final_score); "
            "cannot render the score/cost chart."
        )

    sizes = _scale_latencies(latencies)
    tab20 = colormaps["tab20"]
    colors = [tab20((i % 20) / 19.0) for i in range(len(scores))]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    for index in sorted(range(len(scores)), key=lambda item: sizes[item], reverse=True):
        ax.scatter(
            costs[index],
            scores[index],
            s=sizes[index],
            c=[colors[index]],
            edgecolors="black",
            linewidths=1.0,
            alpha=0.82,
            zorder=3,
        )

    for (x, y, label), (dx, dy) in zip(
        zip(costs, scores, labels, strict=True),
        _label_offsets(costs),
        strict=True,
    ):
        ax.annotate(
            _short_model_label(label, max_len=22),
            xy=(x, y),
            xytext=(dx, dy),
            textcoords="offset points",
            ha="left" if dx >= 0 else "right",
            va="bottom" if dy >= 0 else "top",
            fontsize=8,
            bbox={
                "boxstyle": "round,pad=0.18",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.78,
            },
            arrowprops={
                "arrowstyle": "-",
                "color": "0.45",
                "lw": 0.6,
                "alpha": 0.65,
            },
            zorder=4,
        )

    ax.set_xlabel(xlabel or DEFAULT_XLABEL, fontsize=10)
    ax.set_ylabel(ylabel or DEFAULT_YLABEL, fontsize=10)
    ax.grid(True, alpha=0.28, linestyle="-", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ttl = title or DEFAULT_TITLE
    sub = subtitle if subtitle is not None else DEFAULT_SUBTITLE
    ax.set_title(f"{ttl}\n{sub}", fontsize=12, pad=14)

    x_max = max(costs) if costs else 1.0
    x_margin = max(x_max * 0.12, 0.35)
    ax.set_xlim(0, x_max + x_margin)
    y_span = max(scores) - min(scores) if len(scores) > 1 else 1.0
    y_margin = max(y_span * 0.12, 0.25)
    ax.set_ylim(max(0.0, min(scores) - y_margin), min(10.0, max(scores) + y_margin))

    fig.subplots_adjust(left=0.10, right=0.98, top=0.88, bottom=0.13 if footnote else 0.10)

    if footnote:
        fig.text(0.5, 0.035, footnote, ha="center", fontsize=8, color="0.35")

    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    logger.info("Score/cost chart written to %s", output_path)
    return output_path
