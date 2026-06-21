# Centered README Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Render the four README profile cards as two smaller, centred, borderless pairs with a visible gutter.

**Architecture:** Replace the intrinsic-width HTML table with two full-width centred paragraphs. Each paragraph holds two existing links with 39%-wide SVG images and an entity-based gutter; no card assets, URLs, workflows, or scripts change. The focused integration test becomes the stable contract for the structural layout.

**Tech Stack:** GitHub-flavoured Markdown HTML, Node.js built-in test runner.

---

### Task 1: Borderless centred card rows

**Files:**
- Modify: tests/huggingface-card.test.mjs:96-125
- Modify: README.md:4-13

- [ ] **Step 1: Write the failing layout assertions**

Replace the card-layout assertions at the end of the existing integration test with:

~~~
  assert.doesNotMatch(readme.slice(0, readme.indexOf("<p align=\"center\">")), /<table>/);
  assert.match(
    readme,
    /<p align="center">\n\s*<a href="https:\/\/ceilf6\.github\.io\/ceilf6\/" target="_blank"><img width="39%" src="\.\/assets\/github-stats-card\.svg" \/><\/a>&emsp;<a href="https:\/\/huggingface\.co\/ceilf6" target="_blank"><img width="39%" src="\.\/assets\/huggingface-card\.svg" \/><\/a>\n\s*<\/p>/,
  );
  assert.match(
    readme,
    /<p align="center">\n\s*<a href="https:\/\/ceilf6\.github\.io\/ceilf6\/vlog\.html" target="_blank"><img width="39%" src="\.\/assets\/vlog-card\.svg" \/><\/a>&emsp;<a href="https:\/\/blog\.csdn\.net\/2301_78856868" target="_blank"><img width="39%" src="\.\/assets\/blog-card\.svg" \/><\/a>\n\s*<\/p>/,
  );
~~~

Keep the existing card-order, Hugging Face link, workflow, and generated-asset assertions unchanged.

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

~~~
node --test tests/huggingface-card.test.mjs
~~~

Expected: FAIL because README still contains a table and 100%-wide cell images.

- [ ] **Step 3: Replace the README table with the approved card rows**

Replace README.md lines 4-13 with:

~~~
<p align="center">
  <a href="https://ceilf6.github.io/ceilf6/" target="_blank"><img width="39%" src="./assets/github-stats-card.svg" /></a>&emsp;<a href="https://huggingface.co/ceilf6" target="_blank"><img width="39%" src="./assets/huggingface-card.svg" /></a>
</p>
<p align="center">
  <a href="https://ceilf6.github.io/ceilf6/vlog.html" target="_blank"><img width="39%" src="./assets/vlog-card.svg" /></a>&emsp;<a href="https://blog.csdn.net/2301_78856868" target="_blank"><img width="39%" src="./assets/blog-card.svg" /></a>
</p>
~~~

- [ ] **Step 4: Run focused and full verification**

Run:

~~~
node --test tests/huggingface-card.test.mjs
node --test tests/*.mjs
git diff --check
~~~

Expected: all focused and repository tests pass, and git diff --check emits no output.

- [ ] **Step 5: Inspect and commit the completed layout**

Run:

~~~
git diff -- README.md tests/huggingface-card.test.mjs
git add README.md tests/huggingface-card.test.mjs docs/superpowers/plans/2026-06-21-centered-readme-cards.md
git commit -m "style: center readme card pairs"
~~~

Expected: a focused commit containing only the card-layout markup, regression coverage, and plan.

