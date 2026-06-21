# Hugging Face Last-Updated Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a CSDN-format `last_updated` timestamp whenever Hugging Face statistics are successfully fetched.

**Architecture:** The fetcher owns collection metadata. It will append the local timestamp to the validated profile totals immediately before its existing atomic write; the card renderer remains unchanged. Tests will verify both the timestamp format on success and preservation of prior output on invalid source input.

**Tech Stack:** Python 3 standard library, Node.js built-in test runner.

---

### Task 1: Timestamped Hugging Face statistics output

**Files:**
- Modify: `tests/huggingface-card.test.mjs:31-35`
- Modify: `scripts/fetch-huggingface-stats.py:3-70`
- Modify: `data/huggingface-stats.json`

- [x] **Step 1: Write the failing fetcher output test**

Change the successful fetch test to assert the five totals and a CSDN-format timestamp:

```js
test("fetcher writes the five required Hugging Face overview totals and update time", () => {
  const { result, output } = runFetcher(JSON.stringify(validOverview));
  assert.equal(result.status, 0, result.stderr);
  const stats = JSON.parse(readFileSync(output, "utf8"));
  assert.deepEqual(
    Object.fromEntries(Object.entries(stats).filter(([key]) => key !== "last_updated")),
    validOverview,
  );
  assert.match(stats.last_updated, /^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$/);
});
```

- [x] **Step 2: Run the focused test to verify it fails**

Run:

```bash
node --test tests/huggingface-card.test.mjs
```

Expected: FAIL because `last_updated` is absent from the fetcher output.

- [x] **Step 3: Add the timestamp before the atomic write**

Import `datetime`, then assign the timestamp after validation and before `write_atomically`:

```python
from datetime import datetime

# In main(), after parse_overview succeeds:
stats["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
write_atomically(args.output, stats)
```

Update `data/huggingface-stats.json` to include a valid `last_updated` value. Do not change the five current totals.

- [x] **Step 4: Run focused and full verification**

Run:

```bash
node --test tests/huggingface-card.test.mjs
node --test tests/*.mjs
git diff --check
```

Expected: all tests pass, invalid-input tests retain their existing output-preservation guarantee, and the diff check emits no output.

- [x] **Step 5: Commit the completed change**

Run:

```bash
git add scripts/fetch-huggingface-stats.py data/huggingface-stats.json tests/huggingface-card.test.mjs docs/superpowers/plans/2026-06-21-huggingface-last-updated.md
git commit -m "feat: record hugging face update time"
```

Expected: one focused commit containing the fetcher behaviour, sample data, regression coverage, and this plan.
