import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const repoRoot = new URL("../", import.meta.url);
const script = new URL("../scripts/fetch-github-stats-card.py", import.meta.url);
const currentYear = new Date().getUTCFullYear();

const validUpstreamCard = `<svg xmlns="http://www.w3.org/2000/svg" width="340" height="200" viewBox="0 0 340 200">
  <style>* { font-family: Ubuntu; }</style>
  <rect x="1" y="1" width="338" height="198" fill="#1a1b27" />
  <text x="30" y="40">Stats</text>
  <g transform="translate(0,40)">
    <g transform="translate(30,20)">
      <text x="21" y="14">Total Stars:</text>
      <text x="21" y="39.2">${currentYear} Commits:</text>
      <text x="21" y="64.4">Total PRs:</text>
      <text x="21" y="89.6">Total Issues:</text>
      <text x="21" y="114.8">Contributed to:</text>
      <text x="130" y="14">42</text>
      <text x="130" y="39.2">1234</text>
      <text x="130" y="64.4">7</text>
      <text x="130" y="89.6">8</text>
      <text x="130" y="114.8">9</text>
    </g>
    <g transform="translate(220,20)"><path id="github-mark" /></g>
  </g>
</svg>`;

test("generator preserves upstream stats while replacing the GitHub group with an S badge", () => {
  const dir = mkdtempSync(join(tmpdir(), "github-stats-card-"));
  const input = join(dir, "upstream.svg");
  const output = join(dir, "stats.svg");
  writeFileSync(input, validUpstreamCard);

  const result = spawnSync("python3", [script.pathname, "--input", input, "--output", output], {
    cwd: repoRoot,
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr);
  const svg = readFileSync(output, "utf8");
  assert.match(svg, /width="340"/);
  assert.match(svg, /height="200"/);
  assert.match(svg, /viewBox="0 0 340 200"/);
  for (const value of [
    "ceilf6's Github Stats",
    "Total Stars:",
    `${currentYear} Commits:`,
    "Total PRs:",
    "Total Issues:",
    "Contributed to:",
    "42",
    "1234",
    "7",
    "8",
    "9",
  ]) {
    assert.match(svg, new RegExp(`>${value}<`));
  }
  assert.match(
    svg,
    /<text x="30" y="40" style="font-size: 18px; fill: #70a5fd;">ceilf6's Github Stats<\/text>/,
  );
  assert.doesNotMatch(svg, />Stats<\/text>/);
  assert.match(
    svg,
    /<circle(?=[^>]*cx="48")(?=[^>]*cy="48")(?=[^>]*r="40")(?=[^>]*fill="none")(?=[^>]*stroke="#bf91f3")(?=[^>]*stroke-width="6")[^>]*\/>/,
  );
  assert.match(
    svg,
    /<text[^>]*x="47"[^>]*y="58"[^>]*transform="translate\(-3\.76 0\) scale\(1\.08 1\)"[^>]*style="font-family: Arial; font-size: 24px; font-weight: 400; fill: #ffffff;">S<\/text>/,
  );
  assert.doesNotMatch(svg, /github-mark/);
});

test("generator rejects malformed or incompatible cards without publishing output", () => {
  const invalidCards = [
    ["non-SVG root", validUpstreamCard.replace("<svg", "<card").replace("</svg>", "</card>")],
    ["wrong width", validUpstreamCard.replace('width="340"', 'width="341"')],
    ["wrong height", validUpstreamCard.replace('height="200"', 'height="201"')],
    ["wrong viewBox", validUpstreamCard.replace('viewBox="0 0 340 200"', 'viewBox="0 0 341 200"')],
    ["missing title", validUpstreamCard.replace(">Stats<", ">Overview<")],
    ["missing field label", validUpstreamCard.replace("Total Stars:", "Stars:")],
    [
      "right-side group is not final",
      validUpstreamCard.replace(
        '    <g transform="translate(220,20)"><path id="github-mark" /></g>',
        '    <g transform="translate(220,20)"><path id="github-mark" /></g><rect id="after-badge" />',
      ),
    ],
    ["malformed XML", "<svg>"],
  ];

  for (const [name, source] of invalidCards) {
    const dir = mkdtempSync(join(tmpdir(), "github-stats-card-invalid-"));
    const input = join(dir, "upstream.svg");
    const output = join(dir, "stats.svg");
    writeFileSync(input, source);

    if (name !== "malformed XML") {
      writeFileSync(output, "existing output");
    }

    const result = spawnSync("python3", [script.pathname, "--input", input, "--output", output], {
      cwd: repoRoot,
      encoding: "utf8",
    });

    assert.notEqual(result.status, 0, `${name}: ${result.stderr}`);
    if (name === "malformed XML") {
      assert.equal(existsSync(output), false, `${name} unexpectedly created an output file`);
    } else {
      assert.equal(readFileSync(output, "utf8"), "existing output", `${name} overwrote output`);
    }
  }
});

test("README and Update Stats workflow use the repository-owned stats card", () => {
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  const workflow = readFileSync(
    new URL("../.github/workflows/update-stats-schedule.yml", import.meta.url),
    "utf8",
  );
  const generatedCard = new URL("../assets/github-stats-card.svg", import.meta.url);

  assert.match(readme, /src="\.\/assets\/github-stats-card\.svg"/);
  assert.match(
    workflow,
    /- name: Fetch GitHub stats card\n\s+id: fetch-github\n\s+continue-on-error: true\n\s+run: python scripts\/fetch-github-stats-card\.py/,
  );
  assert.equal(existsSync(generatedCard), true);
  const svg = readFileSync(generatedCard, "utf8");
  assert.match(
    svg,
    /<text x="30" y="40" style="font-size: 18px; fill: #70a5fd;">ceilf6's Github Stats<\/text>/,
  );
  assert.match(
    svg,
    /<circle(?=[^>]*cx="48")(?=[^>]*cy="48")(?=[^>]*r="40")(?=[^>]*fill="none")(?=[^>]*stroke="#bf91f3")(?=[^>]*stroke-width="6")[^>]*\/>/,
  );
  assert.match(
    svg,
    /<text[^>]*x="47"[^>]*y="58"[^>]*transform="translate\(-3\.76 0\) scale\(1\.08 1\)"[^>]*style="font-family: Arial; font-size: 24px; font-weight: 400; fill: #ffffff;">S<\/text>/,
  );
});
