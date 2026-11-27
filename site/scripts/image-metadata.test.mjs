import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  applyImageMetadata,
  formatAwards,
  loadAwards,
  readImageDisplaySize,
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
  // GIF 逻辑屏幕描述符共 13 字节:只有签名 + 宽高(10 字节)也算截断
  assert.throws(() => readImageSize(Buffer.from("47494638396101000100", "hex")), /Corrupt GIF/);
});

test("readImageSize 拒绝头部完好但数据缺失的文件(尾部/声明长度校验)", () => {
  // WebP:VP8X 头完整(1600×1200),RIFF 声明总长远大于实际字节数
  const vp8x = Buffer.alloc(30);
  vp8x.write("RIFF", 0, "ascii");
  vp8x.writeUInt32LE(219712, 4);
  vp8x.write("WEBPVP8X", 8, "ascii");
  vp8x.writeUIntLE(1599, 24, 3);
  vp8x.writeUIntLE(1199, 27, 3);
  assert.throws(() => readImageSize(vp8x), /Corrupt WebP/);
  // 声明长度与实际一致时照常读出尺寸
  vp8x.writeUInt32LE(22, 4);
  assert.deepEqual(readImageSize(vp8x), { width: 1600, height: 1200 });
  // PNG:IHDR 声明 13 字节、实际只有宽高 8 字节就接上 IEND(首块不完整)
  const shortIhdr = Buffer.concat([
    Buffer.from("89504e470d0a1a0a0000000d49484452", "hex"),
    Buffer.from("0000000a00000014", "hex"),
    Buffer.from("0000000049454e44ae426082", "hex"),
  ]);
  assert.throws(() => readImageSize(shortIhdr), /Corrupt PNG/);
  // PNG:IHDR 完整但缺 IEND
  const png = Buffer.alloc(33);
  Buffer.from("89504e470d0a1a0a0000000d49484452", "hex").copy(png, 0);
  png.writeUInt32BE(10, 16);
  png.writeUInt32BE(20, 20);
  assert.throws(() => readImageSize(png), /Corrupt PNG/);
  // JPEG:SOF 完整但没有以 EOI(FFD9)结尾
  const jpeg = Buffer.from("ffd8ffc0001108000a001403012200021101031101ffda", "hex");
  assert.throws(() => readImageSize(jpeg), /Corrupt JPEG/);
});

// 最小 JPEG:SOI + APP1(Exif,IFD0 只有 Orientation)+ SOF0(width×height)+ EOI
function exifJpeg(width, height, orientation) {
  const app1 = Buffer.from(
    "ffe10022" + "457869660000" + "4d4d002a00000008" + "0001" + "011200030000000100" +
      orientation.toString(16).padStart(2, "0") + "0000" + "00000000",
    "hex",
  );
  const sof = Buffer.from("ffc0001108" + "0000" + "0000" + "03012200021101031101", "hex");
  sof.writeUInt16BE(height, 5);
  sof.writeUInt16BE(width, 7);
  return Buffer.concat([Buffer.from("ffd8", "hex"), app1, sof, Buffer.from("ffd9", "hex")]);
}

test("readImageDisplaySize:JPEG EXIF 方向 5–8 交换宽高(按显示方向),其余格式与方向不变", () => {
  assert.deepEqual(readImageDisplaySize(exifJpeg(1200, 800, 6)), { width: 800, height: 1200 });
  assert.deepEqual(readImageDisplaySize(exifJpeg(1200, 800, 8)), { width: 800, height: 1200 });
  assert.deepEqual(readImageDisplaySize(exifJpeg(1200, 800, 1)), { width: 1200, height: 800 });
  assert.deepEqual(readImageDisplaySize(exifJpeg(1200, 800, 3)), { width: 1200, height: 800 });
  // 共用的 readImageSize(awards 元数据)保持编码尺寸,不受影响
  assert.deepEqual(readImageSize(exifJpeg(1200, 800, 6)), { width: 1200, height: 800 });
});
