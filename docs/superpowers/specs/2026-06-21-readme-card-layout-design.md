# README Card Layout Design

## Goal

Replace the shrinking HTML table around the four profile cards with a centered, borderless two-row layout. The cards should remain easy to scan while using intentional whitespace rather than a narrow table frame.

## Layout

`README.md` will use two `<p align="center">` rows instead of `<table>`. Each row contains two existing card links in the current order:

1. GitHub Stats and Hugging Face
2. Vlog and Blog

Each image will use `width="39%"`; an `&emsp;` between the linked images supplies a visible central gutter. This creates a refined card cluster: the pair is centred, cards are slightly smaller than the current rendering, and roughly 10% of the available width remains on each outer side. No table borders, cell padding, CSS, or JavaScript are used.

## Compatibility

GitHub README rendering supports the existing HTML anchors, images, paragraphs, and entity spacing. The design deliberately avoids table sizing and style attributes because their sanitised or intrinsic layout behaviour produced the narrow framed result in the current render. Image widths remain percentage-based, so the layout contracts on narrower viewports without a separate responsive implementation.

## Verification

The focused Hugging Face integration test will assert that the card section has no `<table>`, retains the four card paths and links in order, and contains two centred card rows with 39% image widths and the separator. The complete `node --test tests/*.mjs` suite remains the regression check.

## Scope

Only `README.md`, its focused layout test, and the generated planning/design documentation change. Card SVGs, data fetches, workflows, links, and the remaining README content are unchanged.
