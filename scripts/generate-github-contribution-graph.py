#!/usr/bin/env python3
"""
Generate a Tokyo Night GitHub contribution graph SVG.
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

WIDTH = 1020
HEIGHT = 184
BACKGROUND = "#1a1b27"
TITLE = "#70a5fd"
TEXT = "#38bdae"
MUTED = "#565f89"
CELL_TEXT = "#1a1b27"
LEVEL_COLORS = ["#202a3d", "#24515f", "#38bdae", "#70a5fd", "#bf91f3"]


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


def render_svg(data):
    days = flatten_days(data)
    if not days:
        raise ValueError("No contribution days found")

    max_count = max(day["contribution_count"] for day in days)
    active_days = sum(1 for day in days if day["contribution_count"] > 0)
    weeks = group_days_by_week(days)

    cell = 16
    gap = 3
    graph_width = len(weeks) * cell + max(0, len(weeks) - 1) * gap
    graph_height = 7 * cell + 6 * gap
    graph_x = max(6, (WIDTH - graph_width) // 2)
    graph_y = 42
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
            text_size = cell_text_size(count)
            day_cells.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}">'
                f"<title>{label}</title></rect>"
                f'<text x="{x + cell / 2}" y="{y + cell / 2 + 2.4}" text-anchor="middle" '
                f'style="font-size: {text_size}; font-weight: 800; fill: {CELL_TEXT}; pointer-events: none;">'
                f"{escape(format_cell_count(count))}</text>"
            )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
    <title id="title">GitHub Contribution Graph</title>
    <desc id="desc">Daily contribution counts rendered as a heatmap grid with {active_days} active days.</desc>
    <style>
        * {{
            font-family: 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif;
        }}
    </style>
    <rect x="1" y="1" rx="5" ry="5" width="{WIDTH - 2}" height="{HEIGHT - 2}" stroke="{BACKGROUND}" stroke-width="1" fill="{BACKGROUND}" />
    <text x="22" y="30" style="font-size: 22px; fill: {TITLE};">GitHub Contribution Graph</text>
    <text x="998" y="30" text-anchor="end" style="font-size: 14px; fill: {TEXT};">active {active_days} days</text>
    {''.join(day_cells)}
</svg>'''


def build_parser():
    parser = argparse.ArgumentParser(description="Generate GitHub contribution graph SVG.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        data = load_data(args.input)
        svg = render_svg(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(svg, encoding="utf-8")
        print(f"GitHub contribution graph written to {args.output}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
