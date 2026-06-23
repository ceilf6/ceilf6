#!/usr/bin/env python3
"""Fetch the upstream GitHub stats SVG and replace its GitHub mark with an S badge."""

import argparse
import os
import sys
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen


DEFAULT_URL = (
    "https://github-profile-summary-cards.vercel.app/api/cards/stats?"
    "username=ceilf6&theme=tokyonight"
)
DEFAULT_OUTPUT = Path(__file__).parent.parent / "assets" / "github-stats-card.svg"
RIGHT_SIDE_TRANSFORM = "translate(220,20)"
LEFT_SIDE_TRANSFORM = "translate(30,20)"
EXPECTED_LABELS = (
    "Total Stars:",
    f"{datetime.now(timezone.utc).year} Commits:",
    "Total PRs:",
    "Total Issues:",
    "Contributed to:",
)
OUTPUT_TITLE = "ceilf6's Github Stats"
OUTPUT_TITLE_STYLE = "font-size: 18px; fill: #70a5fd;"


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def qualified_tag(root, name):
    if root.tag.startswith("{"):
        return f"{root.tag.split('}', 1)[0]}}}{name}"
    return name


def register_default_namespace(root):
    if root.tag.startswith("{"):
        ElementTree.register_namespace("", root.tag[1:].split("}", 1)[0])


def load_source(input_path, url):
    if input_path is not None:
        return input_path.read_bytes()

    request = Request(url, headers={"User-Agent": "ceilf6-github-stats-card"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def find_right_side_group(root):
    matches = []
    for parent in root.iter():
        for child in parent:
            if local_name(child.tag) == "g" and child.get("transform") == RIGHT_SIDE_TRANSFORM:
                matches.append((parent, child))
    if len(matches) != 1:
        raise ValueError("Could not find the expected right-side group")
    return matches[0]


def text_values(element):
    return {
        "".join(child.itertext()).strip()
        for child in element.iter()
        if local_name(child.tag) == "text"
    }


def validate_card(root):
    if local_name(root.tag) != "svg":
        raise ValueError("Upstream card root is not an SVG")

    dimensions = (root.get("width"), root.get("height"), root.get("viewBox"))
    if dimensions != ("340", "200", "0 0 340 200"):
        raise ValueError("Upstream card dimensions do not match the expected 340x200 layout")

    title_matches = [
        element
        for element in root.iter()
        if local_name(element.tag) == "text" and "".join(element.itertext()).strip() == "Stats"
    ]
    if len(title_matches) != 1:
        raise ValueError("Upstream card title does not match the expected Stats title")

    label_groups = [
        element
        for element in root.iter()
        if local_name(element.tag) == "g" and element.get("transform") == LEFT_SIDE_TRANSFORM
    ]
    if len(label_groups) != 1 or not set(EXPECTED_LABELS).issubset(text_values(label_groups[0])):
        raise ValueError("Upstream card field labels do not match the expected stats layout")

    parent, target = find_right_side_group(root)
    if list(parent)[-1] is not target:
        raise ValueError("Upstream card right-side group is not the final group")
    return title_matches[0], parent, target


def replace_title(title):
    title.text = OUTPUT_TITLE
    title.set("style", OUTPUT_TITLE_STYLE)


def replace_right_side_group(root, parent, target):
    replacement = ElementTree.Element(
        qualified_tag(root, "g"), {"transform": RIGHT_SIDE_TRANSFORM}
    )
    ElementTree.SubElement(
        replacement,
        qualified_tag(root, "circle"),
        {
            "cx": "48",
            "cy": "48",
            "r": "40",
            "fill": "none",
            "stroke": "#bf91f3",
            "stroke-width": "6",
        },
    )
    badge_text = ElementTree.SubElement(
        replacement,
        qualified_tag(root, "text"),
        {
            # Center the badge glyph on the ring's exact geometric center (cx=48, cy=48).
            # We borrow github-readme-stats' rendering technique -- 800-weight Segoe UI,
            # plus BOTH alignment-baseline and dominant-baseline (different SVG renderers,
            # GitHub's included, honor different ones) -- but NOT its anchor coordinates:
            # grs anchors the letter at (x=-5, y=3) against a ring centered at (cx=-10,
            # cy=8), i.e. +5 right / -5 up from center, which is visibly off at this
            # circle size. text-anchor=middle + both central baselines put the glyph's
            # optical center on (48, 48) with no manual nudges, so it cannot drift.
            "x": "48",
            "y": "48",
            "text-anchor": "middle",
            "alignment-baseline": "central",
            "dominant-baseline": "central",
            "style": "font-family: 'Segoe UI', Ubuntu, Sans-Serif; font-size: 24px; font-weight: 800; fill: #ffffff;",
        },
    )
    badge_text.text = "S"

    parent.insert(list(parent).index(target), replacement)
    parent.remove(target)


def write_atomically(output, content):
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    try:
        os.replace(temporary_path, output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Use a local upstream SVG instead of downloading it.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Upstream stats card URL.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        root = ElementTree.fromstring(load_source(args.input, args.url))
        title, parent, target = validate_card(root)
        replace_title(title)
        replace_right_side_group(root, parent, target)
        register_default_namespace(root)
        write_atomically(args.output, ElementTree.tostring(root, encoding="unicode"))
        print(f"GitHub stats card written to {args.output}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
