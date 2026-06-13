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

test("fetcher requires GH_PROFILE_TOKEN unless public fallback is explicit", () => {
  const dir = mkdtempSync(join(tmpdir(), "github-contribution-fetch-missing-token-"));
  const output = join(dir, "contributions.json");
  const result = spawnSync(
    "python3",
    [
      fetchScript.pathname,
      "--output",
      output,
      "--now",
      "2026-06-13T23:50:00Z",
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        GH_PROFILE_TOKEN: "",
      },
    },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /GH_PROFILE_TOKEN is required/);
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
