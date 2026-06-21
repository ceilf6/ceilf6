# Hugging Face Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add a daily refreshed Hugging Face profile card and arrange the README cards as a 2×2 grid.

**Architecture:** A dedicated Python script will fetch and validate the five public profile-overview totals before atomically writing data/huggingface-stats.json. The existing SVG generator will consume that repository-owned data to create assets/huggingface-card.svg; the existing daily workflow will fetch before rendering. README markup will use a two-row table so each requested pair occupies half of the available width.

**Tech Stack:** Python 3.11 (requests, argparse, json, tempfile), inline SVG, Node.js built-in test runner, GitHub Actions.

---

## File structure

- Create: scripts/fetch-huggingface-stats.py — downloads, validates, and atomically writes overview totals.
- Modify: scripts/generate-svg-cards.py — adds the deterministic Hugging Face SVG renderer.
- Create: data/huggingface-stats.json — committed current overview snapshot.
- Create: assets/huggingface-card.svg — committed generated 340×200 card.
- Keep and commit: svg/hugging_face_high_contrast.svg — supplied source icon.
- Modify: README.md — ordered 2×2 card table and Hugging Face profile link.
- Modify: .github/workflows/update-stats-schedule.yml — runs the new fetch before the shared generator.
- Create: tests/huggingface-card.test.mjs — fetch, renderer, README, asset, and workflow regressions.

### Task 1: Hugging Face overview fetcher

**Files:**
- Create: tests/huggingface-card.test.mjs
- Create: scripts/fetch-huggingface-stats.py

- [x] **Step 1: Write the failing fetcher tests**

Create tests/huggingface-card.test.mjs with this executable test code:

~~~
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const repoRoot = new URL("../", import.meta.url);
const fetchScript = new URL("../scripts/fetch-huggingface-stats.py", import.meta.url);
const validOverview = {
  numFollowers: 12,
  numLikes: 34,
  numModels: 5,
  numDatasets: 6,
  numSpaces: 7,
};

function runFetcher(source, existingOutput) {
  const dir = mkdtempSync(join(tmpdir(), "huggingface-card-"));
  const input = join(dir, "overview.json");
  const output = join(dir, "stats.json");
  writeFileSync(input, source);
  if (existingOutput !== undefined) writeFileSync(output, existingOutput);
  const result = spawnSync(
    "python3",
    [fetchScript.pathname, "--input", input, "--output", output],
    { cwd: repoRoot, encoding: "utf8" },
  );
  return { result, output };
}

test("fetcher writes the five required Hugging Face overview totals", () => {
  const { result, output } = runFetcher(JSON.stringify(validOverview));
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(readFileSync(output, "utf8")), validOverview);
});

test("fetcher rejects malformed, incomplete, and invalid totals without replacing output", () => {
  const invalidInputs = [
    "not-json",
    JSON.stringify({ ...validOverview, numLikes: undefined }),
    JSON.stringify({ ...validOverview, numModels: -1 }),
    JSON.stringify({ ...validOverview, numSpaces: "7" }),
  ];
  for (const source of invalidInputs) {
    const { result, output } = runFetcher(source, "existing output");
    assert.notEqual(result.status, 0, result.stderr);
    assert.equal(readFileSync(output, "utf8"), "existing output");
  }
  const { result, output } = runFetcher("not-json");
  assert.notEqual(result.status, 0, result.stderr);
  assert.equal(existsSync(output), false);
});
~~~

- [x] **Step 2: Run the test to verify it fails**

Run:

~~~
node --test tests/huggingface-card.test.mjs
~~~

Expected: FAIL because scripts/fetch-huggingface-stats.py does not exist.

- [x] **Step 3: Implement the minimal fetcher**

Create scripts/fetch-huggingface-stats.py with this complete implementation:

~~~
#!/usr/bin/env python3
"""Fetch the public Hugging Face profile overview for ceilf6."""

import argparse
import json
import os
import sys
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
            raise ValueError("Hugging Face overview has invalid " + field)
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
        write_atomically(args.output, parse_overview(load_source(args.input, args.url)))
        print("Hugging Face stats written to " + str(args.output))
        return 0
    except Exception as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
~~~

- [x] **Step 4: Run the test to verify it passes**

Run:

~~~
node --test tests/huggingface-card.test.mjs
~~~

Expected: the two fetcher tests PASS.

### Task 2: Self-contained SVG renderer

**Files:**
- Modify: tests/huggingface-card.test.mjs
- Modify: scripts/generate-svg-cards.py
- Create: data/huggingface-stats.json
- Create: assets/huggingface-card.svg
- Keep and commit: svg/hugging_face_high_contrast.svg

- [x] **Step 1: Add a failing renderer test**

Append this complete test:

~~~
const generatorScript = new URL("../scripts/generate-svg-cards.py", import.meta.url);

test("renderer creates the 340×200 card with five totals and an embedded mark", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "import importlib.util, json, sys",
        "spec = importlib.util.spec_from_file_location('cards', sys.argv[1])",
        "cards = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(cards)",
        "print(cards.generate_huggingface_card(json.loads(sys.argv[2])))",
      ].join("; "),
      generatorScript.pathname,
      JSON.stringify(validOverview),
    ],
    { cwd: repoRoot, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  for (const value of [
    'width="340"', 'height="200"', 'viewBox="0 0 340 200"',
    ">Hugging Face<", ">Followers:<", ">Likes:<", ">Models:<", ">Datasets:<", ">Spaces:<",
    ">12<", ">34<", ">5<", ">6<", ">7<", 'data-hugging-face-mark="true"',
  ]) assert.match(result.stdout, new RegExp(value));
});
~~~

- [x] **Step 2: Run the test to verify it fails**

Run:

~~~
node --test tests/huggingface-card.test.mjs
~~~

Expected: FAIL because generate_huggingface_card is not defined.

- [x] **Step 3: Implement the renderer**

Add generate_huggingface_card(stats) before main in scripts/generate-svg-cards.py. Its SVG must have width=340, height=200, viewBox="0 0 340 200", a Hugging Face title, and five 14px rows using format_number for stats["numFollowers"], stats["numLikes"], stats["numModels"], stats["numDatasets"], and stats["numSpaces"]. Preserve the Blog card's text positions and Tokyo Night colours: title #70a5fd, label/value #38bdae, icons #bf91f3, and background #1a1b27. Reuse the Blog card person and star paths, then add similarly sized purple inline paths for Models, Datasets, and Spaces.

Embed the supplied Hugging Face SVG paths rather than linking to the source file:

~~~
<g transform="translate(220,20) scale(0.08)" data-hugging-face-mark="true">
  <!-- copy the three path elements from svg/hugging_face_high_contrast.svg here -->
</g>
~~~

In main, after the current Vlog block, add this complete input/output block:

~~~
    huggingface_stats_file = Path(__file__).parent.parent / "data" / "huggingface-stats.json"
    if huggingface_stats_file.exists():
        with open(huggingface_stats_file, "r", encoding="utf-8") as handle:
            huggingface_stats = json.load(handle)
        huggingface_svg_file = Path(__file__).parent.parent / "assets" / "huggingface-card.svg"
        with open(huggingface_svg_file, "w", encoding="utf-8") as handle:
            handle.write(generate_huggingface_card(huggingface_stats))
        print("Hugging Face card generated successfully!")
~~~

Generate committed data and SVG assets with:

~~~
python scripts/fetch-huggingface-stats.py
python scripts/generate-svg-cards.py
~~~

- [x] **Step 4: Run the test to verify it passes**

Run:

~~~
node --test tests/huggingface-card.test.mjs
~~~

Expected: all three focused tests PASS.

### Task 3: README layout and daily workflow

**Files:**
- Modify: tests/huggingface-card.test.mjs
- Modify: README.md:4-6
- Modify: .github/workflows/update-stats-schedule.yml:38-44

- [x] **Step 1: Add a failing integration test**

Append this complete test:

~~~
test("README and daily workflow publish the ordered two-by-two card layout", () => {
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  const workflow = readFileSync(
    new URL("../.github/workflows/update-stats-schedule.yml", import.meta.url),
    "utf8",
  );
  const generatedCard = new URL("../assets/huggingface-card.svg", import.meta.url);
  const cards = [
    "./assets/github-stats-card.svg",
    "./assets/huggingface-card.svg",
    "./assets/vlog-card.svg",
    "./assets/blog-card.svg",
  ];
  let position = -1;
  for (const card of cards) {
    const next = readme.indexOf(card);
    assert.ok(next > position, card + " is not in the required order");
    position = next;
  }
  assert.match(readme, /href="https:\/\/huggingface\.co\/ceilf6"/);
  assert.match(readme, /<td width="50%" align="center">/);
  assert.match(workflow, /- name: Fetch Hugging Face stats\n\s+run: python scripts\/fetch-huggingface-stats\.py/);
  assert.equal(existsSync(generatedCard), true);
});
~~~

- [x] **Step 2: Run the test to verify it fails**

Run:

~~~
node --test tests/huggingface-card.test.mjs
~~~

Expected: FAIL because the current README, workflow, and generated asset lack Hugging Face integration.

- [x] **Step 3: Update the README and workflow minimally**

Replace the first README card div with:

~~~
<table>
  <tr>
    <td width="50%" align="center"><a href="https://ceilf6.github.io/ceilf6/" target="_blank"><img width="100%" src="./assets/github-stats-card.svg" /></a></td>
    <td width="50%" align="center"><a href="https://huggingface.co/ceilf6" target="_blank"><img width="100%" src="./assets/huggingface-card.svg" /></a></td>
  </tr>
  <tr>
    <td width="50%" align="center"><a href="https://ceilf6.github.io/ceilf6/vlog.html" target="_blank"><img width="100%" src="./assets/vlog-card.svg" /></a></td>
    <td width="50%" align="center"><a href="https://blog.csdn.net/2301_78856868" target="_blank"><img width="100%" src="./assets/blog-card.svg" /></a></td>
  </tr>
</table>
~~~

Insert this workflow step immediately after Fetch GitHub stats card and before Generate SVG cards:

~~~
      - name: Fetch Hugging Face stats
        run: python scripts/fetch-huggingface-stats.py
~~~

- [x] **Step 4: Run the test to verify it passes**

Run:

~~~
node --test tests/huggingface-card.test.mjs
~~~

Expected: all four focused tests PASS.

### Task 4: Full verification and commit

**Files:**
- Modify: README.md
- Modify: .github/workflows/update-stats-schedule.yml
- Modify: scripts/generate-svg-cards.py
- Create: scripts/fetch-huggingface-stats.py, data/huggingface-stats.json, assets/huggingface-card.svg, tests/huggingface-card.test.mjs
- Keep and commit: svg/hugging_face_high_contrast.svg

- [x] **Step 1: Regenerate from a current public overview**

Run:

~~~
python scripts/fetch-huggingface-stats.py
python scripts/generate-svg-cards.py
~~~

Expected: data/huggingface-stats.json and assets/huggingface-card.svg are refreshed.

- [x] **Step 2: Run complete verification**

Run:

~~~
node --test tests/*.mjs
git diff --check
~~~

Expected: every Node test passes and git diff --check emits no output.

- [x] **Step 3: Inspect scope before committing**

Run:

~~~
git status --short
git diff -- README.md .github/workflows/update-stats-schedule.yml scripts/generate-svg-cards.py scripts/fetch-huggingface-stats.py data/huggingface-stats.json assets/huggingface-card.svg tests/huggingface-card.test.mjs svg/hugging_face_high_contrast.svg
~~~

Expected: only the plan's files and the already committed design document are affected.

- [x] **Step 4: Commit the feature**

Run:

~~~
git add README.md .github/workflows/update-stats-schedule.yml scripts/generate-svg-cards.py scripts/fetch-huggingface-stats.py data/huggingface-stats.json assets/huggingface-card.svg tests/huggingface-card.test.mjs svg/hugging_face_high_contrast.svg docs/superpowers/plans/2026-06-21-hugging-face-card.md
git commit -m "feat: add hugging face profile card"
~~~

Expected: one feature commit with the generated card, daily refresh wiring, source data, and regression tests.
