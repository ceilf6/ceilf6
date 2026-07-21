import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  loadImagesModule,
  readImageSizeFromFile,
  updateImageMetadata,
} from "./update-image-metadata.mjs";

const repoRoot = new URL("../", import.meta.url);
const imagesFile = new URL("../resume-awards/images.js", import.meta.url);

export const MAX_EDGE = 900;
const JPEG_QUALITY = 80;

export function resolveThumbStatus({
  thumbExists,
  sourceMtimeMs,
  thumbMtimeMs,
  force = false,
}) {
  if (!thumbExists) return "missing";
  if (force) return "forced";
  return sourceMtimeMs > thumbMtimeMs ? "stale" : null;
}

// 原图短于目标边长时不放大，否则缩略图只会更糊更大
export function planResize(size, maxEdge = MAX_EDGE) {
  return Math.max(size.width, size.height) > maxEdge ? maxEdge : null;
}

export function planThumbnails(images, { rootUrl = repoRoot, force = false } = {}) {
  const tasks = [];

  for (const image of images) {
    if (!image.thumb) continue;

    const source = new URL(image.src, rootUrl);
    const thumb = new URL(image.thumb, rootUrl);
    const thumbExists = existsSync(thumb);
    const status = resolveThumbStatus({
      thumbExists,
      sourceMtimeMs: statSync(source).mtimeMs,
      thumbMtimeMs: thumbExists ? statSync(thumb).mtimeMs : 0,
      force,
    });

    if (status) {
      tasks.push({ source, thumb, status, label: image.thumb });
    }
  }

  return tasks;
}

function hasBinary(name) {
  try {
    execFileSync("which", [name], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function renderWithSips(source, thumb, maxEdge) {
  const args = maxEdge ? ["-Z", String(maxEdge)] : [];
  args.push(
    "-s",
    "format",
    "jpeg",
    "-s",
    "formatOptions",
    String(JPEG_QUALITY),
    fileURLToPath(source),
    "--out",
    fileURLToPath(thumb),
  );
  execFileSync("sips", args, { stdio: "ignore" });
}

function createMagickRenderer(binary) {
  return (source, thumb, maxEdge) => {
    const args = [fileURLToPath(source), "-auto-orient"];
    if (maxEdge) args.push("-resize", `${maxEdge}x${maxEdge}>`);
    args.push("-quality", String(JPEG_QUALITY), fileURLToPath(thumb));
    execFileSync(binary, args, { stdio: "ignore" });
  };
}

export function resolveRenderer() {
  if (process.platform === "darwin" && existsSync("/usr/bin/sips")) {
    return renderWithSips;
  }

  for (const binary of ["magick", "convert"]) {
    if (hasBinary(binary)) return createMagickRenderer(binary);
  }

  throw new Error(
    "No image tool available. Install ImageMagick (magick/convert) or run on macOS (sips).",
  );
}

export function generateThumbs({ force = false } = {}) {
  const images = loadImagesModule(readFileSync(imagesFile, "utf8"));
  const tasks = planThumbnails(images, { rootUrl: repoRoot, force });
  if (tasks.length === 0) return tasks;

  const render = resolveRenderer();

  for (const task of tasks) {
    mkdirSync(new URL(".", task.thumb), { recursive: true });
    render(task.source, task.thumb, planResize(readImageSizeFromFile(task.source)));
  }

  return tasks;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const tasks = generateThumbs({ force: process.argv.includes("--force") });

    for (const task of tasks) {
      console.log(`${task.status.padEnd(7)} ${task.label}`);
    }

    console.log(
      tasks.length
        ? `Generated ${tasks.length} thumbnail(s)`
        : "Thumbnails already up to date",
    );

    if (updateImageMetadata()) {
      console.log("Updated image metadata");
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
