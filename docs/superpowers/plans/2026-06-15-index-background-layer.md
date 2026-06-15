# Index Background Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `index.html` so the visible page and browser elastic-scroll edge share the same fixed gradient background layer instead of exposing a white or pure black browser canvas.

**Architecture:** Keep the single-file static page. Move visual background responsibility out of the document-flow `body` background and into fixed pseudo-element layers: `body::before` for the main gradient, `body::after` for the existing soft glow, and `html::after` for noise plus the existing grid texture. Keep content on `z-index: 1`.

**Tech Stack:** Static HTML/CSS, Node.js built-in test runner, local HTTP server, Codex Browser / Playwright screenshot verification, ImageMagick pixel sampling.

---

### Task 1: Add CSS Structure Regression Test

**Files:**
- Modify: `tests/index-gallery.test.mjs`

- [ ] **Step 1: Add a style extraction helper near the top of the test file**

```js
const styleMatch = indexHtml.match(/<style>([\s\S]*?)<\/style>/i);
assert.ok(styleMatch, "index.html should include an inline style block");
const indexStyles = styleMatch[1];
```

- [ ] **Step 2: Add a regression test before the gallery behavior tests**

```js
test("page background uses fixed visual layers instead of a body paint fallback", () => {
  assert.match(indexStyles, /--page-background:\s*[\s\S]*linear-gradient\(/);
  assert.match(indexStyles, /html\s*\{[\s\S]*background-color:\s*var\(--bg-void\);[\s\S]*\}/);
  assert.match(indexStyles, /body\s*\{[\s\S]*background:\s*transparent;[\s\S]*\}/);
  assert.doesNotMatch(indexStyles, /body\s*\{[\s\S]*background-color:\s*var\(--bg-void\);[\s\S]*\}/);
  assert.match(indexStyles, /body::before\s*\{[\s\S]*position:\s*fixed;[\s\S]*background:\s*var\(--page-background\);[\s\S]*z-index:\s*-3;[\s\S]*\}/);
  assert.match(indexStyles, /body::after\s*\{[\s\S]*position:\s*fixed;[\s\S]*z-index:\s*-2;[\s\S]*\}/);
  assert.match(indexStyles, /html::after\s*\{[\s\S]*position:\s*fixed;[\s\S]*background-image:[\s\S]*linear-gradient\([\s\S]*feTurbulence[\s\S]*\}/);
});
```

- [ ] **Step 3: Run the focused test and confirm it fails before implementation**

Run: `node --test tests/index-gallery.test.mjs`

Expected: failure in the new background-layer test because `body` still owns the page background and `body::before` is still the grid layer.

### Task 2: Refactor `index.html` Background Layers

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Keep `--page-background` in `:root`**

Confirm the existing `--page-background` variable remains the single source for the main gradient.

- [ ] **Step 2: Change root and body paint responsibilities**

Replace the current `html` and `body` background declarations with:

```css
html {
  min-height: 100%;
  background-color: var(--bg-void);
}

body {
  min-height: 100vh;
  background: transparent;
  color: var(--text-main);
  display: flex;
  flex-direction: column;
  position: relative;
  overflow-x: hidden;
  font-family:
    "Azeret Mono", "Noto Sans SC", "PingFang SC", "Microsoft YaHei",
    sans-serif;
}
```

- [ ] **Step 3: Make `body::before` the fixed main gradient layer**

Replace the current grid-only `body::before` with:

```css
body::before {
  content: "";
  position: fixed;
  inset: 0;
  background: var(--page-background);
  background-attachment: fixed;
  z-index: -3;
  pointer-events: none;
}
```

- [ ] **Step 4: Keep `body::after` as the soft glow layer**

Set `body::after` to fixed viewport coverage with `z-index: -2`, keeping its existing radial-gradient content and animation:

```css
body::after {
  content: "";
  position: fixed;
  inset: -12%;
  background:
    radial-gradient(
      32% 38% at 14% 72%,
      rgba(255, 178, 98, 0.16) 0%,
      transparent 100%
    ),
    radial-gradient(
      36% 42% at 83% 18%,
      rgba(87, 227, 207, 0.14) 0%,
      transparent 100%
    ),
    radial-gradient(
      34% 36% at 44% 48%,
      rgba(120, 166, 255, 0.1) 0%,
      transparent 100%
    );
  filter: blur(14px);
  animation: floatOrbs 30s ease-in-out infinite;
  z-index: -2;
  pointer-events: none;
}
```

- [ ] **Step 5: Move the grid texture into `html::after` with the noise**

Update `html::after` so `background-image` contains the two grid linear-gradient layers followed by the existing noise SVG URL. Keep it fixed, pointer-events none, and visually subtle:

```css
html::after {
  content: "";
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(145, 184, 214, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(145, 184, 214, 0.06) 1px, transparent 1px),
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E");
  background-size: 38px 38px, 38px 38px, 160px 160px;
  opacity: 0.07;
  mix-blend-mode: overlay;
  pointer-events: none;
  z-index: 50;
}
```

### Task 3: Verify Tests and Rendered Pixels

**Files:**
- No source edits expected.

- [ ] **Step 1: Run all Node tests**

Run: `node --test tests/*.test.mjs`

Expected: 20 tests pass, 0 fail.

- [ ] **Step 2: Run whitespace diff check**

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 3: Serve the site locally**

Run: `python3 -m http.server 8000 --bind 127.0.0.1`

Expected: server starts at `http://127.0.0.1:8000/`.

- [ ] **Step 4: Use the browser to capture a screenshot**

Open `http://127.0.0.1:8000/index.html`, capture a screenshot, and save it under `/tmp/index-background-layer.png`.

- [ ] **Step 5: Sample screenshot pixels**

Run ImageMagick against the screenshot:

```bash
magick /tmp/index-background-layer.png -format '%[pixel:p{10,10}] %[pixel:p{10,719}] %[pixel:p{640,719}]' info:
```

Expected: sampled colors are dark blue / blue-tinted values, not white and not all equal to `srgb(5,9,20)`.

- [ ] **Step 6: Stop the local HTTP server**

Send Ctrl-C to the server session and confirm it exits.

### Task 4: Review and Report

**Files:**
- No source edits expected.

- [ ] **Step 1: Inspect the final diff**

Run: `git diff -- index.html tests/index-gallery.test.mjs docs/superpowers/plans/2026-06-15-index-background-layer.md`

Expected: diff only contains the planned CSS refactor, regression test, and this plan.

- [ ] **Step 2: Check working tree**

Run: `git status --short`

Expected: only planned files are modified or added.
