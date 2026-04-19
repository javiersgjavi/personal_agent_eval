"""Scatter chart: benchmark score vs total estimated cost per model.

Bubble area is proportional to average latency (seconds). Labels are rendered
as annotation boxes connected to the bubble by a thin line.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from personal_agent_eval.reporting.models import ModelSummary, StructuredReport

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "Model comparison: final quality vs estimated total benchmark cost"
DEFAULT_SUBTITLE = (
    "(Higher = better score, further left = lower estimated cost — bubble size = latency)"
)
DEFAULT_XLABEL = "Estimated cost to run the full benchmark ($, input + output, estimate)"
DEFAULT_YLABEL = "Overall benchmark score (0 to 10)"

# Bubble area range (matplotlib scatter `s` is in points²)
_BUBBLE_MIN = 80
_BUBBLE_MAX = 800
_BUBBLE_DEFAULT = 220  # used when no latency data is available


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
        costs.append(summary.total_usage.cost_usd)
        scores.append(float(summary.average_final_score))
        latencies.append(summary.average_latency_seconds)
    return labels, costs, scores, latencies


def _scale_latencies(latencies: list[float | None]) -> list[float]:
    """Map raw latency values to bubble area (points²).

    Models with no latency get the default size. When only one model has
    latency data the default size is used for all to avoid an uninformative
    single-point scale.
    """
    known = [v for v in latencies if v is not None]
    if len(known) < 2:
        return [_BUBBLE_DEFAULT] * len(latencies)
    lo, hi = min(known), max(known)
    result = []
    for v in latencies:
        if v is None:
            result.append(_BUBBLE_DEFAULT)
        elif hi == lo:
            result.append((_BUBBLE_MIN + _BUBBLE_MAX) / 2)
        else:
            # Linear interpolation on area (already perceptually reasonable
            # for latency comparisons; sqrt would be needed for true radius).
            result.append(_BUBBLE_MIN + (_BUBBLE_MAX - _BUBBLE_MIN) * (v - lo) / (hi - lo))
    return result


def _label_offset(x: float, y: float, x_range: float, y_range: float) -> tuple[float, float]:
    """Return a text offset (dx, dy) that points away from the chart centre."""
    cx, cy = x_range / 2, y_range / 2
    dx = x - cx
    dy = y - cy
    length = math.hypot(dx, dy) or 1.0
    scale_x = x_range * 0.10
    scale_y = y_range * 0.10
    return dx / length * scale_x, dy / length * scale_y


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
    """Write a score-vs-cost bubble chart PNG for each model in ``report``.

    Bubble area encodes average run latency. Requires ``matplotlib``
    (and ``adjustText`` for non-overlapping labels when installed).

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

    adjust_text_fn: Callable[..., Any] | None = None
    try:
        from adjustText import adjust_text as _adjust_text_import

        adjust_text_fn = cast(Callable[..., Any], _adjust_text_import)
    except ImportError:
        pass

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

    # Draw bubbles first so they are behind the labels
    ax.scatter(
        costs,
        scores,
        s=sizes,
        c=colors,
        edgecolors="black",
        linewidths=1.0,
        zorder=3,
        alpha=0.85,
    )

    # Determine axis ranges for offset computation
    x_range = max(costs) - min(costs) if len(costs) > 1 else (max(costs) or 1.0)
    y_range = max(scores) - min(scores) if len(scores) > 1 else 1.0
    if x_range == 0:
        x_range = max(costs) or 1.0
    if y_range == 0:
        y_range = 1.0

    texts = []
    for x, y, mid, lat in zip(costs, scores, labels, latencies, strict=True):
        short = _short_model_label(mid)
        lat_str = f"{lat:.1f}s" if lat is not None else "n/a"
        body = f"{short}\nScore: {y:.3f}\nCost: ${x:.2f}\nLatency: {lat_str}"

        dx, dy = _label_offset(x, y, x_range, y_range)

        ann = ax.annotate(
            body,
            xy=(x, y),
            xytext=(x + dx, y + dy),
            fontsize=8,
            ha="center",
            va="center",
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "edgecolor": "black",
                "linewidth": 0.7,
                "alpha": 0.9,
            },
            arrowprops={
                "arrowstyle": "-",
                "color": "gray",
                "lw": 0.6,
                "alpha": 0.7,
            },
            zorder=5,
        )
        texts.append(ann)

    if adjust_text_fn is not None:
        adjust_text_fn(
            texts,
            x=costs,
            y=scores,
            ax=ax,
            expand_points=(1.6, 1.8),
            expand_text=(1.3, 1.4),
            arrowprops={
                "arrowstyle": "-",
                "color": "gray",
                "lw": 0.5,
                "alpha": 0.7,
            },
        )

    ax.set_xlabel(xlabel or DEFAULT_XLABEL, fontsize=10)
    ax.set_ylabel(ylabel or DEFAULT_YLABEL, fontsize=10)
    ax.grid(True, alpha=0.30, linestyle="-", linewidth=0.5)
    ax.set_axisbelow(True)

    ttl = title or DEFAULT_TITLE
    sub = subtitle if subtitle is not None else DEFAULT_SUBTITLE
    ax.set_title(f"{ttl}\n{sub}", fontsize=11, pad=12)

    y_pad = max(0.3, (max(scores) - min(scores)) * 0.08) if len(scores) > 1 else 0.5
    ax.set_ylim(max(0.0, min(scores) - y_pad), min(10.0, max(scores) + y_pad))

    x_max = max(costs) if costs else 0.0
    x_margin = max(0.02, x_max * 0.12) if x_max > 0 else 0.05
    ax.set_xlim(-x_margin * 0.3, x_max + x_margin)

    # Latency legend
    known_latencies = [v for v in latencies if v is not None]
    if len(known_latencies) >= 2:
        lo, hi = min(known_latencies), max(known_latencies)
        mid_val = (lo + hi) / 2
        for _lat_val, size_val, lbl in [
            (lo, _BUBBLE_MIN, f"{lo:.0f}s"),
            (mid_val, (_BUBBLE_MIN + _BUBBLE_MAX) / 2, f"{mid_val:.0f}s"),
            (hi, _BUBBLE_MAX, f"{hi:.0f}s"),
        ]:
            ax.scatter([], [], s=size_val, c="silver", edgecolors="black", lw=0.7, label=lbl)
        ax.legend(
            title="Avg latency",
            loc="upper left",
            framealpha=0.85,
            fontsize=8,
            title_fontsize=8,
        )

    fig.tight_layout(rect=(0, 0.05 if footnote else 0, 1, 1))
    if footnote:
        fig.text(0.5, 0.012, footnote, ha="center", fontsize=8, color="0.35")

    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    logger.info("Score/cost chart written to %s", output_path)
    return output_path
