import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const defaultNotesDir = new URL("../content/notes/", import.meta.url);
const defaultManifestFile = new URL(
  "../server/comments/note_slugs.json",
  import.meta.url,
);

// 与 site/src/data/notes.ts 的 slugFromPath(path) 保持 100% 一致
export function slugFromNotePath(path) {
  return String(path).replace(/\\/g, "/").split("/").pop().replace(/\.md$/, "");
}

export function discoverNoteSlugs(notesDir = defaultNotesDir) {
  return readdirSync(notesDir, { withFileTypes: true })
    .filter(
      (entry) =>
        entry.isFile() &&
        !entry.name.startsWith(".") &&
        entry.name.endsWith(".md"),
    )
    .map((entry) => slugFromNotePath(`/content/notes/${entry.name}`))
    .sort();
}

export function formatNoteSlugs(slugs) {
  return `${JSON.stringify(slugs, null, 2)}\n`;
}

export function updateNoteSlugs({
  check = false,
  notesDir = defaultNotesDir,
  manifestFile = defaultManifestFile,
} = {}) {
  const slugs = discoverNoteSlugs(notesDir);
  if (slugs.length === 0) {
    throw new Error("No markdown notes found under site/content/notes/");
  }

  const nextSource = formatNoteSlugs(slugs);
  const currentSource = existsSync(manifestFile)
    ? readFileSync(manifestFile, "utf8")
    : "";

  if (currentSource === nextSource) {
    return false;
  }

  if (check) {
    throw new Error(
      "site/server/comments/note_slugs.json is out of sync with site/content/notes/*.md. Run: node site/scripts/update-note-slugs.mjs",
    );
  }

  writeFileSync(manifestFile, nextSource, "utf8");
  return true;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const changed = updateNoteSlugs({
      check: process.argv.includes("--check"),
    });
    console.log(
      changed
        ? "Updated note slugs manifest"
        : "Note slugs manifest already up to date",
    );
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
