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
      return {
        code: `export const meta = ${JSON.stringify(meta)};\nexport const html = ${JSON.stringify(html)};`,
        moduleSideEffects: false,
      };
    },
  };
}
