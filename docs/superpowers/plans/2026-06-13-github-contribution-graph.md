# GitHub Contribution Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a self-generated GitHub contribution graph SVG to the README, styled like the existing Tokyo Night cards and updated by an independent daily workflow.

**Architecture:** Split the feature into a data fetcher, a deterministic SVG generator, README integration, and a dedicated GitHub Actions workflow. The CI path uses `GH_PROFILE_TOKEN`; a separate explicit `--public-fallback` mode exists only for local bootstrap when no token is available.

**Tech Stack:** Python 3.11, GitHub GraphQL API, GitHub Actions, SVG, Node `node:test` for repository verification.

---

## File Structure

- Create `scripts/fetch-github-contributions.py`: fetches contribution calendar data, computes the UTC cutoff window, writes `data/github-contributions.json`.
- Create `scripts/generate-github-contribution-graph.py`: reads contribution JSON and writes `assets/github-contribution-graph.svg`.
- Create `tests/github-contribution-graph.test.mjs`: verifies cutoff logic CLI and SVG generation behavior without network access.
- Create `.github/workflows/update-github-contribution-graph.yml`: independent daily workflow using `GH_PROFILE_TOKEN`.
- Modify `README.md`: insert the generated local SVG after the intro paragraph and before `我的一些探索`.
- Create `data/github-contributions.json` and `assets/github-contribution-graph.svg`: bootstrap artifacts generated locally with explicit public fallback if `GH_PROFILE_TOKEN` is absent.

## Task 1: Tests First

**Files:**
- Create: `tests/github-contribution-graph.test.mjs`

- [x] **Step 1: Write the failing test**

```js
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const repoRoot = new URL("../", import.meta.url);
const fetchScript = new URL("../scripts/fetch-github-contributions.py", import.meta.url);
const graphScript = new URL("../scripts/generate-github-contribution-graph.py", import.meta.url);

function runPython(script, args, options = {}) {
  return execFileSync("python3", [script.pathname, ...args], {
    cwd: repoRoot,
    encoding: "utf8",
    ...options,
  });
}

test("cutoff window hides the newly-started UTC day during the rollover guard", () => {
  const output = runPython(fetchScript, [
    "--print-window",
    "--now",
    "2026-06-13T00:05:00Z",
  ]);
  const window = JSON.parse(output);

  assert.equal(window.to_date, "2026-06-12");
  assert.equal(window.to_datetime, "2026-06-12T23:59:59Z");
});

test("cutoff window includes the current UTC day before rollover", () => {
  const output = runPython(fetchScript, [
    "--print-window",
    "--now",
    "2026-06-13T23:50:00Z",
  ]);
  const window = JSON.parse(output);

  assert.equal(window.to_date, "2026-06-13");
  assert.equal(window.to_datetime, "2026-06-13T23:50:00Z");
});

test("generator renders a Tokyo Night SVG from contribution data", () => {
  const dir = mkdtempSync(join(tmpdir(), "github-contribution-graph-"));
  const input = join(dir, "contributions.json");
  const output = join(dir, "graph.svg");

  writeFileSync(
    input,
    JSON.stringify({
      username: "ceilf6",
      source: "fixture",
      generated_at: "2026-06-13T23:50:00Z",
      from: "2026-06-07",
      to: "2026-06-13",
      total_contributions: 26,
      weeks: [
        {
          first_day: "2026-06-07",
          days: [
            { date: "2026-06-07", contribution_count: 0 },
            { date: "2026-06-08", contribution_count: 1 },
            { date: "2026-06-09", contribution_count: 3 },
            { date: "2026-06-10", contribution_count: 7 },
            { date: "2026-06-11", contribution_count: 15 },
          ],
        },
      ],
    }),
  );

  runPython(graphScript, ["--input", input, "--output", output]);
  const svg = readFileSync(output, "utf8");

  assert.match(svg, /GitHub Contribution Graph/);
  assert.match(svg, /ceilf6 · last 12 months/);
  assert.match(svg, /#1a1b27/);
  assert.match(svg, /#70a5fd/);
  assert.match(svg, /#38bdae/);
  assert.match(svg, /#bf91f3/);
  assert.doesNotMatch(svg, /#216e39/i);
});

test("generator rejects empty contribution data", () => {
  const dir = mkdtempSync(join(tmpdir(), "github-contribution-graph-empty-"));
  const input = join(dir, "contributions.json");
  const output = join(dir, "graph.svg");

  writeFileSync(
    input,
    JSON.stringify({
      username: "ceilf6",
      source: "fixture",
      generated_at: "2026-06-13T23:50:00Z",
      from: "2026-06-07",
      to: "2026-06-13",
      total_contributions: 0,
      weeks: [],
    }),
  );

  const result = spawnSync("python3", [graphScript.pathname, "--input", input, "--output", output], {
    cwd: repoRoot,
    encoding: "utf8",
  });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /No contribution days found/);
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `node --test tests/github-contribution-graph.test.mjs`

Expected: FAIL because `scripts/fetch-github-contributions.py` and `scripts/generate-github-contribution-graph.py` do not exist yet.

## Task 2: Fetcher Script

**Files:**
- Create: `scripts/fetch-github-contributions.py`

- [x] **Step 1: Implement the cutoff window, GraphQL fetch, and explicit public fallback**

Create a Python CLI with these behaviors:

- `--print-window --now <ISO>` prints the computed JSON window without requiring a token.
- Default mode requires `GH_PROFILE_TOKEN`.
- `--public-fallback` fetches `https://github.com/users/<username>/contributions` and parses public/anonymized aggregate HTML for local bootstrap only.
- Output schema uses `contribution_count` snake case.

- [x] **Step 2: Run cutoff tests**

Run: `node --test tests/github-contribution-graph.test.mjs`

Expected: generator tests still fail because the generator does not exist; cutoff tests pass.

## Task 3: SVG Generator

**Files:**
- Create: `scripts/generate-github-contribution-graph.py`

- [x] **Step 1: Implement deterministic Tokyo Night SVG rendering**

The generator must:

- fail on empty data
- render `700x200`
- use `#1a1b27`, `#70a5fd`, `#38bdae`, `#bf91f3`
- render the last 53 weeks at most
- escape user-controlled text
- avoid scripts, external assets, external fonts, and default GitHub green

- [x] **Step 2: Run graph tests**

Run: `node --test tests/github-contribution-graph.test.mjs`

Expected: PASS.

## Task 4: Bootstrap Data And README

**Files:**
- Create: `data/github-contributions.json`
- Create: `assets/github-contribution-graph.svg`
- Modify: `README.md`

- [x] **Step 1: Generate bootstrap artifacts**

If `GH_PROFILE_TOKEN` is set:

```bash
python3 scripts/fetch-github-contributions.py
python3 scripts/generate-github-contribution-graph.py
```

If `GH_PROFILE_TOKEN` is missing:

```bash
python3 scripts/fetch-github-contributions.py --public-fallback
python3 scripts/generate-github-contribution-graph.py
```

- [x] **Step 2: Insert the README image block**

Insert after the contact paragraph and before `<h2 align="center">`:

```html
<p align="center">
  <img src="./assets/github-contribution-graph.svg" width="100%" alt="GitHub Contribution Graph" />
</p>
```

- [x] **Step 3: Check generated files**

Run:

```bash
test -s data/github-contributions.json
test -s assets/github-contribution-graph.svg
rg -n "github-contribution-graph.svg" README.md
```

Expected: all commands pass.

## Task 5: Independent Workflow

**Files:**
- Create: `.github/workflows/update-github-contribution-graph.yml`

- [x] **Step 1: Add the independent daily workflow**

The workflow must:

- run on `cron: "50 23 * * *"`
- support `workflow_dispatch`
- use `secrets.GH_PROFILE_TOKEN`
- install only Python `requests`
- commit only when generated files changed

- [x] **Step 2: Verify workflow does not modify existing stats workflow**

Run:

```bash
git diff -- .github/workflows/update-stats-schedule.yml
```

Expected: no diff.

## Task 6: Full Verification

**Files:**
- Verify all touched files

- [x] **Step 1: Run repository tests**

Run: `node --test tests/*.mjs`

Expected: PASS.

- [x] **Step 2: Run generator manually**

Run:

```bash
python3 scripts/generate-github-contribution-graph.py
```

Expected: `assets/github-contribution-graph.svg` is regenerated without error.

- [x] **Step 3: Inspect git diff**

Run: `git diff --stat && git diff -- README.md .github/workflows/update-github-contribution-graph.yml scripts/fetch-github-contributions.py scripts/generate-github-contribution-graph.py tests/github-contribution-graph.test.mjs`

Expected: changes match the plan and do not include `.superpowers/`.
