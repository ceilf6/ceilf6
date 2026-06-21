# Hugging Face Card Design

## Goal

Add a repository-owned Hugging Face profile card to the profile README. The card refreshes with the existing daily `Update Stats` workflow, links to `https://huggingface.co/ceilf6`, and uses the same Tokyo Night palette, 340×200 dimensions, typography, and purple line-icon treatment as the existing Blog and Vlog cards.

## Data source and refresh

The workflow will fetch the public Hugging Face profile overview endpoint once per run:

```text
https://huggingface.co/api/users/ceilf6/overview
```

The fetch script will retain exactly these five public profile totals in `data/huggingface-stats.json`:

- `numFollowers`
- `numLikes`
- `numModels`
- `numDatasets`
- `numSpaces`

The endpoint is the stable public profile-overview API and supplies all five values in one response. It is preferable to scraping the rendered profile page or deriving totals from multiple repository-list requests. The existing `Update Stats` workflow already runs daily at 03:00 UTC, and will run the Hugging Face fetch before the shared SVG-card generator.

If the request, JSON parsing, or field validation fails, the script exits non-zero and writes no data file. GitHub Actions consequently fails before the card generator and retains the last committed data and SVG assets.

## Card rendering

`scripts/generate-svg-cards.py` will gain a Hugging Face renderer that consumes `data/huggingface-stats.json` and writes `assets/huggingface-card.svg`. It will preserve the existing card canvas, background, colours, labels, number formatting, and five-row spacing. The rows, in order, are:

1. Followers
2. Likes
3. Models
4. Datasets
5. Spaces

The left-side pictograms will use the same purple line-icon language as the Blog and Vlog cards. The supplied `svg/hugging_face_high_contrast.svg` will be retained as the source logo and its purple Hugging Face mark will be embedded on the right of the generated card, rather than referenced at runtime. This keeps the README card self-contained and renders correctly on GitHub.

## README layout

The README card section will become two explicit rows, each with two 50% cards:

1. GitHub Stats (left) and Hugging Face (right)
2. Vlog (left) and Blog (right)

The Hugging Face image will be wrapped in a link to `https://huggingface.co/ceilf6`. Existing GitHub, Vlog, and Blog destinations remain unchanged. Explicit row containers prevent Markdown whitespace or renderer differences from collapsing the intended 2×2 layout.

## Verification

A focused Node test will use a temporary Hugging Face overview JSON fixture to verify that the fetch script extracts and atomically writes the five required values. It will also verify that malformed, incomplete, and invalid-count responses fail without replacing an existing data file. The test will exercise the renderer and assert its 340×200 output, title, labels, source values, and embedded Hugging Face mark. It will confirm the README link, 2×2 ordering, workflow fetch step, and generated asset reference. The repository-wide check remains:

```bash
node --test tests/*.mjs
```

## Scope

Changes are limited to one fetch script, the shared SVG generator, the existing daily workflow, the README card markup, the supplied logo source, generated Hugging Face data and SVG assets, and focused tests. The existing Blog, Vlog, GitHub Stats, and contribution-graph pipelines are otherwise unchanged.
