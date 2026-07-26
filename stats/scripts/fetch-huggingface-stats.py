#!/usr/bin/env python3
"""Fetch the public Hugging Face profile overview for ceilf6."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests


DEFAULT_URL = "https://huggingface.co/api/users/ceilf6/overview"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "huggingface-stats.json"
FIELDS = ("numFollowers", "numLikes", "numModels", "numDatasets", "numSpaces")


def load_source(input_path, url):
    if input_path is not None:
        return input_path.read_text(encoding="utf-8")

    response = requests.get(
        url,
        headers={"User-Agent": "ceilf6-huggingface-card"},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def parse_overview(source):
    overview = json.loads(source)
    if not isinstance(overview, dict):
        raise ValueError("Hugging Face overview must be a JSON object")

    stats = {}
    for field in FIELDS:
        value = overview.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Hugging Face overview has invalid {field}")
        stats[field] = value
    return stats


def write_atomically(output, stats):
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        json.dump(stats, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    try:
        os.replace(temporary_path, output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Use a local overview JSON instead of downloading it.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        stats = parse_overview(load_source(args.input, args.url))
        stats["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_atomically(args.output, stats)
        print(f"Hugging Face stats written to {args.output}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
