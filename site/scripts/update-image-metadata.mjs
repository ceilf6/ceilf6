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
  // 首块须是完整的 IHDR:4 字节长度(=13) + "IHDR" + 13 字节数据 + 4 字节 CRC,共到第 33 字节
  if (
    buffer.length < 33 ||
    buffer.readUInt32BE(8) !== 13 ||
    buffer.toString("ascii", 12, 16) !== "IHDR"
  ) {
    throw corrupt("PNG");
  }
  // 遍历块结构(只读块头,不解压):每块 4 字节长度 + 4 字节类型 + 数据 + 4 字节 CRC 都须落在文件内,
  // 且以 IEND 收尾——首块残缺、中途截断、缺少收尾都会在这里暴露
  let chunk = 8;
  let ended = false;
  while (chunk + 12 <= buffer.length) {
    const next = chunk + 12 + buffer.readUInt32BE(chunk);
    if (next > buffer.length) throw corrupt("PNG");
    if (buffer.toString("ascii", chunk + 4, chunk + 8) === "IEND") {
      ended = true;
      break;
    }
    chunk = next;
  }
  if (!ended) throw corrupt("PNG");

  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
  };
}

function readGifSize(buffer) {
  const signature = buffer.subarray(0, 6).toString("ascii");
  if (signature !== "GIF87a" && signature !== "GIF89a") return null;
  // 头部 = 6 字节签名 + 7 字节逻辑屏幕描述符
  if (buffer.length < 13) throw corrupt("GIF");

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
      // SOF 段头 = 长度 2 + 精度 1 + 高 2 + 宽 2 + 分量数 1:声明长度装不下就是损坏,不能越界去读后面的字节
      if (segmentLength < 8 || offset + 7 > buffer.length) throw corrupt("JPEG");
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
  // 格式已识别但文件头里的宽高为 0:同样是损坏,不能当作「尺寸未知」放行
  if (!(size.width > 0 && size.height > 0)) {
    throw new Error("Corrupt image: zero width or height");
  }

  return size;
}

// EXIF Orientation(IFD0 的 0x0112 标签);读不到时按 1(不旋转)处理
function exifOrientation(tiff) {
  if (tiff.length < 8) return 1;
  const order = tiff.toString("ascii", 0, 2);
  if (order !== "II" && order !== "MM") return 1;
  const le = order === "II";
  const u16 = (o) => (le ? tiff.readUInt16LE(o) : tiff.readUInt16BE(o));
  const u32 = (o) => (le ? tiff.readUInt32LE(o) : tiff.readUInt32BE(o));
  const ifd = u32(4);
  if (ifd + 2 > tiff.length) return 1;
  const count = u16(ifd);
  for (let i = 0; i < count; i += 1) {
    const entry = ifd + 2 + i * 12;
    if (entry + 12 > tiff.length) return 1;
    if (u16(entry) === 0x0112) return u16(entry + 8);
  }
  return 1;
}

function readJpegOrientation(buffer) {
  if (buffer[0] !== 0xff || buffer[1] !== 0xd8) return 1;
  let offset = 2;
  while (offset + 4 <= buffer.length) {
    while (buffer[offset] === 0xff) offset += 1;
    const marker = buffer[offset];
    offset += 1;
    if (marker === 0xd9 || marker === 0xda) break;
    const segmentLength = buffer.readUInt16BE(offset);
    if (segmentLength < 2 || offset + segmentLength > buffer.length) break;
    if (marker === 0xe1 && buffer.toString("latin1", offset + 2, offset + 8) === "Exif\0\0") {
      return exifOrientation(buffer.subarray(offset + 8, offset + segmentLength));
    }
    offset += segmentLength;
  }
  return 1;
}

/** 按浏览器实际显示方向的尺寸:JPEG 的 EXIF 方向为 5–8(旋转 90°/270°)时交换宽高。
    札记构建据此写宽高比,竖拍照片放进并排组才能等高;awards 元数据仍用编码尺寸 readImageSize。 */
export function readImageDisplaySize(buffer) {
  const size = readImageSize(buffer);
  const orientation = readJpegOrientation(buffer);
  return orientation >= 5 && orientation <= 8
    ? { width: size.height, height: size.width }
    : size;
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
