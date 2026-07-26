#!/usr/bin/env python3
"""
Fetch GitHub contribution calendar data for the profile README.
"""

import argparse
import html
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_USERNAME = "ceilf6"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "github-contributions.json"
GRAPHQL_ENDPOINT = "https://api.github.com/graphql"


def parse_utc_datetime(value):
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def format_utc_datetime(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def determine_window(now=None, days=365, guard_minutes=30):
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    start_of_today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    if now - start_of_today < timedelta(minutes=guard_minutes):
        end_date = now.date() - timedelta(days=1)
        to_datetime = datetime.combine(end_date, time.max, tzinfo=timezone.utc).replace(microsecond=0)
    else:
        end_date = now.date()
        to_datetime = now

    start_date = end_date - timedelta(days=days - 1)
    from_datetime = datetime.combine(start_date, time.min, tzinfo=timezone.utc)

    return {
        "from_date": start_date.isoformat(),
        "to_date": end_date.isoformat(),
        "from_datetime": format_utc_datetime(from_datetime),
        "to_datetime": format_utc_datetime(to_datetime),
    }


def graphql_query(username, token, window):
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Missing Python dependency: requests") from exc

    query = """
    query ProfileContributionCalendar($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              firstDay
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    response = requests.post(
        GRAPHQL_ENDPOINT,
        json={
            "query": query,
            "variables": {
                "login": username,
                "from": window["from_datetime"],
                "to": window["to_datetime"],
            },
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ceilf6-readme-contribution-graph",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        messages = "; ".join(error.get("message", "unknown error") for error in payload["errors"])
        raise RuntimeError(f"GitHub GraphQL API returned errors: {messages}")
    return payload


def normalize_graphql_payload(payload, username, window):
    try:
        calendar = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    except (TypeError, KeyError) as exc:
        raise RuntimeError("GitHub GraphQL response is missing contributionCalendar") from exc

    weeks = []
    for week in calendar.get("weeks", []):
        days = []
        for day in week.get("contributionDays", []):
            days.append(
                {
                    "date": day["date"],
                    "contribution_count": int(day.get("contributionCount", 0)),
                }
            )
        weeks.append({"first_day": week.get("firstDay"), "days": days})

    return {
        "username": username,
        "source": "github-graphql",
        "generated_at": format_utc_datetime(datetime.now(timezone.utc)),
        "from": window["from_date"],
        "to": window["to_date"],
        "total_contributions": int(calendar.get("totalContributions", 0)),
        "weeks": weeks,
    }


def parse_attrs(tag):
    return dict(re.findall(r'([a-zA-Z0-9_-]+)="([^"]*)"', tag))


def parse_tooltip_count(text):
    clean = html.unescape(re.sub(r"\s+", " ", text)).strip()
    if clean.startswith("No contribution"):
        return 0
    match = re.search(r"([\d,]+)\s+contributions?", clean)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def fetch_public_contributions(username, window):
    url = f"https://github.com/users/{username}/contributions"
    request = Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": "ceilf6-readme-contribution-graph",
        },
    )
    with urlopen(request, timeout=20) as response:
        content = response.read().decode("utf-8")

    total_match = re.search(r"([\d,]+)\s+contributions\s+in the last year", content)
    total = int(total_match.group(1).replace(",", "")) if total_match else 0

    day_pattern = re.compile(
        r"(<td\b(?=[^>]*ContributionCalendar-day)[^>]*></td>)\s*"
        r"<tool-tip\b[^>]*>(.*?)</tool-tip>",
        re.DOTALL,
    )
    start_date = datetime.fromisoformat(window["from_date"]).date()
    end_date = datetime.fromisoformat(window["to_date"]).date()
    grouped_days = defaultdict(list)

    for match in day_pattern.finditer(content):
        attrs = parse_attrs(match.group(1))
        raw_date = attrs.get("data-date")
        if not raw_date:
            continue
        day_date = datetime.fromisoformat(raw_date).date()
        if day_date < start_date or day_date > end_date:
            continue
        count = parse_tooltip_count(match.group(2))
        if count is None:
            count = int(attrs.get("data-level", 0))

        github_weekday = (day_date.weekday() + 1) % 7
        first_day = day_date - timedelta(days=github_weekday)
        grouped_days[first_day.isoformat()].append(
            {
                "date": day_date.isoformat(),
                "contribution_count": count,
            }
        )

    weeks = []
    for first_day in sorted(grouped_days):
        weeks.append(
            {
                "first_day": first_day,
                "days": sorted(grouped_days[first_day], key=lambda day: day["date"]),
            }
        )

    if weeks:
        total = sum(day["contribution_count"] for week in weeks for day in week["days"])

    return {
        "username": username,
        "source": "github-public-contributions-page",
        "generated_at": format_utc_datetime(datetime.now(timezone.utc)),
        "from": window["from_date"],
        "to": window["to_date"],
        "total_contributions": total,
        "weeks": weeks,
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser():
    parser = argparse.ArgumentParser(description="Fetch GitHub contribution calendar data.")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--now", help="UTC timestamp for deterministic window calculation.")
    parser.add_argument("--guard-minutes", type=int, default=30)
    parser.add_argument("--print-window", action="store_true")
    parser.add_argument("--public-fallback", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    now = parse_utc_datetime(args.now) if args.now else None
    window = determine_window(now=now, guard_minutes=args.guard_minutes)

    if args.print_window:
        print(json.dumps(window, ensure_ascii=False))
        return 0

    token = os.environ.get("GH_PROFILE_TOKEN", "").strip()
    try:
        if token:
            payload = graphql_query(args.username, token, window)
            data = normalize_graphql_payload(payload, args.username, window)
        elif args.public_fallback:
            data = fetch_public_contributions(args.username, window)
        else:
            raise RuntimeError("GH_PROFILE_TOKEN is required. Use --public-fallback only for local bootstrap.")

        if not any(week.get("days") for week in data["weeks"]):
            raise RuntimeError("No contribution days found in fetched data")

        write_json(args.output, data)
        print(f"GitHub contribution data written to {args.output}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
