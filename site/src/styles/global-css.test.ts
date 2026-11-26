import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import rawGlobalCss from "./global.css?raw";

const globalCssSource =
  rawGlobalCss ||
  readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");

interface CssRuleBlock {
  prelude: string;
  body: string;
  rawBlock: string;
}

function stripCssComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function parseTopLevelBlocks(css: string): CssRuleBlock[] {
  const blocks: CssRuleBlock[] = [];
  let i = 0;
  while (i < css.length) {
    const openIdx = css.indexOf("{", i);
    if (openIdx === -1) break;
    const prelude = css.slice(i, openIdx).trim();
    let depth = 1;
    let j = openIdx + 1;
    let inQuote: string | null = null;
    while (j < css.length && depth > 0) {
      const ch = css[j];
      if (inQuote) {
        if (ch === "\\" && j + 1 < css.length) {
          j += 2;
          continue;
        }
        if (ch === inQuote) inQuote = null;
      } else if (ch === '"' || ch === "'") {
        inQuote = ch;
      } else if (ch === "{") {
        depth += 1;
      } else if (ch === "}") {
        depth -= 1;
      }
      j += 1;
    }
    const body = css.slice(openIdx + 1, j - 1);
    const rawBlock = css.slice(i, j);
    blocks.push({ prelude, body, rawBlock });
    i = j;
  }
  return blocks;
}

describe("global.css 根滚动条常驻与窗帘防退化守卫", () => {
  it("剥离注释后校验 html/body 溢出职责、webkit 滚动条保留及 Firefox @supports 隔离", () => {
    const cleanCss = stripCssComments(globalCssSource);
    expect(cleanCss.length).toBeGreaterThan(100);
    const topBlocks = parseTopLevelBlocks(cleanCss);

    // 1) 顶层 html 规则含 overflow-y: scroll 与 overflow-x: hidden
    const htmlBlocks = topBlocks.filter((b) => b.prelude === "html");
    expect(htmlBlocks).toHaveLength(1);
    expect(htmlBlocks[0].body).toMatch(/overflow-y:\s*scroll\s*;/);
    expect(htmlBlocks[0].body).toMatch(/overflow-x:\s*hidden\s*;/);

    // 2) 顶层 body 规则不含任何 overflow 声明（防止 body 变成滚动容器破坏首页 sticky 窗帘）
    const bodyBlocks = topBlocks.filter((b) => b.prelude === "body");
    expect(bodyBlocks).toHaveLength(1);
    expect(bodyBlocks[0].body).not.toContain("overflow");

    // 3) 自定义 ::-webkit-scrollbar 规则保持存在
    const webkitScrollbarBlocks = topBlocks.filter(
      (b) => b.prelude === "::-webkit-scrollbar",
    );
    expect(webkitScrollbarBlocks).toHaveLength(1);

    // 4) scrollbar-color 仅出现在 @supports not selector(::-webkit-scrollbar) 块内，块外零出现
    const supportsBlocks = topBlocks.filter(
      (b) =>
        b.prelude.replace(/\s+/g, " ") ===
        "@supports not selector(::-webkit-scrollbar)",
    );
    expect(supportsBlocks).toHaveLength(1);
    expect(supportsBlocks[0].body).toContain("scrollbar-color");

    const outsideSupports = topBlocks
      .filter((b) => b !== supportsBlocks[0])
      .map((b) => b.rawBlock)
      .join("\n");
    expect(outsideSupports).not.toContain("scrollbar-color");
  });
});
