#!/usr/bin/env python3
"""
Generate Tokyo Night GitHub contribution graph SVGs.

Two variants are produced from the same data:
  - the full wide graph (1020x184) with per-day contribution counts in each cell
  - a compact heatmap copy (<=700x220, no per-cell numbers) for tight slots
"""

import argparse
import json
import math
import sys
from datetime import datetime
from html import escape
from pathlib import Path


DEFAULT_INPUT = Path(__file__).parent.parent / "data" / "github-contributions.json"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "assets" / "github-contribution-graph.svg"

TITLE_TEXT = "ceilf6's Github Contribution"
BACKGROUND = "#1a1b27"
TITLE = "#70a5fd"
TEXT = "#38bdae"
MUTED = "#565f89"
CELL_TEXT = "#1a1b27"
LEVEL_COLORS = ["#202a3d", "#24515f", "#38bdae", "#70a5fd", "#bf91f3"]

# Full wide graph: fixed canvas, grid centered, per-day counts printed in cells.
MAIN_LAYOUT = {
    "cell": 16,
    "gap": 3,
    "margin_x": 22,
    "title_y": 30,
    "title_size": 22,
    "meta_size": 14,
    "graph_y": 42,
    "show_counts": True,
    "width": 1020,
    "height": 184,
    "bottom_margin": 0,
}

# Compact copy: width/height fit the content and stay within the 700x220 budget.
# 53 weeks at cell=10/gap=2 -> 634px grid -> 682x142 canvas. Numbers are dropped
# because they are illegible at this cell size; the heatmap colors carry the read.
COMPACT_LAYOUT = {
    "cell": 10,
    "gap": 2,
    "margin_x": 24,
    "title_y": 28,
    "title_size": 15,
    "meta_size": 11,
    "graph_y": 44,
    "show_counts": False,
    "width": None,
    "height": None,
    "bottom_margin": 16,
}


def load_data(path):
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_days(data):
    days = []
    for week in data.get("weeks", []):
        for day in week.get("days", []):
            days.append(
                {
                    "date": day["date"],
                    "contribution_count": int(day.get("contribution_count", 0)),
                }
            )
    return sorted(days, key=lambda day: day["date"])


def group_days_by_week(days):
    weeks = []
    current_week = None
    current_days = []
    for day in days:
        date = datetime.fromisoformat(day["date"]).date()
        github_weekday = (date.weekday() + 1) % 7
        first_day = date.toordinal() - github_weekday
        if current_week is None:
            current_week = first_day
        if first_day != current_week:
            weeks.append(current_days)
            current_days = []
            current_week = first_day
        current_days.append(day)
    if current_days:
        weeks.append(current_days)
    return weeks[-53:]


def color_for_count(count, max_count):
    if count <= 0:
        return LEVEL_COLORS[0]
    if max_count <= 1:
        return LEVEL_COLORS[1]
    ratio = math.log(count + 1) / math.log(max_count + 1)
    level = min(4, max(1, math.ceil(ratio * 4)))
    return LEVEL_COLORS[level]


def format_cell_count(value):
    return str(value)


def cell_text_size(value):
    if value >= 10000:
        return "4.8px"
    if value >= 1000:
        return "5.9px"
    if value >= 100:
        return "6.7px"
    return "8px"


def render_svg(data, layout):
    days = flatten_days(data)
    if not days:
        raise ValueError("No contribution days found")

    max_count = max(day["contribution_count"] for day in days)
    active_days = sum(1 for day in days if day["contribution_count"] > 0)
    weeks = group_days_by_week(days)

    cell = layout["cell"]
    gap = layout["gap"]
    margin_x = layout["margin_x"]
    graph_y = layout["graph_y"]
    show_counts = layout["show_counts"]

    graph_width = len(weeks) * cell + max(0, len(weeks) - 1) * gap
    graph_height = 7 * cell + 6 * gap
    width = layout["width"] or graph_width + 2 * margin_x
    height = layout["height"] or graph_y + graph_height + layout["bottom_margin"]
    graph_x = max(6, (width - graph_width) // 2)

    day_cells = []
    for week_index, week in enumerate(weeks):
        for day in week:
            date = datetime.fromisoformat(day["date"]).date()
            github_weekday = (date.weekday() + 1) % 7
            x = graph_x + week_index * (cell + gap)
            y = graph_y + github_weekday * (cell + gap)
            count = day["contribution_count"]
            color = color_for_count(count, max_count)
            label = escape(f'{count} contributions on {day["date"]}')
            markup = (
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}">'
                f"<title>{label}</title></rect>"
            )
            if show_counts:
                text_size = cell_text_size(count)
                markup += (
                    f'<text x="{x + cell / 2}" y="{y + cell / 2 + 2.4}" text-anchor="middle" '
                    f'style="font-size: {text_size}; font-weight: 800; fill: {CELL_TEXT}; pointer-events: none;">'
                    f"{escape(format_cell_count(count))}</text>"
                )
            day_cells.append(markup)

    title_size = layout["title_size"]
    meta_size = layout["meta_size"]
    title_y = layout["title_y"]
    meta_x = width - margin_x

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
    <title id="title">{TITLE_TEXT}</title>
    <desc id="desc">Daily contribution counts rendered as a heatmap grid with {active_days} active days.</desc>
    <style>
        * {{
            font-family: 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif;
        }}
    </style>
    <rect x="1" y="1" rx="5" ry="5" width="{width - 2}" height="{height - 2}" stroke="{BACKGROUND}" stroke-width="1" fill="{BACKGROUND}" />
    <text x="{margin_x}" y="{title_y}" style="font-size: {title_size}px; fill: {TITLE};">{TITLE_TEXT}</text>
    <text x="{meta_x}" y="{title_y}" text-anchor="end" style="font-size: {meta_size}px; fill: {TEXT};">active {active_days} days</text>
    {''.join(day_cells)}
</svg>'''


def compact_path_for(output):
    return output.with_name(f"{output.stem}-compact{output.suffix}")


def build_parser():
    parser = argparse.ArgumentParser(description="Generate GitHub contribution graph SVGs.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--compact-output",
        type=Path,
        default=None,
        help="Path for the compact (<=700x220) copy. Defaults to '<output>-compact.svg'.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    try:
        data = load_data(args.input)
        targets = [
            (args.output, MAIN_LAYOUT),
            (args.compact_output or compact_path_for(args.output), COMPACT_LAYOUT),
        ]
        for path, layout in targets:
            svg = render_svg(data, layout)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg, encoding="utf-8")
            print(f"GitHub contribution graph written to {path}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
