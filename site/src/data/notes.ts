/** 站内札记数据层。meta 走 eager glob 进主包(插件产物无副作用,html 被摇树);
    正文 html 走懒 glob,每篇文章一个分包,只在 /notes/:slug 加载。 */
import type { NoteModule } from "./note-module";

export interface NoteMeta {
  slug: string;
  title: string;
  date: string;
  summary: string;
  source: string;
  sourceUrl: string;
}

export function slugFromPath(path: string): string {
  return path.split("/").pop()!.replace(/\.md$/, "");
}

export function buildNotes(mods: Record<string, NoteModule["meta"]>): NoteMeta[] {
  return Object.entries(mods)
    .map(([path, m]) => ({
      slug: slugFromPath(path),
      title: m.title,
      date: m.date,
      summary: m.summary,
      source: m.source ?? "站内",
      sourceUrl: m.sourceUrl ?? "",
    }))
    .sort((a, b) => (a.date < b.date ? 1 : -1));
}

const metaModules = import.meta.glob<NoteModule["meta"]>("/content/notes/*.md", {
  eager: true,
  import: "meta",
});

export const notes: NoteMeta[] = buildNotes(metaModules);

const htmlModules = import.meta.glob<NoteModule["html"]>("/content/notes/*.md", {
  import: "html",
});

export function loadNoteHtml(slug: string): Promise<string> | null {
  const entry = Object.entries(htmlModules).find(([p]) => slugFromPath(p) === slug);
  return entry ? entry[1]() : null;
}
