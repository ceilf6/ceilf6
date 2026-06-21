import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const repoRoot = new URL("../", import.meta.url);
const fetchScript = new URL("../scripts/fetch-huggingface-stats.py", import.meta.url);
const generatorScript = new URL("../scripts/generate-svg-cards.py", import.meta.url);
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
    'width="340"',
    'height="200"',
    'viewBox="0 0 340 200"',
    ">Hugging Face<",
    ">Followers:<",
    ">Likes:<",
    ">Models:<",
    ">Datasets:<",
    ">Spaces:<",
    ">12<",
    ">34<",
    ">5<",
    ">6<",
    ">7<",
    'data-hugging-face-mark="true"',
  ]) {
    assert.match(result.stdout, new RegExp(value));
  }
  assert.match(
    result.stdout,
    /<g transform="translate\(220,67\) scale\(0\.08\)" data-hugging-face-mark="true">/,
  );
});

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
    assert.ok(next > position, `${card} is not in the required order`);
    position = next;
  }
  assert.match(readme, /href="https:\/\/huggingface\.co\/ceilf6"/);
  assert.match(readme, /<td width="50%" align="center">/);
  assert.match(
    workflow,
    /- name: Fetch Hugging Face stats\n\s+run: python scripts\/fetch-huggingface-stats\.py/,
  );
  assert.equal(existsSync(generatedCard), true);
});
