import { readFileSync } from "node:fs";
import { compileNote } from "./markdown.mjs";

/** /content/notes/*.md → `export const meta / html` 纯导出模块。
    同一 md 服务两个模块 id:裸 id 出 meta+html 双导出(懒加载分包消费),
    `?meta` 查询只出 meta——Rollup 对「同模块既 eager 又 dynamic import」
    会报 INEFFECTIVE_DYNAMIC_IMPORT 并拒绝分包(正文全量进主包),
    拆成两个 id 才能让主包物理上不含 html、正文按文章分包。 */
export function mdNotes() {
  return {
    name: "md-notes",
    enforce: "pre",
    load(id) {
      const [file, query] = id.split("?");
      if (!/\/content\/notes\/[^/]+\.md$/.test(file)) return null;
      const { meta, html } = compileNote(readFileSync(file, "utf8"));
      // compileNote 永不 throw(无/未闭合 frontmatter 时 meta={}),这里是构建期
      // 唯一能拦住「页面标题渲染 undefined」的地方——必填键缺失即 fail loud,
      // 两个分支都过守卫:坏 md 不能因先被 ?meta 消费而漏检。
      for (const key of ["title", "date", "summary"]) {
        if (!meta[key]) {
          throw new Error(`md-notes: ${file} 缺少必填 frontmatter 键(title/date/summary)`);
        }
        // 数据层按字符串排序,只有定宽 YYYY-MM-DD 能保证字典序=时间序,
        // `2026-7-5` 这类会静默错序——格式偏差也在构建期拦下。
        if (key === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(meta.date)) {
          throw new Error(
            `md-notes: ${file} date 须为 YYYY-MM-DD(字符串排序依赖定宽格式),实际为 "${meta.date}"`,
          );
        }
      }
      // dev/HMR 可能在查询串追加 &t= 等参数,精确比较会漏匹配——按参数集合判定
      if (new URLSearchParams(query).has("meta")) {
        return {
          code: `export const meta = ${JSON.stringify(meta)};`,
          moduleSideEffects: false,
        };
      }
      return {
        code: `export const meta = ${JSON.stringify(meta)};\nexport const html = ${JSON.stringify(html)};`,
        moduleSideEffects: false,
      };
    },
  };
}
