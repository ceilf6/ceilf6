# Index Card Grid Design

## Goal

Show all four profile cards on one row in the desktop site header: GitHub Stats, Hugging Face, Vlog, and Blog. Preserve the existing dark glass-card treatment, loaders, hover behaviour, and links.

## Layout

`index.html` will replace the wrapping flex row with a CSS grid. On screens wider than 900px, `grid-template-columns: repeat(4, minmax(0, 1fr))` creates four equal-width cards in a single row with the existing 14px gutter. Cards will use `width: 100%` and `aspect-ratio: 340 / 200`, so their height follows their allocated width instead of retaining a 340px flex basis.

The first desktop-row order is Stats, Hugging Face, Vlog, Blog. A new Hugging Face anchor links to `https://huggingface.co/ceilf6` and loads `assets/huggingface-card.svg` using the same loading-state class and dimensions as the other cards.

## Responsive behaviour

At `max-width: 900px`, the card grid becomes two columns. At `max-width: 640px`, it becomes one column. This preserves readable labels and tap targets; forcing four columns at those widths would reduce each 340×200 card below a usable size.

## Verification

The existing index regression test will be extended to assert the fourth card, its Hugging Face destination and SVG source, desktop four-column grid rule, and tablet/mobile column changes. Existing loader tests will run against four card fixtures. The complete verification command remains `node --test tests/*.mjs`.

## Scope

Changes are limited to `index.html`, `tests/index-gallery.test.mjs`, and implementation documentation. README card markup, data workflows, generators, and SVG assets are unchanged.
