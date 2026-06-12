import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { runInNewContext } from "node:vm";

const repoRoot = new URL("../", import.meta.url);
const imagesFile = new URL("../resume-awards/images.js", import.meta.url);

function readUint24LE(buffer, offset) {
  return buffer[offset] | (buffer[offset + 1] << 8) | (buffer[offset + 2] << 16);
}

function readPngSize(buffer) {
  const pngSignature = "89504e470d0a1a0a";
  if (buffer.subarray(0, 8).toString("hex") !== pngSignature) return null;

  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
  };
}

function readGifSize(buffer) {
  const signature = buffer.subarray(0, 6).toString("ascii");
  if (signature !== "GIF87a" && signature !== "GIF89a") return null;

  return {
    width: buffer.readUInt16LE(6),
    height: buffer.readUInt16LE(8),
  };
}

function readJpegSize(buffer) {
  if (buffer[0] !== 0xff || buffer[1] !== 0xd8) return null;

  let offset = 2;
  while (offset < buffer.length) {
    while (buffer[offset] === 0xff) offset += 1;
    const marker = buffer[offset];
    offset += 1;

    if (marker === 0xd9 || marker === 0xda) break;
    if (offset + 2 > buffer.length) break;

    const segmentLength = buffer.readUInt16BE(offset);
    if (segmentLength < 2 || offset + segmentLength > buffer.length) break;

    const isStartOfFrame =
      (marker >= 0xc0 && marker <= 0xc3) ||
      (marker >= 0xc5 && marker <= 0xc7) ||
      (marker >= 0xc9 && marker <= 0xcb) ||
      (marker >= 0xcd && marker <= 0xcf);

    if (isStartOfFrame) {
      return {
        width: buffer.readUInt16BE(offset + 5),
        height: buffer.readUInt16BE(offset + 3),
      };
    }

    offset += segmentLength;
  }

  return null;
}

function readWebpSize(buffer) {
  if (
    buffer.subarray(0, 4).toString("ascii") !== "RIFF" ||
    buffer.subarray(8, 12).toString("ascii") !== "WEBP"
  ) {
    return null;
  }

  const chunkType = buffer.subarray(12, 16).toString("ascii");
  if (chunkType === "VP8X") {
    return {
      width: readUint24LE(buffer, 24) + 1,
      height: readUint24LE(buffer, 27) + 1,
    };
  }

  if (chunkType === "VP8L") {
    const bits = buffer.readUInt32LE(21);
    return {
      width: (bits & 0x3fff) + 1,
      height: ((bits >> 14) & 0x3fff) + 1,
    };
  }

  if (chunkType === "VP8 ") {
    return {
      width: buffer.readUInt16LE(26) & 0x3fff,
      height: buffer.readUInt16LE(28) & 0x3fff,
    };
  }

  return null;
}

export function readImageSize(buffer) {
  const size =
    readPngSize(buffer) ||
    readJpegSize(buffer) ||
    readGifSize(buffer) ||
    readWebpSize(buffer);

  if (!size) {
    throw new Error("Unsupported image format");
  }

  return size;
}

export function readImageSizeFromFile(fileUrl) {
  return readImageSize(readFileSync(fileUrl));
}

export function loadImagesModule(source) {
  return runInNewContext(`${source}\nimages;`, {});
}

export function applyImageMetadata(images, rootUrl = repoRoot) {
  return images.map((image) => {
    const sourceSize = readImageSizeFromFile(new URL(image.src, rootUrl));
    const nextImage = {
      ...image,
      width: sourceSize.width,
      height: sourceSize.height,
    };

    if (image.thumb) {
      const thumbSize = readImageSizeFromFile(new URL(image.thumb, rootUrl));
      nextImage.thumbWidth = thumbSize.width;
      nextImage.thumbHeight = thumbSize.height;
    }

    return nextImage;
  });
}

export function formatImagesModule(images) {
  const orderedKeys = [
    "src",
    "thumb",
    "alt",
    "width",
    "height",
    "thumbWidth",
    "thumbHeight",
  ];
  const lines = [
    "// src: 原图（viewer.html 大图查看用）；thumb: 压缩缩略图（index.html 瀑布流用）；width/height: 自动生成的真实尺寸",
    "const images = [",
  ];

  for (const image of images) {
    lines.push("  {");
    for (const key of orderedKeys) {
      if (image[key] !== undefined) {
        lines.push(`    ${key}: ${JSON.stringify(image[key])},`);
      }
    }
    for (const [key, value] of Object.entries(image)) {
      if (!orderedKeys.includes(key)) {
        lines.push(`    ${key}: ${JSON.stringify(value)},`);
      }
    }
    lines.push("  },");
  }

  lines.push("];", "");
  return lines.join("\n");
}

export function updateImageMetadata({ check = false } = {}) {
  const currentSource = readFileSync(imagesFile, "utf8");
  const images = loadImagesModule(currentSource);
  const nextSource = formatImagesModule(applyImageMetadata(images, repoRoot));

  if (currentSource === nextSource) {
    return false;
  }

  if (check) {
    throw new Error(
      "resume-awards/images.js has stale image dimensions. Run: node scripts/update-image-metadata.mjs",
    );
  }

  writeFileSync(imagesFile, nextSource);
  return true;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const changed = updateImageMetadata({
      check: process.argv.includes("--check"),
    });
    console.log(changed ? "Updated image metadata" : "Image metadata already up to date");
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
