# Hugging Face Last-Updated Design

## Goal

Add a `last_updated` field to `data/huggingface-stats.json`, matching the timestamp convention used by `data/csdn-stats.json`.

## Data Contract

`last_updated` is a local-time string formatted as `YYYY-MM-DD HH:MM:SS`. It represents the time at which a valid Hugging Face overview was successfully written to the output JSON.

The five Hugging Face totals remain unchanged:

- `numFollowers`
- `numLikes`
- `numModels`
- `numDatasets`
- `numSpaces`

## Implementation

`scripts/fetch-huggingface-stats.py` will add the timestamp immediately before its existing atomic JSON write. The fetcher remains responsible for the profile data and its metadata; `scripts/generate-svg-cards.py` remains a pure renderer and does not display the timestamp.

The committed `data/huggingface-stats.json` will include the new field. Fetch failures, malformed API payloads, and failed writes retain the current atomic-write behaviour: the existing output is left unchanged.

## Verification

Extend the Hugging Face fetcher tests to verify a successful run writes a correctly formatted `last_updated`, and that invalid input still does not replace an existing output. Run the focused test and the full Node test suite.
