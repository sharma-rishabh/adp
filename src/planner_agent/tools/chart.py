"""Chart generation for habit and time-tracking visualizations.

Uses matplotlib to produce PNG images saved into the sandbox.
This module is stateless — each call receives data and returns a path.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_chart(
    chart_type: str,
    title: str,
    data_json: str,
    output_dir: str | Path,
    y_label: str = "Value",
) -> str:
    """Generate a chart PNG and return its absolute path.

    Args:
        chart_type: One of ``bar``, ``line``, or ``cumulative``.
        title: Chart title.
        data_json: JSON string — a list of ``{"date": "YYYY-MM-DD", "value": <number>}`` objects.
        output_dir: Directory where the PNG will be saved.
        y_label: Label for the Y-axis (e.g. ``Minutes``, ``Pages``).

    Returns:
        Absolute path to the generated PNG file.

    Raises:
        ValueError: If ``chart_type`` is unsupported or data is invalid.
    """
    try:
        data: list[dict[str, Any]] = json.loads(data_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON data: {exc}") from exc

    if not data:
        raise ValueError("Data list is empty — nothing to chart.")

    dates = [datetime.strptime(d["date"], "%Y-%m-%d") for d in data]
    values = [float(d["value"]) for d in data]

    fig, ax = plt.subplots(figsize=(8, 4))

    if chart_type == "bar":
        ax.bar(dates, values, width=0.8, color="#4CAF50")
    elif chart_type == "line":
        ax.plot(dates, values, marker="o", linewidth=2, color="#2196F3")
    elif chart_type == "cumulative":
        cumulative = []
        running = 0.0
        for v in values:
            running += v
            cumulative.append(running)
        ax.fill_between(dates, cumulative, alpha=0.3, color="#FF9800")
        ax.plot(dates, cumulative, marker="o", linewidth=2, color="#FF9800")
    else:
        plt.close(fig)
        raise ValueError(f"Unsupported chart_type: {chart_type}. Use bar, line, or cumulative.")

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel(y_label)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=45)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filename = f"chart_{uuid.uuid4().hex[:8]}.png"
    filepath = output_path / filename
    fig.savefig(filepath, dpi=100)
    plt.close(fig)

    logger.info("Generated chart: %s", filepath)
    return str(filepath)

