import { readFileSync } from "node:fs";
import { compileNote } from "./markdown.mjs";

/** /content/notes/*.md → `export const meta / html` 纯导出模块。
    moduleSideEffects:false 让只 import meta 的主包把 html 字符串摇树掉，
    文章正文只进 /notes/:slug 的懒加载分包。 */
export function mdNotes() {
  return {
    name: "md-notes",
    enforce: "pre",
    load(id) {
      if (!/\/content\/notes\/[^/]+\.md$/.test(id)) return null;
      const { meta, html } = compileNote(readFileSync(id, "utf8"));
      // compileNote 永不 throw(无/未闭合 frontmatter 时 meta={}),这里是构建期
      // 唯一能拦住「页面标题渲染 undefined」的地方——必填键缺失即 fail loud。
      for (const key of ["title", "date", "summary"]) {
        if (!meta[key]) {
          throw new Error(`md-notes: ${id} 缺少必填 frontmatter 键(title/date/summary)`);
        }
      }
      return {
        code: `export const meta = ${JSON.stringify(meta)};\nexport const html = ${JSON.stringify(html)};`,
        moduleSideEffects: false,
      };
    },
  };
}
