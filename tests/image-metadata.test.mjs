import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

import {
  applyImageMetadata,
  formatImagesModule,
  readImageSizeFromFile,
} from "../scripts/update-image-metadata.mjs";

const repoRoot = new URL("../", import.meta.url);
const imagesFile = new URL("../resume-awards/images.js", import.meta.url);

function loadImages() {
  return vm.runInNewContext(`${readFileSync(imagesFile, "utf8")}\nimages;`, {});
}

test("all award image entries include real dimensions for source and thumbnail files", () => {
  const images = loadImages();

  for (const image of images) {
    const sourceSize = readImageSizeFromFile(new URL(image.src, repoRoot));
    assert.equal(image.width, sourceSize.width, `${image.src} width`);
    assert.equal(image.height, sourceSize.height, `${image.src} height`);

    if (image.thumb) {
      const thumbSize = readImageSizeFromFile(new URL(image.thumb, repoRoot));
      assert.equal(image.thumbWidth, thumbSize.width, `${image.thumb} width`);
      assert.equal(image.thumbHeight, thumbSize.height, `${image.thumb} height`);
    }
  }
});

test("image metadata generator keeps images.js up to date", () => {
  const images = loadImages();
  const withMetadata = applyImageMetadata(images, repoRoot);
  const expectedSource = formatImagesModule(withMetadata);

  assert.equal(readFileSync(imagesFile, "utf8"), expectedSource);
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
    repoRoot,
  );

  assert.equal(withMetadata.featured, true);
  assert.equal(withMetadata.group, "fixture");

  const formatted = formatImagesModule([withMetadata]);
  assert.match(formatted, /featured: true,/);
  assert.match(formatted, /group: "fixture",/);
});
