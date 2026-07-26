import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  MAX_EDGE,
  planResize,
  resolveThumbStatus,
} from "./generate-thumbs.mjs";
import {
  loadAwards,
  readImageSizeFromFile,
  resolvePublicUrl,
} from "./update-image-metadata.mjs";

const publicRoot = new URL("../public/", import.meta.url);
const awardsFile = new URL("../src/data/awards.json", import.meta.url);

function loadImages() {
  return loadAwards(readFileSync(awardsFile, "utf8"));
}

test("thumbnail status flags missing and outdated thumbnails only", () => {
  assert.equal(
    resolveThumbStatus({ thumbExists: false, sourceMtimeMs: 1, thumbMtimeMs: 0 }),
    "missing",
  );
  assert.equal(
    resolveThumbStatus({ thumbExists: true, sourceMtimeMs: 2, thumbMtimeMs: 1 }),
    "stale",
  );
  assert.equal(
    resolveThumbStatus({ thumbExists: true, sourceMtimeMs: 1, thumbMtimeMs: 2 }),
    null,
  );
  assert.equal(
    resolveThumbStatus({
      thumbExists: true,
      sourceMtimeMs: 1,
      thumbMtimeMs: 2,
      force: true,
    }),
    "forced",
  );
});

test("resize plan never upscales a source smaller than the target edge", () => {
  assert.equal(planResize({ width: 2772, height: 2056 }), MAX_EDGE);
  assert.equal(planResize({ width: 788, height: 1112 }), MAX_EDGE);
  assert.equal(planResize({ width: 640, height: 480 }), null);
});

test("every award image has a thumbnail within the target edge", () => {
  const images = loadImages();
  const withThumbs = images.filter((image) => image.thumb);

  assert.equal(withThumbs.length, images.length);

  for (const image of withThumbs) {
    const size = readImageSizeFromFile(resolvePublicUrl(image.thumb, publicRoot));
    assert.ok(
      Math.max(size.width, size.height) <= MAX_EDGE,
      `${image.thumb} exceeds ${MAX_EDGE}px`,
    );
  }
});
