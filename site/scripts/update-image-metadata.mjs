import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const publicRoot = new URL("../public/", import.meta.url);
const awardsFile = new URL("../src/data/awards.json", import.meta.url);

// 签名已识别但数据不全:与「不认识的格式」区分开,调用方可据此判定为损坏文件
function corrupt(format) {
  return new Error(`Corrupt ${format} image`);
}

function readUint24LE(buffer, offset) {
  return buffer[offset] | (buffer[offset + 1] << 8) | (buffer[offset + 2] << 16);
}

function readPngSize(buffer) {
  const pngSignature = "89504e470d0a1a0a";
  if (buffer.subarray(0, 8).toString("hex") !== pngSignature) return null;
  if (buffer.length < 24) throw corrupt("PNG");
  // 完整的 PNG 以 IEND 块收尾(4 字节长度 + "IEND" + 4 字节 CRC)
  if (buffer.subarray(-8, -4).toString("ascii") !== "IEND") throw corrupt("PNG");

  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
  };
}

function readGifSize(buffer) {
  const signature = buffer.subarray(0, 6).toString("ascii");
  if (signature !== "GIF87a" && signature !== "GIF89a") return null;
  if (buffer.length < 10) throw corrupt("GIF");

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
      if (offset + 7 > buffer.length) throw corrupt("JPEG");
      // 完整的 JPEG 以 EOI(FFD9)收尾;个别编码器会在末尾补 0x00,先去掉
      let end = buffer.length;
      while (end > 0 && buffer[end - 1] === 0x00) end -= 1;
      if (end < 2 || buffer[end - 2] !== 0xff || buffer[end - 1] !== 0xd9) throw corrupt("JPEG");
      return {
        width: buffer.readUInt16BE(offset + 5),
        height: buffer.readUInt16BE(offset + 3),
      };
    }

    offset += segmentLength;
  }

  // SOI 已识别,却在找到尺寸帧(SOF)之前结束:文件截断或损坏
  throw corrupt("JPEG");
}

function readWebpSize(buffer) {
  if (
    buffer.subarray(0, 4).toString("ascii") !== "RIFF" ||
    buffer.subarray(8, 12).toString("ascii") !== "WEBP"
  ) {
    return null;
  }

  const chunkType = buffer.subarray(12, 16).toString("ascii");
  // 各分支读取的最远字节:VP8X 到 30、VP8L 到 25、VP8 到 30;不足即截断
  const need = { VP8X: 30, VP8L: 25, "VP8 ": 30 }[chunkType];
  if (!need || buffer.length < need) throw corrupt("WebP");
  // RIFF 头声明的数据长度(不含开头 8 字节)超出实际字节数:文件后半截缺失
  if (buffer.readUInt32LE(4) + 8 > buffer.length) throw corrupt("WebP");
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

export function loadAwards(source) {
  return JSON.parse(source);
}

// awards.json 里的 src/thumb 是站点绝对路径（/resume-awards/...），实际文件在 site/public/ 下
export function resolvePublicUrl(publicPath, rootUrl = publicRoot) {
  return new URL(publicPath.replace(/^\//, ""), rootUrl);
}

export function applyImageMetadata(images, rootUrl = publicRoot) {
  return images.map((image) => {
    const sourceSize = readImageSizeFromFile(resolvePublicUrl(image.src, rootUrl));
    const nextImage = {
      ...image,
      width: sourceSize.width,
      height: sourceSize.height,
    };

    if (image.thumb) {
      const thumbSize = readImageSizeFromFile(resolvePublicUrl(image.thumb, rootUrl));
      nextImage.thumbWidth = thumbSize.width;
      nextImage.thumbHeight = thumbSize.height;
    }

    return nextImage;
  });
}

export function formatAwards(images) {
  const orderedKeys = [
    "src",
    "thumb",
    "alt",
    "width",
    "height",
    "thumbWidth",
    "thumbHeight",
  ];
  const ordered = images.map((image) => {
    const next = {};
    for (const key of orderedKeys) {
      if (image[key] !== undefined) {
        next[key] = image[key];
      }
    }
    for (const [key, value] of Object.entries(image)) {
      if (!orderedKeys.includes(key)) {
        next[key] = value;
      }
    }
    return next;
  });

  return `${JSON.stringify(ordered, null, 2)}\n`;
}

export function updateImageMetadata({ check = false } = {}) {
  const currentSource = readFileSync(awardsFile, "utf8");
  const images = loadAwards(currentSource);
  const nextSource = formatAwards(applyImageMetadata(images, publicRoot));

  if (currentSource === nextSource) {
    return false;
  }

  if (check) {
    throw new Error(
      "site/src/data/awards.json has stale image dimensions. Run: node site/scripts/update-image-metadata.mjs",
    );
  }

  writeFileSync(awardsFile, nextSource);
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
