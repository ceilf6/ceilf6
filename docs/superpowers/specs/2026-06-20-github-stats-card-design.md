# GitHub Stats Card Design

## Goal

Replace the remote GitHub Stats card in the profile README with a repository-owned SVG that refreshes daily. The card must preserve the current `github-profile-summary-cards` title, five statistics, icon list, colours, and 340×200 layout. Its right-side GitHub mark becomes a custom `S` badge.

## Source and refresh

The existing `Update Stats` workflow will run one additional Python command after its current data fetches. The command downloads this canonical upstream source on each scheduled/manual run:

```text
https://github-profile-summary-cards.vercel.app/api/cards/stats?username=ceilf6&theme=tokyonight
```

This preserves the upstream project's definitions for Total Stars, the current-year commit count, Total PRs, Total Issues, and Contributed to. No GitHub token or separate statistic calculation is added. If the download or source validation fails, the workflow fails before committing and the previously generated local SVG remains unchanged.

## Transformation

`scripts/fetch-github-stats-card.py` will:

1. Download the source SVG, or read a supplied local SVG when invoked by tests.
2. Validate the card contract: SVG root; `width="340"`, `height="200"`, and `viewBox="0 0 340 200"`; title `Stats`; the five expected left-side field labels; and the final right-side group at `translate(220,20)`.
3. Preserve every source element except that final right-side group.
4. Replace the group with a Tokyo Night purple circular badge centred in the same visual area. It will contain a large `S`.
5. Write the resulting SVG atomically to `assets/github-stats-card.svg`.

The badge uses no JavaScript, external assets, or new runtime dependencies. `README.md` will reference the generated local file, while retaining the existing surrounding link and the three-card layout.

## Failure handling

The generator exits non-zero for an HTTP failure, malformed XML, or an upstream layout that no longer matches the validated contract. It does not overwrite the existing output on those failures. This makes upstream changes visible in GitHub Actions instead of silently publishing a partial card.

## Verification

A Node test will create a temporary upstream-card fixture and execute the Python script. It will verify that the output retains the source size, title, all five labels, and source statistic values; replaces the GitHub icon; and includes `S`. A malformed or incompatible fixture will be tested to ensure the generator fails without creating output. The repository's existing `node --test tests/*.mjs` suite will remain the workflow verification command.

## Scope

Changes are limited to the README reference, the existing daily stats workflow, one SVG-fetch/transform script, one generated SVG asset, and focused tests/fixtures. Blog, Vlog, contribution graph, and their data collection remain unchanged.
