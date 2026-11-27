import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  applyImageMetadata,
  formatAwards,
  loadAwards,
  readImageSize,
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

test("readImageSize 区分未知格式与已识别但截断的文件", () => {
  // 未知签名 → 不支持的格式(调用方可以据此降级)
  assert.throws(() => readImageSize(Buffer.from("<svg/>")), /Unsupported image format/);
  // PNG 签名完整但 IHDR 不全
  const png = Buffer.from("89504e470d0a1a0a0000000d49484452", "hex");
  assert.throws(() => readImageSize(png), /Corrupt PNG/);
  // JPEG:SOI + APP0 段,之后截断,找不到 SOF
  const jpeg = Buffer.from("ffd8ffe000104a46494600010100000100010000", "hex");
  assert.throws(() => readImageSize(jpeg), /Corrupt JPEG/);
  // WebP:只剩到 VP8X 块名,宽高字段缺失(此前会读出 1×1)
  const webp = Buffer.concat([Buffer.from("RIFF"), Buffer.alloc(4), Buffer.from("WEBPVP8X")]);
  assert.throws(() => readImageSize(webp), /Corrupt WebP/);
  // GIF 头不全
  assert.throws(() => readImageSize(Buffer.from("GIF89a\x01")), /Corrupt GIF/);
});
