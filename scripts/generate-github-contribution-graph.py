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

WIDTH = 700
HEIGHT = 200
BACKGROUND = "#1a1b27"
TITLE = "#70a5fd"
TEXT = "#38bdae"
ACCENT = "#bf91f3"
MUTED = "#565f89"
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


def format_number(value):
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return f"{value:,}"


def format_date_range(start, end):
    if not start or not end:
        return "last 12 months"
    return f"{start} to {end}"


def render_svg(data):
    days = flatten_days(data)
    if not days:
        raise ValueError("No contribution days found")

    username = escape(str(data.get("username", "github")))
    total = int(data.get("total_contributions", sum(day["contribution_count"] for day in days)))
    end = str(data.get("to", days[-1]["date"]))
    start = str(data.get("from", days[0]["date"]))
    source = escape(str(data.get("source", "github")))
    generated_at = escape(str(data.get("generated_at", "")))
    max_day = max(days, key=lambda day: day["contribution_count"])
    max_count = max(day["contribution_count"] for day in days)
    active_days = sum(1 for day in days if day["contribution_count"] > 0)
    weeks = group_days_by_week(days)

    graph_x = 32
    graph_y = 78
    cell = 8
    gap = 3
    month_labels = []
    seen_months = set()
    day_rects = []

    for week_index, week in enumerate(weeks):
        for day in week:
            date = datetime.fromisoformat(day["date"]).date()
            github_weekday = (date.weekday() + 1) % 7
            x = graph_x + week_index * (cell + gap)
            y = graph_y + github_weekday * (cell + gap)
            count = day["contribution_count"]
            color = color_for_count(count, max_count)
            label = escape(f'{count} contributions on {day["date"]}')
            day_rects.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}">'
                f"<title>{label}</title></rect>"
            )
            month_key = (date.year, date.month)
            if date.day <= 7 and month_key not in seen_months:
                seen_months.add(month_key)
                month_labels.append(
                    f'<text x="{x}" y="70" style="font-size: 9px; fill: {MUTED};">{date.strftime("%b")}</text>'
                )

    legend_x = 560
    legend_y = 168
    legend = []
    for index, color in enumerate(LEVEL_COLORS):
        x = legend_x + index * 15
        legend.append(f'<rect x="{x}" y="{legend_y}" width="8" height="8" rx="2" fill="{color}" />')

    subtitle = f"{username} · last 12 months"
    range_text = escape(format_date_range(start, end))
    generated_text = escape(generated_at.replace("T", " ").replace("Z", " UTC"))
    source_text = escape(source)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
    <title id="title">GitHub Contribution Graph</title>
    <desc id="desc">{username} contribution graph from {escape(start)} to {escape(end)}</desc>
    <style>
        * {{
            font-family: 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif;
        }}
    </style>
    <rect x="1" y="1" rx="5" ry="5" width="{WIDTH - 2}" height="{HEIGHT - 2}" stroke="{BACKGROUND}" stroke-width="1" fill="{BACKGROUND}" />
    <text x="30" y="40" style="font-size: 22px; fill: {TITLE};">GitHub Contribution Graph</text>
    <text x="30" y="60" style="font-size: 12px; fill: {TEXT};">{subtitle}</text>
    <text x="535" y="35" text-anchor="start" style="font-size: 13px; fill: {ACCENT};">{format_number(total)} contributions</text>
    <text x="535" y="53" text-anchor="start" style="font-size: 11px; fill: {TEXT};">active {active_days} days · best {max_day["contribution_count"]}</text>
    {''.join(month_labels)}
    {''.join(day_rects)}
    <text x="32" y="168" style="font-size: 10px; fill: {MUTED};">{range_text}</text>
    <text x="32" y="184" style="font-size: 10px; fill: {MUTED};">generated {generated_text} · {source_text}</text>
    <text x="500" y="176" style="font-size: 9px; fill: {MUTED};">Less</text>
    {''.join(legend)}
    <text x="638" y="176" style="font-size: 9px; fill: {MUTED};">More</text>
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
