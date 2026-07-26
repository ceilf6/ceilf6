import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  applyImageMetadata,
  formatAwards,
  loadAwards,
  readImageSizeFromFile,
  resolvePublicUrl,
} from "./update-image-metadata.mjs";

const publicRoot = new URL("../public/", import.meta.url);
const awardsFile = new URL("../src/data/awards.json", import.meta.url);

function loadImages() {
  return loadAwards(readFileSync(awardsFile, "utf8"));
}

test("all award image entries include real dimensions for source and thumbnail files", () => {
  const images = loadImages();

  for (const image of images) {
    const sourceSize = readImageSizeFromFile(resolvePublicUrl(image.src, publicRoot));
    assert.equal(image.width, sourceSize.width, `${image.src} width`);
    assert.equal(image.height, sourceSize.height, `${image.src} height`);

    if (image.thumb) {
      const thumbSize = readImageSizeFromFile(resolvePublicUrl(image.thumb, publicRoot));
      assert.equal(image.thumbWidth, thumbSize.width, `${image.thumb} width`);
      assert.equal(image.thumbHeight, thumbSize.height, `${image.thumb} height`);
    }
  }
});

test("image metadata generator keeps awards.json up to date", () => {
  const images = loadImages();
  const withMetadata = applyImageMetadata(images, publicRoot);
  const expectedSource = formatAwards(withMetadata);

  assert.equal(readFileSync(awardsFile, "utf8"), expectedSource);
});

test("image metadata generator preserves future custom fields", () => {
  const [firstImage] = loadImages();
  const [withMetadata] = applyImageMetadata(
    [
      {
        ...firstImage,
        featured: true,
        group: "fixture",
      },
    ],
    publicRoot,
  );

  assert.equal(withMetadata.featured, true);
  assert.equal(withMetadata.group, "fixture");

  const formatted = formatAwards([withMetadata]);
  assert.match(formatted, /"featured": true/);
  assert.match(formatted, /"group": "fixture"/);
});
