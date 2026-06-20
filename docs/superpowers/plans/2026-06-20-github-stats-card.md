# GitHub Stats Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the remote GitHub stats image with a locally owned SVG that preserves upstream statistics and displays an `S` badge.

**Architecture:** A standard-library Python script downloads the canonical upstream SVG (or reads a test fixture), verifies its fixed structural contract, replaces only the final right-side group, and atomically writes the result. A Node test exercises the command through its public CLI and validates both successful transformation and refusal to publish incompatible source cards.

**Tech Stack:** Python 3.11 standard library (`urllib`, `xml.etree.ElementTree`, `tempfile`), Node.js built-in test runner, GitHub Actions.

---

## File map

- Create: `scripts/fetch-github-stats-card.py` — fetch, validate, transform, and atomically publish the SVG.
- Create: `tests/github-stats-card.test.mjs` — fixture-driven CLI tests and README/workflow integration checks.
- Create: `assets/github-stats-card.svg` — current generated card committed for README rendering.
- Modify: `README.md` — reference the local generated SVG without changing its link or layout.
- Modify: `.github/workflows/update-stats-schedule.yml` — refresh the generated card during each scheduled/manual stats update.

### Task 1: Establish the generator contract with a failing test

**Files:**
- Create: `tests/github-stats-card.test.mjs`

- [ ] **Step 1: Add a self-contained valid upstream-card fixture and a success-path test.**

```js
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
  for (const value of ["Stats", "Total Stars:", "2026 Commits:", "Total PRs:", "Total Issues:", "Contributed to:", "42", "1234", "7", "8", "9"]) {
    assert.match(svg, new RegExp(`>${value}<`));
  }
  assert.match(svg, /<circle[^>]*fill="#bf91f3"/);
  assert.match(svg, />S<\/text>/);
  assert.doesNotMatch(svg, /github-mark/);
});
```

- [ ] **Step 2: Run the focused test and observe the expected failure because the script does not yet exist.**

Run: `node --test tests/github-stats-card.test.mjs`

Expected: failure of the success assertion with Python reporting that `scripts/fetch-github-stats-card.py` is absent.

### Task 2: Implement the success-path transformer

**Files:**
- Create: `scripts/fetch-github-stats-card.py`
- Test: `tests/github-stats-card.test.mjs`

- [ ] **Step 1: Implement the CLI with local-input support, canonical URL default, and an atomic write.**

```python
DEFAULT_URL = "https://github-profile-summary-cards.vercel.app/api/cards/stats?username=ceilf6&theme=tokyonight"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "assets" / "github-stats-card.svg"

def load_source(input_path, url):
    if input_path is not None:
        return input_path.read_bytes()
    request = Request(url, headers={"User-Agent": "ceilf6-github-stats-card"})
    with urlopen(request, timeout=30) as response:
        return response.read()

def write_atomically(output, content):
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    try:
        os.replace(temporary_path, output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
```

- [ ] **Step 2: Parse the SVG, identify the group at `translate(220,20)`, and replace it with the purple circular `S` badge while retaining all other elements.**

```python
replacement = ElementTree.Element(qualified_tag(root, "g"), {"transform": "translate(220,20)"})
ElementTree.SubElement(replacement, qualified_tag(root, "circle"), {
    "cx": "48", "cy": "48", "r": "48", "fill": "#bf91f3",
})
badge_text = ElementTree.SubElement(replacement, qualified_tag(root, "text"), {
    "x": "48", "y": "72", "text-anchor": "middle",
    "style": "font-size: 76px; font-weight: 800; fill: #1a1b27;",
})
badge_text.text = "S"
parent.insert(list(parent).index(target), replacement)
parent.remove(target)
```

- [ ] **Step 3: Run the focused success test and confirm it passes.**

Run: `node --test tests/github-stats-card.test.mjs`

Expected: the success-path test passes with the five labels and statistics retained.

### Task 3: Add contract rejection and preservation tests, then enforce the contract

**Files:**
- Modify: `tests/github-stats-card.test.mjs`
- Modify: `scripts/fetch-github-stats-card.py`

- [ ] **Step 1: Add incompatible and malformed fixture cases that verify a pre-existing output is unchanged.**

```js
for (const [name, source] of [
  ["wrong dimensions", validUpstreamCard.replace('width="340"', 'width="341"')],
  ["missing field label", validUpstreamCard.replace("Total Stars:", "Stars:")],
  ["missing right-side group", validUpstreamCard.replace("translate(220,20)", "translate(221,20)")],
  ["malformed XML", "<svg>"],
]) {
  // Write `existing output`, execute the CLI, then assert non-zero status and unchanged output.
}
```

- [ ] **Step 2: Run the focused test and observe the expected failure for an incompatible card being written.**

Run: `node --test tests/github-stats-card.test.mjs`

Expected: the invalid-card case fails because validation has not yet rejected the altered source.

- [ ] **Step 3: Validate the full documented upstream contract before building replacement output.**

```python
EXPECTED_LABELS = ("Total Stars:", f"{datetime.now(timezone.utc).year} Commits:", "Total PRs:", "Total Issues:", "Contributed to:")

def validate_card(root):
    if local_name(root.tag) != "svg":
        raise ValueError("Upstream card root is not an SVG")
    if (root.get("width"), root.get("height"), root.get("viewBox")) != ("340", "200", "0 0 340 200"):
        raise ValueError("Upstream card dimensions do not match the expected 340x200 layout")
    text_values = {"".join(element.itertext()).strip() for element in root.iter() if local_name(element.tag) == "text"}
    if "Stats" not in text_values or not set(EXPECTED_LABELS).issubset(text_values):
        raise ValueError("Upstream card text contract does not match the expected stats layout")
    matches = [(parent, child) for parent in root.iter() for child in parent if local_name(child.tag) == "g" and child.get("transform") == "translate(220,20)"]
    if len(matches) != 1 or list(matches[0][0])[-1] is not matches[0][1]:
        raise ValueError("Upstream card right-side group does not match the expected layout")
    return matches[0]
```

- [ ] **Step 4: Catch HTTP, input, XML, and contract failures at the command boundary; only call the atomic writer after successful validation and transformation.**

```python
try:
    source = load_source(args.input, args.url)
    root = ElementTree.fromstring(source)
    parent, target = validate_card(root)
    replace_right_side_group(root, parent, target)
    write_atomically(args.output, ElementTree.tostring(root, encoding="unicode"))
except Exception as exc:
    print(f"Error: {exc}", file=sys.stderr)
    return 1
```

- [ ] **Step 5: Re-run the focused test and confirm both the replacement and non-overwrite behavior pass.**

Run: `node --test tests/github-stats-card.test.mjs`

Expected: every generator test passes; malformed and incompatible inputs leave their output files unchanged.

### Task 4: Wire the generated asset into the profile

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/update-stats-schedule.yml`
- Modify: `tests/github-stats-card.test.mjs`
- Create: `assets/github-stats-card.svg`

- [ ] **Step 1: Add a failing static integration test that requires the local README source and scheduled generator command.**

```js
test("README and Update Stats workflow use the repository-owned stats card", () => {
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  const workflow = readFileSync(new URL("../.github/workflows/update-stats-schedule.yml", import.meta.url), "utf8");
  assert.match(readme, /src="\.\/assets\/github-stats-card\.svg"/);
  assert.match(workflow, /Fetch GitHub stats card\n\s+run: python scripts\/fetch-github-stats-card\.py/);
});
```

- [ ] **Step 2: Run the focused test and observe the expected failure because the README still references the remote URL.**

Run: `node --test tests/github-stats-card.test.mjs`

Expected: the integration test fails on the missing local README source.

- [ ] **Step 3: Change only the first card image source in `README.md` to `./assets/github-stats-card.svg`, retaining its existing link and `width="33%"`.**

- [ ] **Step 4: Insert `python scripts/fetch-github-stats-card.py` after the existing data-fetch steps and before `Generate SVG cards` in `.github/workflows/update-stats-schedule.yml`.**

- [ ] **Step 5: Run the generator with its default source to create `assets/github-stats-card.svg`, then rerun the focused test.**

Run: `python scripts/fetch-github-stats-card.py && node --test tests/github-stats-card.test.mjs`

Expected: the tracked SVG contains the source statistics and a single `S` badge; the integration test passes.

### Task 5: Verify the deliverable

**Files:**
- Verify: `README.md`, `.github/workflows/update-stats-schedule.yml`, `scripts/fetch-github-stats-card.py`, `tests/github-stats-card.test.mjs`, `assets/github-stats-card.svg`

- [ ] **Step 1: Run the repository verification command.**

Run: `node --test tests/*.mjs`

Expected: all existing tests plus the new stats-card tests pass.

- [ ] **Step 2: Inspect the final diff and generated SVG contract.**

Run: `git diff --check && git diff -- README.md .github/workflows/update-stats-schedule.yml scripts/fetch-github-stats-card.py tests/github-stats-card.test.mjs assets/github-stats-card.svg`

Expected: only the scoped files change; no whitespace errors; the README retains the three-card layout.

No commit is part of this plan: the requested work is being made directly on `main`, and commit creation was not requested.
