/** 站内札记的最小 Markdown 编译器:只在构建期跑(vite 插件调用),
    运行时零解析器。刻意只支持文章实际用到的子集,先转义再替换防注入。 */

export function parseFrontmatter(src) {
  // 容忍 CRLF(与 mdToHtml 的归一化一致,否则 Windows 文件静默丢 frontmatter);
  // 闭合定界符锚定行尾,防 "----"/"---extra" 误闭合。
  const m = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/.exec(src);
  if (!m) return { meta: {}, body: src };
  const meta = {};
  for (const line of m[1].split("\n")) {
    const i = line.indexOf(":");
    if (i === -1) continue;
    meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return { meta, body: src.slice(m[0].length) };
}

const esc = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// 行内原子占位符的定界符:NUL 不可能出现在合法文本里。
// 用 fromCharCode 而非字面转义,避免源码里混入原始控制字节(git 会误判二进制)。
const NUL = String.fromCharCode(0);
const PLACEHOLDER = new RegExp(`${NUL}(\\d+)${NUL}`, "g");

// 图片块:整行只由图片构成(可多张、可分多行)时不走段落,输出 figure。
const IMAGE = /!\[([^\]]*)\]\(([^)\s]+)\)/g;
const IMAGE_LINE = /^\s*(?:!\[[^\]]*\]\([^)\s]+\)\s*)+$/;
const HR = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;

/** imageSize(src) → {width,height} | null:构建期由插件注入(读 public/ 文件头),
    写入 width/height 让浏览器预留版面、避免加载时跳动。图片块(单图/gallery)另带
    宽高比 --r:gallery 按 --r 分配 flex 宽度,使宽高比不同的图并排时同一行等高;
    单图据此限高,长截图不至于撑满一屏。 */
function imgTag(alt, src, opts, inBlock = false) {
  const size = opts.imageSize?.(src) ?? null;
  let attrs = `alt="${esc(alt)}" src="${esc(src)}"`;
  if (size) {
    attrs += ` width="${size.width}" height="${size.height}"`;
    if (inBlock) attrs += ` style="--r:${Number((size.width / size.height).toFixed(4))}"`;
  }
  return `<img ${attrs} loading="lazy">`;
}

function imageBlock(lines, opts) {
  const imgs = [...lines.join(" ").matchAll(IMAGE)];
  if (imgs.length === 1) {
    return `<figure class="note-figure">${imgTag(imgs[0][1], imgs[0][2], opts, true)}</figure>`;
  }
  return `<figure class="note-gallery">${imgs.map((m) => imgTag(m[1], m[2], opts, true)).join("")}</figure>`;
}

function inline(s, opts = {}) {
  // 行内原子(code/img/link)统一抽成占位符:已生成的标记若留在原文流里,
  // 后跑的 strong/em 会跨标签边界配对(href/alt 里的 * 也会被撕开)。
  // 进料先剔除杂散 NUL,保证占位符定界唯一、回填循环不空转。
  s = s.split(NUL).join("");
  const atoms = [];
  const stash = (html) => NUL + (atoms.push(html) - 1) + NUL;
  const em = (t) =>
    t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*([^*]+)\*/g, "<em>$1</em>");
  s = s
    .replace(/`([^`]+)`/g, (_, c) => stash(`<code>${esc(c)}</code>`))
    .replace(IMAGE, (_, alt, src) => stash(imgTag(alt, src, opts)))
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, text, href) =>
      // 链接文本自身要吃 strong/em(如 [**a**](b)),href 保持原样
      stash(
        `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${em(esc(text))}</a>`,
      ),
    );
  s = em(esc(s));
  // 链接文本可能内嵌 code 占位符(嵌套 stash),回填须循环——replace 不重扫替换进来的文本
  while (s.includes(NUL)) s = s.replace(PLACEHOLDER, (_, i) => atoms[i]);
  return s;
}

export function mdToHtml(md, opts = {}) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++; // 收尾围栏
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      // 文内标题降一级:文章页 h1 归 frontmatter title
      const lv = h[1].length + 1;
      out.push(`<h${lv}>${inline(h[2], opts)}</h${lv}>`);
      i++;
      continue;
    }
    if (HR.test(line)) {
      out.push("<hr>");
      i++;
      continue;
    }
    if (IMAGE_LINE.test(line)) {
      const buf = [];
      while (i < lines.length && IMAGE_LINE.test(lines[i])) buf.push(lines[i++]);
      out.push(imageBlock(buf, opts));
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i]))
        items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      out.push(`<ul>${items.map((t) => `<li>${inline(t, opts)}</li>`).join("")}</ul>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote><p>${inline(buf.join(" "), opts)}</p></blockquote>`);
      continue;
    }
    if (line.trim() === "") {
      i++;
      continue;
    }
    const buf = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^(#{1,3})\s|^\s*[-*]\s|^>|^```/.test(lines[i]) &&
      !HR.test(lines[i]) &&
      !IMAGE_LINE.test(lines[i])
    )
      buf.push(lines[i++]);
    out.push(`<p>${inline(buf.join(" "), opts)}</p>`);
  }
  return out.join("\n");
}

export function compileNote(src, opts = {}) {
  const { meta, body } = parseFrontmatter(src);
  return { meta, html: mdToHtml(body, opts) };
}
