import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { compileNote } from "./markdown.mjs";
import { readImageSize } from "./update-image-metadata.mjs";

const inside = (root, p) => {
  const r = relative(root, p);
  // 按完整路径段判断:..draft.webp 是普通文件名,不是上级目录
  return r !== "" && r !== ".." && !r.startsWith(`..${sep}`) && !isAbsolute(r);
};

/** 站内绝对路径图片 → 读 <site>/public 下的文件头取尺寸;外链返回 null 不写尺寸。
    - 解析后(含符号链接)须仍在 public 内,否则构建失败:札记不能让构建读到发布目录之外;
    - /notes/ 是札记配图的约定目录,缺图即构建失败(断图不能静默上线);
      其余站内路径(如构建期另行打包的 /assets/)在 public 里找不到时不写尺寸、照常输出;
    - 尺寸读取器不认识的格式(SVG 等)不写尺寸,不阻断构建。 */
function publicImageSize(file) {
  const publicDir = file.replace(/\/content\/notes\/[^/]+\.md$/, "/public");
  return (src) => {
    if (!src.startsWith("/") || src.startsWith("//")) return null;
    const pathname = decodeURI(src.split(/[?#]/)[0]);
    const target = resolve(publicDir, `.${pathname}`);
    if (!inside(publicDir, target)) {
      throw new Error(`md-notes: ${file} 引用的图片路径越出 public: ${src}`);
    }
    if (!existsSync(target)) {
      // 按规范化后的目标判定(/assets/../notes/x 与 /notes/x 是同一资源)
      if (inside(resolve(publicDir, "notes"), target)) {
        throw new Error(`md-notes: ${file} 引用的站内图片不存在: ${src}`);
      }
      return null;
    }
    const real = realpathSync(target);
    if (!inside(realpathSync(publicDir), real)) {
      throw new Error(`md-notes: ${file} 引用的图片路径越出 public: ${src}`);
    }
    if (!statSync(real).isFile()) {
      throw new Error(`md-notes: ${file} 引用的站内图片不是文件: ${src}`);
    }
    const buf = readFileSync(real); // 读取错误照常抛出,只放过下面的格式识别失败
    try {
      return readImageSize(buf);
    } catch {
      return null; // 读取器不支持的格式(如 SVG)不写尺寸,照常输出
    }
  };
}

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
      const { meta, html } = compileNote(readFileSync(file, "utf8"), {
        imageSize: publicImageSize(file),
      });
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
