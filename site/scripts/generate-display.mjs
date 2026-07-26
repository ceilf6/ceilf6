import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

import {
  loadAwards,
  readImageSizeFromFile,
  resolvePublicUrl,
} from "./update-image-metadata.mjs";
import { planResize, resolveRenderer, resolveThumbStatus } from "./generate-thumbs.mjs";

const publicRoot = new URL("../public/", import.meta.url);
const awardsFile = new URL("../src/data/awards.json", import.meta.url);

/** viewer 展示级渲染：原件（数 MB 的扫描 PNG/JPG）压成长边 2000 的 jpeg，
    体积降一个量级；原件仍在原路径，viewer 里「查看原件」直达（求证口径不变）。 */
export const DISPLAY_MAX_EDGE = 2000;
const DISPLAY_PREFIX = "/resume-awards/imgs/display/";

export function displayPathFor(src) {
  const base = src.split("/").pop().replace(/\.[^.]+$/, "");
  return `${DISPLAY_PREFIX}${base}.jpg`;
}

export function generateDisplay({ force = false } = {}) {
  const images = loadAwards(readFileSync(awardsFile, "utf8"));
  const tasks = [];
  let manifestChanged = false;
  let render = null;

  for (const image of images) {
    const displayPath = displayPathFor(image.src);
    if (image.display !== displayPath) {
      image.display = displayPath;
      manifestChanged = true;
    }

    const source = resolvePublicUrl(image.src, publicRoot);
    const out = resolvePublicUrl(displayPath, publicRoot);
    const outExists = existsSync(out);
    const status = resolveThumbStatus({
      thumbExists: outExists,
      sourceMtimeMs: statSync(source).mtimeMs,
      thumbMtimeMs: outExists ? statSync(out).mtimeMs : 0,
      force,
    });

    if (status) {
      render ??= resolveRenderer();
      mkdirSync(new URL(".", out), { recursive: true });
      render(source, out, planResize(readImageSizeFromFile(source), DISPLAY_MAX_EDGE));
      tasks.push({ status, label: displayPath });
    }
  }

  if (manifestChanged) {
    writeFileSync(awardsFile, `${JSON.stringify(images, null, 2)}\n`);
  }

  return { tasks, manifestChanged };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const { tasks, manifestChanged } = generateDisplay({
      force: process.argv.includes("--force"),
    });

    for (const task of tasks) {
      console.log(`${task.status.padEnd(7)} ${task.label}`);
    }

    console.log(
      tasks.length
        ? `Generated ${tasks.length} display rendition(s)`
        : "Display renditions already up to date",
    );
    if (manifestChanged) console.log("Updated awards manifest display fields");
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
