# Index Four-Card Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Render Stats, Hugging Face, Vlog, and Blog as one equal-width desktop row in index.html while retaining readable tablet and mobile layouts.

**Architecture:** Replace the readme-cards wrapping flex row with a responsive CSS grid. The DOM gains one Hugging Face link; shared loader and hover behaviour remain unchanged. Static CSS/HTML assertions plus the existing loader fixture protect the responsive layout and fourth card.

**Tech Stack:** HTML, CSS Grid, Node.js built-in test runner.

---

### Task 1: Responsive four-card homepage grid

**Files:**
- Modify: tests/index-gallery.test.mjs:105-116 and after the background test
- Modify: index.html:398-503 and 536-565

- [x] **Step 1: Write the failing grid and fourth-card tests**

Change the fixture declaration to create four cards:

~~~
  const readmeCards = [
    createElement("a"),
    createElement("a"),
    createElement("a"),
    createElement("a"),
  ];
~~~

Add this test after the page-background test:

~~~
test("homepage uses an ordered responsive four-card grid", () => {
  const cardSources = [
    "./assets/github-stats-card.svg",
    "./assets/huggingface-card.svg",
    "assets/vlog-card.svg",
    "assets/blog-card.svg",
  ];
  let position = -1;
  for (const source of cardSources) {
    const next = indexHtml.indexOf('src="' + source + '"');
    assert.ok(next > position, source + " is not in the required order");
    position = next;
  }
  assert.match(indexHtml, /href="https:\/\/huggingface\.co\/ceilf6"/);
  assert.match(getCssRule(".readme-cards"), /display:\s*grid;/);
  assert.match(
    getCssRule(".readme-cards"),
    /grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(getCssRule(".readme-card"), /width:\s*100%;/);
  assert.match(
    indexStyles,
    /@media \(max-width: 900px\) \{[\s\S]*?\.readme-cards\s*\{[\s\S]*?grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(
    indexStyles,
    /@media \(max-width: 640px\) \{[\s\S]*?\.readme-cards\s*\{[\s\S]*?grid-template-columns:\s*1fr;/,
  );
  assert.equal(runIndexScript().readmeCards.length, 4);
});
~~~

- [x] **Step 2: Run the focused test to verify it fails**

Run:

~~~
node --test tests/index-gallery.test.mjs
~~~

Expected: FAIL because index.html has three cards and a wrapping flex layout.

- [x] **Step 3: Implement the minimal responsive grid and Hugging Face card**

Replace the desktop rules with:

~~~
      .readme-cards {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
      }

      .readme-card {
        position: relative;
        display: block;
        width: 100%;
        height: auto;
        aspect-ratio: 340 / 200;
        min-width: 0;
        overflow: hidden;
        border-radius: 12px;
        border: 1px solid rgba(194, 220, 245, 0.34);
        background: linear-gradient(
          160deg,
          rgba(10, 24, 42, 0.92),
          rgba(15, 33, 56, 0.68)
        );
        box-shadow: 0 14px 30px rgba(3, 10, 24, 0.3);
        transition:
          transform 0.45s cubic-bezier(0.22, 1, 0.36, 1),
          box-shadow 0.45s cubic-bezier(0.22, 1, 0.36, 1),
          border-color 0.35s ease;
      }
~~~

Inside the max-width 900px media query add:

~~~
        .readme-cards {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
~~~

Inside the max-width 640px media query add:

~~~
        .readme-cards {
          grid-template-columns: 1fr;
        }
~~~

Remove the responsive readme-card flex-basis and height declarations. Insert this anchor directly after the Stats anchor and put Vlog before Blog:

~~~
        <a
          class="readme-card is-loading"
          href="https://huggingface.co/ceilf6"
          target="_blank"
          rel="noopener noreferrer"
          ><span class="readme-card-loader" aria-hidden="true">加载中</span
          ><img
            src="./assets/huggingface-card.svg"
            alt="Hugging Face"
            width="340"
            height="200"
        /></a>
~~~

- [x] **Step 4: Run focused and full verification**

Run:

~~~
node --test tests/index-gallery.test.mjs
node --test tests/*.mjs
git diff --check
~~~

Expected: all tests pass and git diff --check emits no output.

- [x] **Step 5: Review and commit separately from the README layout**

Run:

~~~
git diff -- index.html tests/index-gallery.test.mjs tests/huggingface-card.test.mjs
git add index.html tests/index-gallery.test.mjs tests/huggingface-card.test.mjs docs/superpowers/plans/2026-06-21-index-four-card-grid.md
git commit -m "feat: add hugging face homepage card"
~~~

Expected: one commit contains only the index grid, fourth card, regression coverage, the stale README width assertion sync, and this plan.
