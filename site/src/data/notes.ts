/** 站内札记数据层。meta 走 eager glob 进主包,正文 html 走懒 glob,
    每篇文章一个分包,只在 /notes/:slug 加载。eager 侧必须带 ?meta 查询:
    同一模块 id 既 eager 又 dynamic 会让 Rollup 拒绝分包(INEFFECTIVE_DYNAMIC_IMPORT),
    ?meta 使两侧成为不同模块,插件对该查询只 emit meta,主包物理上不含正文。 */
import type { NoteFrontmatter, NoteModule } from "./note-module";

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

export function buildNotes(metas: Record<string, NoteFrontmatter>): NoteMeta[] {
  return Object.entries(metas)
    .map(([path, m]) => ({
      slug: slugFromPath(path),
      title: m.title,
      date: m.date,
      summary: m.summary,
      source: m.source ?? "站内",
      sourceUrl: m.sourceUrl ?? "",
    }))
    // localeCompare 相等返回 0:满足比较器契约,稳定排序保住同日文章的 glob 键序
    .sort((a, b) => b.date.localeCompare(a.date));
}

const metaModules = import.meta.glob<NoteFrontmatter>("/content/notes/*.md", {
  eager: true,
  import: "meta",
  query: "?meta", // 勿删:去掉即 INEFFECTIVE_DYNAMIC_IMPORT,正文回灌主包(见文件头)
});

export const notes: NoteMeta[] = buildNotes(metaModules);

const htmlModules = import.meta.glob<NoteModule["html"]>("/content/notes/*.md", {
  import: "html",
});

export function loadNoteHtml(slug: string): Promise<string> | null {
  const entry = Object.entries(htmlModules).find(([p]) => slugFromPath(p) === slug);
  return entry ? entry[1]() : null;
}
