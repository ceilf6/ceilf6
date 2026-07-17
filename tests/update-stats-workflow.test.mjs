import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workflow = readFileSync(
  new URL("../.github/workflows/update-stats-schedule.yml", import.meta.url),
  "utf8",
);

test("stats sources continue independently and report failures after publishing", () => {
  const fetchSteps = [
    ["Fetch Bilibili stats", "fetch-bilibili", "python scripts/fetch-bilibili-stats-1.py"],
    ["Fetch CSDN stats", "fetch-csdn", "python scripts/fetch-csdn-stats-2.py"],
    ["Fetch GitHub stats card", "fetch-github", "python scripts/fetch-github-stats-card.py"],
    ["Fetch Hugging Face stats", "fetch-huggingface", "python scripts/fetch-huggingface-stats.py"],
  ];

  for (const [name, id, command] of fetchSteps) {
    assert.match(
      workflow,
      new RegExp(
        `- name: ${name}\\n\\s+id: ${id}\\n\\s+continue-on-error: true\\n\\s+run: ${command.replaceAll(".", "\\.")}`,
      ),
      `${name} must allow the remaining sources to run`,
    );
    const outcomeLine =
      `${id.toUpperCase().replaceAll("-", "_")}_OUTCOME: ` +
      "${{ steps." +
      id +
      ".outcome }}";
    assert.ok(workflow.includes(outcomeLine), `${name} outcome must be included in the final report`);
  }

  const publishIndex = workflow.indexOf("- name: Commit and push if changed");
  const reportIndex = workflow.indexOf("- name: Report fetch failures");
  assert.ok(publishIndex >= 0, "publish step is missing");
  assert.ok(reportIndex > publishIndex, "failure reporting must happen after successful data is pushed");
  assert.match(workflow.slice(reportIndex), /if: always\(\)/);
  assert.match(workflow.slice(reportIndex), /exit 1/);
});
