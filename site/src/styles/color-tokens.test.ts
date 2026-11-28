import { existsSync, readdirSync, readFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

function resolveSiteDir(): string {
  const cwd = process.cwd();
  return existsSync(resolve(cwd, "src/styles/tokens.css"))
    ? cwd
    : resolve(cwd, "site");
}

const SITE_DIR = resolveSiteDir();
const SRC_DIR = resolve(SITE_DIR, "src");
const SCRIPTS_DIR = resolve(SITE_DIR, "scripts");
const TOKENS_REL_PATH = "src/styles/tokens.css";

/** 局部锁定为午夜蓝的灯箱根选择器及 Note.css 灯箱内部扁平子元素类名 */
const LOCKED_ROOT_SELECTORS = [".viewer-screen", ".note-zoom"] as const;
const LOCKED_CHILD_CLASS_PREFIXES = [
  ".viewer-screen",
  ".note-zoom",
  ".note-zoom-toggle",
  ".note-zoom-close",
  ".note-zoom-hint",
] as const;

/** D 类豁免：压在用户自选 8 色深色头像底色上的固定白色文字与半透白边 */
const AVATAR_CUSTOM_COLOR_EXEMPTIONS: Readonly<Record<string, ReadonlySet<string>>> = {
  "src/components/CommentAvatar.css": new Set([".comment-avatar.has-custom-color"]),
  "src/components/SiteHeader.css": new Set([".account-trigger.has-custom-color"]),
};

/** E 类豁免：仅在 mask 属性声明中用作 alpha 遮罩的纯白字面量 */
const MASK_PROPERTIES = new Set([
  "mask",
  "-webkit-mask",
  "mask-image",
  "-webkit-mask-image",
]);

/** 运行期 / 构建期写入行内样式的 CSS 自定义属性白名单（每项必须能在源码中反向核对到写入处） */
const RUNTIME_WRITTEN: Readonly<Record<string, string>> = {
  "--brand": "src/components/PlatformStage.tsx",
  "--brand-rgb": "src/components/PlatformStage.tsx",
  "--brand-2-rgb": "src/components/PlatformStage.tsx",
  "--tilt-rx": "src/fx/tilt.ts",
  "--tilt-ry": "src/fx/tilt.ts",
  "--gx": "src/fx/tilt.ts",
  "--gy": "src/fx/tilt.ts",
  "--r": "scripts/markdown.mjs",
};

/** 合法的通道颜色函数调用：仅允许 rgb(var(--x-rgb)) 或 rgba(var(--x-rgb), alpha)，禁止在 var() 内塞字面量回退 */
const VALID_TOKEN_RGB_CALL_RE =
  /^rgba?\(\s*var\(--[a-z0-9-]+-rgb\)\s*(?:,\s*(?:0|1|0?\.\d+|1\.0+)\s*)?\)$/i;

/** 所有 CSS 颜色函数名（含 Color 4 的 hwb / lab / lch / oklch / oklab / color / color-mix） */
const ALL_COLOR_FN_RE =
  /\b(?:rgba?|hsla?|hwb|lab|lch|oklch|oklab|color|color-mix)\s*\(/gi;

/** 常见 CSS 命名色关键字（不含 transparent / currentColor / inherit / none 等非具体色值关键字） */
const NAMED_COLOR_RE =
  /(?:^|[\s,(/:])(white|black|red|green|blue|yellow|orange|purple|pink|cyan|magenta|gold|gray|grey|silver|maroon|olive|lime|aqua|teal|navy|fuchsia|crimson|coral|salmon|khaki|violet|indigo|ivory|beige|wheat|tan|peru|chocolate|firebrick|darkred|darkblue|darkgreen|darkslategray|slategray|lightgray|dimgray|rebeccapurple|hotpink|tomato|dodgerblue|skyblue|steelblue|royalblue|midnightblue|forestgreen|seagreen|turquoise|aquamarine|lavender|plum|orchid|sienna|brown)(?=$|[\s,!);\n])/gi;

/** 全局无宿主限定的伪元素选择器（含 :hover 等伪类后缀，会直接作用到灯箱内部节点及其滚动条/选区） */
const GLOBAL_PSEUDO_ELEMENT_RE =
  /^::(?:selection|-webkit-scrollbar(?:-[a-z-]+)?)(?::[a-z-]+(?:\([^)]*\))?)*$/i;

/** :root 必须声明的复合颜色变量集合（防止漏定义复合令牌而在组件中散落硬编码透明度） */
const REQUIRED_ROOT_COMPOSITES = [
  "--panel-bg",
  "--panel-border",
  "--card-shadow",
  "--page-background",
  "--card-index-fg",
] as const;

interface CssDeclaration {
  file: string;
  line: number;
  selector: string;
  atRule: string | null;
  prop: string;
  value: string;
}

interface CssRule {
  file: string;
  line: number;
  selector: string;
  atRule: string | null;
  declarations: CssDeclaration[];
}

function collectFiles(dir: string, predicate: (name: string) => boolean): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...collectFiles(full, predicate));
    } else if (entry.isFile() && predicate(entry.name)) {
      out.push(full);
    }
  }
  return out.sort();
}

function toPosixRel(fullPath: string): string {
  return relative(SITE_DIR, fullPath).replace(/\\/g, "/");
}

/** 剥离 CSS 注释并保留原换行符，确保报错行号与源文件完全一致 */
function stripCssCommentsPreservingLines(css: string): string {
  let out = "";
  let i = 0;
  let inQuote: string | null = null;
  while (i < css.length) {
    const ch = css[i];
    if (inQuote) {
      out += ch;
      if (ch === "\\" && i + 1 < css.length) {
        out += css[i + 1];
        i += 2;
        continue;
      }
      if (ch === inQuote) inQuote = null;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inQuote = ch;
      out += ch;
      i += 1;
      continue;
    }
    if (ch === "/" && css[i + 1] === "*") {
      const end = css.indexOf("*/", i + 2);
      const sliceEnd = end === -1 ? css.length : end + 2;
      const comment = css.slice(i, sliceEnd);
      out += comment.replace(/[^\n]/g, " ");
      i = sliceEnd;
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

function buildLineStarts(text: string): number[] {
  const starts = [0];
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "\n") starts.push(i + 1);
  }
  return starts;
}

function lineNumberAt(lineStarts: number[], offset: number): number {
  let lo = 0;
  let hi = lineStarts.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lineStarts[mid] <= offset) {
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return hi + 1;
}

function parseDeclarations(
  body: string,
  bodyOffset: number,
  file: string,
  selector: string,
  atRule: string | null,
  lineStarts: number[],
): CssDeclaration[] {
  const decls: CssDeclaration[] = [];
  let start = 0;
  let inQuote: string | null = null;
  let parenDepth = 0;

  const pushSegment = (segStart: number, segEnd: number) => {
    const raw = body.slice(segStart, segEnd);
    const trimmed = raw.trim();
    if (!trimmed) return;
    const unquoted = stripQuotedStrings(raw);
    if (unquoted.includes("{") || unquoted.includes("}")) {
      const line = lineNumberAt(lineStarts, bodyOffset + segStart);
      throw new Error(
        `${file}:${line} (${selector}) 出现未预期的嵌套块，请改为扁平选择器规则以保证颜色门禁完整扫描`,
      );
    }
    const colonIdx = raw.indexOf(":");
    if (colonIdx === -1) return;
    const prop = raw.slice(0, colonIdx).trim();
    const valueSlice = raw.slice(colonIdx + 1);
    const leadingWs = valueSlice.length - valueSlice.trimStart().length;
    const valueOffset = bodyOffset + segStart + colonIdx + 1 + leadingWs;
    const value = valueSlice.trim();
    decls.push({
      file,
      line: lineNumberAt(lineStarts, valueOffset),
      selector,
      atRule,
      prop,
      value,
    });
  };

  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (inQuote) {
      if (ch === "\\" && i + 1 < body.length) {
        i += 1;
        continue;
      }
      if (ch === inQuote) inQuote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inQuote = ch;
    } else if (ch === "(") {
      parenDepth += 1;
    } else if (ch === ")" && parenDepth > 0) {
      parenDepth -= 1;
    } else if (ch === ";" && parenDepth === 0) {
      pushSegment(start, i);
      start = i + 1;
    }
  }
  pushSegment(start, body.length);
  return decls;
}

/** 引号与括号感知地查找下一个顶层 `{` 或语句型 at-rule 的 `;` */
function findNextRuleBoundary(
  css: string,
  fromIdx: number,
): { kind: "block" | "statement"; index: number } | null {
  let inQuote: string | null = null;
  let parenDepth = 0;
  let bracketDepth = 0;
  for (let i = fromIdx; i < css.length; i += 1) {
    const ch = css[i];
    if (inQuote) {
      if (ch === "\\" && i + 1 < css.length) {
        i += 1;
        continue;
      }
      if (ch === inQuote) inQuote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inQuote = ch;
    } else if (ch === "(") {
      parenDepth += 1;
    } else if (ch === ")" && parenDepth > 0) {
      parenDepth -= 1;
    } else if (ch === "[") {
      bracketDepth += 1;
    } else if (ch === "]" && bracketDepth > 0) {
      bracketDepth -= 1;
    } else if (parenDepth === 0 && bracketDepth === 0) {
      if (ch === "{") return { kind: "block", index: i };
      if (ch === ";") return { kind: "statement", index: i };
    }
  }
  return null;
}

function parseCssRules(
  css: string,
  baseOffset: number,
  file: string,
  atRule: string | null,
  lineStarts: number[],
): CssRule[] {
  const rules: CssRule[] = [];
  let i = 0;
  while (i < css.length) {
    const boundary = findNextRuleBoundary(css, i);
    if (!boundary) break;
    if (boundary.kind === "statement") {
      // 跳过 @import / @charset / @layer base; 等以分号结尾的语句型 at-rule
      i = boundary.index + 1;
      continue;
    }
    const openIdx = boundary.index;
    const rawPrelude = css.slice(i, openIdx);
    const leadWs = rawPrelude.length - rawPrelude.trimStart().length;
    const preludeOffset = baseOffset + i + leadWs;
    const prelude = rawPrelude.trim().replace(/\s+/g, " ");

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

    const inner = css.slice(openIdx + 1, j - 1);
    const innerOffset = baseOffset + openIdx + 1;

    if (/^@(?:media|supports|layer|container|scope|starting-style)\b/i.test(prelude)) {
      const nextAt = atRule ? `${atRule} > ${prelude}` : prelude;
      rules.push(...parseCssRules(inner, innerOffset, file, nextAt, lineStarts));
    } else if (/^@keyframes\b/i.test(prelude)) {
      rules.push(...parseCssRules(inner, innerOffset, file, prelude, lineStarts));
    } else {
      rules.push({
        file,
        line: lineNumberAt(lineStarts, preludeOffset),
        selector: prelude,
        atRule,
        declarations: parseDeclarations(
          inner,
          innerOffset,
          file,
          prelude,
          atRule,
          lineStarts,
        ),
      });
    }
    i = j;
  }
  return rules;
}

/** 提取括号匹配的完整函数调用（如 `rgba(255, 255, 255, 0.2)` 或 `rgb(var(--x-rgb))`） */
function extractFunctionCalls(value: string, fnRegex: RegExp): string[] {
  const matches: string[] = [];
  const re = new RegExp(
    fnRegex.source,
    fnRegex.flags.includes("g") ? fnRegex.flags : `${fnRegex.flags}g`,
  );
  let m: RegExpExecArray | null;
  while ((m = re.exec(value)) !== null) {
    const start = m.index;
    const openParen = value.indexOf("(", start);
    if (openParen === -1) continue;
    let depth = 1;
    let k = openParen + 1;
    while (k < value.length && depth > 0) {
      if (value[k] === "(") depth += 1;
      else if (value[k] === ")") depth -= 1;
      k += 1;
    }
    matches.push(value.slice(start, k));
  }
  return matches;
}

/** 剥离字符串字面量（如 font-family: "Segoe UI" 或 url("data:...")），避免干扰颜色字面量扫描 */
function stripQuotedStrings(value: string): string {
  let out = "";
  let i = 0;
  let inQuote: string | null = null;
  while (i < value.length) {
    const ch = value[i];
    if (inQuote) {
      if (ch === "\\" && i + 1 < value.length) {
        i += 2;
        continue;
      }
      if (ch === inQuote) inQuote = null;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inQuote = ch;
      out += '""';
      i += 1;
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

export function findColorLiteralsInValue(rawValue: string): string[] {
  const unquoted = stripQuotedStrings(rawValue);
  const literals: string[] = [];

  for (const m of unquoted.matchAll(/#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])/g)) {
    literals.push(m[0]);
  }

  for (const call of extractFunctionCalls(unquoted, ALL_COLOR_FN_RE)) {
    if (!VALID_TOKEN_RGB_CALL_RE.test(call)) {
      literals.push(call);
    }
  }

  for (const m of unquoted.matchAll(NAMED_COLOR_RE)) {
    literals.push(m[1]);
  }

  return literals;
}

function isNeutralWhiteLiteral(literal: string): boolean {
  const norm = literal.trim().toLowerCase().replace(/\s+/g, "");
  if (norm === "#fff" || norm === "#ffffff" || norm === "white") return true;
  if (norm === "rgb(255,255,255)") return true;
  return /^rgba\(255,255,255,(?:0|1|0?\.\d+|1\.0+)\)$/.test(norm);
}

function isNeutralWhiteOrBlackLiteral(literal: string): boolean {
  if (isNeutralWhiteLiteral(literal)) return true;
  const norm = literal.trim().toLowerCase().replace(/\s+/g, "");
  if (norm === "#000" || norm === "#000000" || norm === "black") return true;
  if (norm === "rgb(0,0,0)") return true;
  return /^rgba\(0,0,0,(?:0|1|0?\.\d+|1\.0+)\)$/.test(norm);
}

function splitSelectorList(selector: string): string[] {
  const parts: string[] = [];
  let start = 0;
  let depth = 0;
  let inQuote: string | null = null;
  for (let i = 0; i < selector.length; i += 1) {
    const ch = selector[i];
    if (inQuote) {
      if (ch === "\\" && i + 1 < selector.length) {
        i += 1;
        continue;
      }
      if (ch === inQuote) inQuote = null;
      continue;
    }
    if (ch === '"' || ch === "'") inQuote = ch;
    else if (ch === "(" || ch === "[") depth += 1;
    else if ((ch === ")" || ch === "]") && depth > 0) depth -= 1;
    else if (ch === "," && depth === 0) {
      parts.push(selector.slice(start, i).trim());
      start = i + 1;
    }
  }
  parts.push(selector.slice(start).trim());
  return parts.filter(Boolean);
}

function hasTopLevelSiblingCombinator(branch: string): boolean {
  let depth = 0;
  let inQuote: string | null = null;
  for (let i = 0; i < branch.length; i += 1) {
    const ch = branch[i];
    if (inQuote) {
      if (ch === "\\" && i + 1 < branch.length) {
        i += 1;
        continue;
      }
      if (ch === inQuote) inQuote = null;
      continue;
    }
    if (ch === '"' || ch === "'") inQuote = ch;
    else if (ch === "(" || ch === "[") depth += 1;
    else if ((ch === ")" || ch === "]") && depth > 0) depth -= 1;
    else if (depth === 0 && (ch === "+" || ch === "~")) return true;
  }
  return false;
}

/**
 * 判断单条选择器分支是否严格命中灯箱子树内部：
 * - 拒绝任何含顶层 `+` / `~` 兄弟组合器的分支（如 `.viewer-screen + .other` 在灯箱外部）；
 * - 允许 `.viewer-screen`、`.note-zoom` 及其后代/伪类/属性组合，以及 Note.css 中挂载在 `.note-zoom` 内的三个扁平子类名。
 */
export function isBranchInLockedScope(branch: string): boolean {
  if (hasTopLevelSiblingCombinator(branch)) return false;
  return LOCKED_CHILD_CLASS_PREFIXES.some((prefix) => {
    if (!branch.startsWith(prefix)) return false;
    const next = branch[prefix.length];
    return next === undefined || /[\s.:[>]/.test(next);
  });
}

/** 测试 1 使用：逗号选择器的全部分支都落在灯箱内时才允许豁免中性白/黑字面量 */
export function allBranchesInLockedScope(selector: string): boolean {
  const branches = splitSelectorList(selector);
  return branches.length > 0 && branches.every(isBranchInLockedScope);
}

/** 测试 6 使用：只要任一分支命中灯箱内部（或为无宿主限定的全局伪元素），引用的 tokens 变量就必须在锁定块重建 */
export function anyBranchAffectsLockedScope(selector: string): boolean {
  const branches = splitSelectorList(selector);
  return (
    branches.length > 0 &&
    branches.some((b) => isBranchInLockedScope(b) || GLOBAL_PSEUDO_ELEMENT_RE.test(b))
  );
}

describe("前端颜色令牌完整性与单点定义守卫（color-tokens）", () => {
  const cssFiles = collectFiles(SRC_DIR, (n) => n.endsWith(".css"));
  const parsedByFile = new Map<
    string,
    { clean: string; lineStarts: number[]; rules: CssRule[] }
  >();

  for (const fullPath of cssFiles) {
    const rel = toPosixRel(fullPath);
    const raw = readFileSync(fullPath, "utf8");
    const clean = stripCssCommentsPreservingLines(raw);
    const lineStarts = buildLineStarts(clean);
    const rules = parseCssRules(clean, 0, rel, null, lineStarts);
    parsedByFile.set(rel, { clean, lineStarts, rules });
  }

  it("1) 除 tokens.css 外无未豁免的颜色字面量（仅放行 D 类自定义头像白字、E 类 mask 遮罩、灯箱锁定作用域内的中性白/黑）", () => {
    expect(parsedByFile.has(TOKENS_REL_PATH)).toBe(true);
    const violations: string[] = [];

    for (const [rel, { rules }] of parsedByFile.entries()) {
      if (rel === TOKENS_REL_PATH) continue;

      for (const rule of rules) {
        const inLockedScope = allBranchesInLockedScope(rule.selector);
        const avatarExemptSelectors = AVATAR_CUSTOM_COLOR_EXEMPTIONS[rel];
        const isAvatarCustomRule =
          avatarExemptSelectors !== undefined &&
          avatarExemptSelectors.has(rule.selector);

        for (const decl of rule.declarations) {
          const literals = findColorLiteralsInValue(decl.value);
          for (const lit of literals) {
            if (isAvatarCustomRule && isNeutralWhiteLiteral(lit)) {
              continue;
            }
            if (
              MASK_PROPERTIES.has(decl.prop.toLowerCase()) &&
              isNeutralWhiteOrBlackLiteral(lit)
            ) {
              continue;
            }
            if (inLockedScope && isNeutralWhiteOrBlackLiteral(lit)) {
              continue;
            }
            violations.push(
              `${decl.file}:${decl.line} (${rule.selector} -> ${decl.prop}) 匹配到未豁免字面量: ${lit}`,
            );
          }
        }
      }
    }

    expect(violations).toEqual([]);
  });

  it("2) 除 tokens.css 外不存在裸 RGB 三元组（--x: R, G, B）声明", () => {
    const violations: string[] = [];
    const bareTripletRe = /^\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}$/;

    for (const [rel, { rules }] of parsedByFile.entries()) {
      if (rel === TOKENS_REL_PATH) continue;
      for (const rule of rules) {
        for (const decl of rule.declarations) {
          if (decl.prop.startsWith("--") && bareTripletRe.test(decl.value)) {
            violations.push(
              `${decl.file}:${decl.line} (${rule.selector}) 存在裸 RGB 三元组: ${decl.prop}: ${decl.value}`,
            );
          }
        }
      }
    }

    expect(violations).toEqual([]);
  });

  it("3) tokens.css 自身零十六进制/非 rgb 颜色函数、rgb/rgba 首参均为 var(--*-rgb)、且 :root 的 --*-rgb 为 >=26 个 0–255 三元组", () => {
    const tokensEntry = parsedByFile.get(TOKENS_REL_PATH)!;
    const violations: string[] = [];
    let rootChannelCount = 0;

    for (const rule of tokensEntry.rules) {
      const isRootRule = rule.selector === ":root" && rule.atRule === null;

      for (const decl of rule.declarations) {
        const unquoted = stripQuotedStrings(decl.value);

        for (const m of unquoted.matchAll(/#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])/g)) {
          violations.push(
            `${decl.file}:${decl.line} (${decl.prop}) 出现十六进制颜色字面量: ${m[0]}`,
          );
        }

        for (const m of unquoted.matchAll(NAMED_COLOR_RE)) {
          violations.push(
            `${decl.file}:${decl.line} (${decl.prop}) 出现关键字颜色字面量: ${m[1]}`,
          );
        }

        for (const call of extractFunctionCalls(unquoted, ALL_COLOR_FN_RE)) {
          if (!VALID_TOKEN_RGB_CALL_RE.test(call)) {
            violations.push(
              `${decl.file}:${decl.line} (${decl.prop}) 出现非法颜色函数调用（仅允许 rgb/rgba(var(--*-rgb), α)）: ${call}`,
            );
          }
        }

        if (decl.prop.endsWith("-rgb")) {
          if (isRootRule) rootChannelCount += 1;
          const tripletMatch = /^(\d{1,3}), (\d{1,3}), (\d{1,3})$/.exec(decl.value);
          if (!tripletMatch) {
            violations.push(
              `${decl.file}:${decl.line} (${decl.prop}) 不符合 "R, G, B" 严格格式: "${decl.value}"`,
            );
          } else {
            const nums = [
              Number(tripletMatch[1]),
              Number(tripletMatch[2]),
              Number(tripletMatch[3]),
            ];
            if (nums.some((n) => n < 0 || n > 255)) {
              violations.push(
                `${decl.file}:${decl.line} (${decl.prop}) 通道数值越出 0–255: "${decl.value}"`,
              );
            }
          }
        }
      }
    }

    const rootRule = tokensEntry.rules.find(
      (r) => r.selector === ":root" && r.atRule === null,
    );
    expect(rootRule).toBeDefined();
    const rootDefinedNames = new Set(rootRule!.declarations.map((d) => d.prop));
    for (const reqName of REQUIRED_ROOT_COMPOSITES) {
      if (!rootDefinedNames.has(reqName)) {
        violations.push(`${TOKENS_REL_PATH} 的 :root 缺少必需的复合变量声明: ${reqName}`);
      }
    }

    expect(rootChannelCount).toBeGreaterThanOrEqual(26);
    expect(violations).toEqual([]);
  });

  it("4) 所有 CSS var(--name) 引用均有全局或同文件定义（或登记于 RUNTIME_WRITTEN），且反向校验白名单真实写入", () => {
    const globalVars = new Set<string>();
    const fileScopedVars = new Map<string, Set<string>>();
    const varReferences: Array<{ file: string; line: number; name: string }> = [];

    for (const [rel, { rules }] of parsedByFile.entries()) {
      const localSet = new Set<string>();
      fileScopedVars.set(rel, localSet);
      for (const rule of rules) {
        const isRootScope =
          rel === TOKENS_REL_PATH ||
          rule.selector === ":root" ||
          rule.selector === "html";
        for (const decl of rule.declarations) {
          if (decl.prop.startsWith("--")) {
            if (isRootScope) {
              globalVars.add(decl.prop);
            } else {
              localSet.add(decl.prop);
            }
          }
          for (const m of stripQuotedStrings(decl.value).matchAll(
            /var\(\s*(--[a-zA-Z0-9-]+)/g,
          )) {
            varReferences.push({
              file: decl.file,
              line: decl.line,
              name: m[1],
            });
          }
        }
      }
    }

    const missingRefs = varReferences
      .filter(({ file, name }) => {
        if (globalVars.has(name)) return false;
        if (fileScopedVars.get(file)?.has(name)) return false;
        return !(name in RUNTIME_WRITTEN);
      })
      .map(({ file, line, name }) => `${file}:${line} 引用了未定义的变量 ${name}`);
    expect(missingRefs).toEqual([]);

    // 扫描三处非测试源码写入源反向校验 RUNTIME_WRITTEN 白名单，防止死项残留
    const discoveredRuntimeWrites = new Map<string, Set<string>>();
    const recordWrite = (varName: string, relFile: string) => {
      if (!discoveredRuntimeWrites.has(varName)) {
        discoveredRuntimeWrites.set(varName, new Set());
      }
      discoveredRuntimeWrites.get(varName)!.add(relFile);
    };

    // (a) src/**/*.tsx（排除测试文件）行内样式键 "--x": 或 style.setProperty("--x", ...)
    for (const fullPath of collectFiles(
      SRC_DIR,
      (n) => n.endsWith(".tsx") && !n.endsWith(".test.tsx") && !n.endsWith(".spec.tsx"),
    )) {
      const rel = toPosixRel(fullPath);
      const content = readFileSync(fullPath, "utf8");
      for (const m of content.matchAll(/["'](--[a-zA-Z0-9-]+)["']\s*:/g)) {
        recordWrite(m[1], rel);
      }
      for (const m of content.matchAll(/\.setProperty\(\s*["'](--[a-zA-Z0-9-]+)["']/g)) {
        recordWrite(m[1], rel);
      }
    }

    // (b) src/**/*.ts（排除测试文件）style.setProperty("--x", ...)
    for (const fullPath of collectFiles(
      SRC_DIR,
      (n) => n.endsWith(".ts") && !n.endsWith(".test.ts") && !n.endsWith(".spec.ts"),
    )) {
      const rel = toPosixRel(fullPath);
      const content = readFileSync(fullPath, "utf8");
      for (const m of content.matchAll(/\.setProperty\(\s*["'](--[a-zA-Z0-9-]+)["']/g)) {
        recordWrite(m[1], rel);
      }
    }

    // (c) scripts/*.mjs（排除测试文件）构建期拼入 style="--x:..."
    for (const fullPath of collectFiles(
      SCRIPTS_DIR,
      (n) => n.endsWith(".mjs") && !n.endsWith(".test.mjs"),
    )) {
      const rel = toPosixRel(fullPath);
      const content = readFileSync(fullPath, "utf8");
      for (const m of content.matchAll(/style="[^"]*?(--[a-zA-Z0-9-]+)\s*:/g)) {
        recordWrite(m[1], rel);
      }
    }

    const staleWhitelist: string[] = [];
    for (const [varName, expectedFile] of Object.entries(RUNTIME_WRITTEN)) {
      const actualFiles = discoveredRuntimeWrites.get(varName);
      if (!actualFiles || !actualFiles.has(expectedFile)) {
        staleWhitelist.push(
          `${varName} 声明写入处为 ${expectedFile}，但实际扫描结果: ${
            actualFiles ? [...actualFiles].join(", ") : "未找到任何写入处"
          }`,
        );
      }
    }
    expect(staleWhitelist).toEqual([]);
  });

  it("5) PlatformStage.css 不再在组件内私自定义 --accent-cyan 或 --accent-amber", () => {
    const platformCss = parsedByFile.get("src/components/PlatformStage.css");
    expect(platformCss).toBeDefined();
    expect(platformCss!.clean).not.toMatch(/--accent-cyan\s*:/);
    expect(platformCss!.clean).not.toMatch(/--accent-amber\s*:/);
  });

  it("6) 灯箱锁定块（.viewer-screen, .note-zoom）完整覆盖作用域及全局伪元素引用的通道/派生变量并阻断 body 文字色继承", () => {
    const tokensEntry = parsedByFile.get(TOKENS_REL_PATH)!;
    const rootRule = tokensEntry.rules.find(
      (r) => r.selector === ":root" && r.atRule === null,
    );
    expect(rootRule).toBeDefined();

    const rootMap = new Map<string, string>();
    for (const d of rootRule!.declarations) {
      if (d.prop.startsWith("--")) rootMap.set(d.prop, d.value);
    }

    const lockRule = tokensEntry.rules.find((r) => {
      if (r.atRule !== null) return false;
      const branches = splitSelectorList(r.selector);
      return (
        branches.length === LOCKED_ROOT_SELECTORS.length &&
        LOCKED_ROOT_SELECTORS.every((p) => branches.includes(p))
      );
    });
    expect(lockRule).toBeDefined();

    const lockMap = new Map<string, string>();
    let hasExplicitTextMainColor = false;
    for (const d of lockRule!.declarations) {
      if (d.prop.startsWith("--")) lockMap.set(d.prop, d.value);
      if (d.prop === "color" && d.value === "var(--text-main)") {
        hasExplicitTextMainColor = true;
      }
    }
    expect(hasExplicitTextMainColor).toBe(true);

    const lockErrors: string[] = [];

    // 锁定块内声明的每个变量都必须与 :root 午夜蓝定义一致，且派生变量依赖的 --*-rgb 也必须在同块锁定
    for (const [prop, val] of lockMap.entries()) {
      if (!rootMap.has(prop)) {
        lockErrors.push(`锁定块声明了 :root 中不存在的变量 ${prop}`);
        continue;
      }
      if (rootMap.get(prop) !== val) {
        lockErrors.push(
          `锁定块 ${prop} 的值 (${val}) 与 :root 默认午夜蓝值 (${rootMap.get(prop)}) 不一致`,
        );
      }
      if (!prop.endsWith("-rgb")) {
        for (const m of val.matchAll(/var\(\s*(--[a-zA-Z0-9-]+)/g)) {
          if (!lockMap.has(m[1])) {
            lockErrors.push(
              `锁定块派生变量 ${prop} 依赖 ${m[1]}，但 ${m[1]} 未在同一个锁定块内重新声明`,
            );
          }
        }
      }
    }

    // 锁定作用域（含 .note-zoom-* 扁平子类名）及全局伪元素（::selection / ::-webkit-scrollbar*）使用的每个 tokens 变量都必须在锁定块重建
    let matchedNoteZoomClose = false;
    for (const [, { rules }] of parsedByFile.entries()) {
      for (const rule of rules) {
        if (!anyBranchAffectsLockedScope(rule.selector)) continue;
        if (rule.selector === ".note-zoom-close") matchedNoteZoomClose = true;

        for (const decl of rule.declarations) {
          for (const m of stripQuotedStrings(decl.value).matchAll(
            /var\(\s*(--[a-zA-Z0-9-]+)/g,
          )) {
            const varName = m[1];
            if (rootMap.has(varName) && !lockMap.has(varName)) {
              lockErrors.push(
                `${decl.file}:${decl.line} (${rule.selector}) 使用了 ${varName}，但 tokens.css 灯箱锁定块未重新声明它`,
              );
            }
          }
        }
      }
    }

    expect(matchedNoteZoomClose).toBe(true);
    expect(lockErrors).toEqual([]);
  });

  it("7) 守卫自检：防止 var() 字面量回退、非 rgb 颜色函数、兄弟组合器与多分支选择器绕过", () => {
    expect(findColorLiteralsInValue("rgba(var(--accent-gold-rgb, 255, 192, 105), 0.5)")).toHaveLength(1);
    expect(findColorLiteralsInValue("hsl(var(--h), 100%, 50%)")).toHaveLength(1);
    expect(findColorLiteralsInValue("color-mix(in srgb, var(--accent-gold) 50%, transparent)")).toHaveLength(1);
    expect(findColorLiteralsInValue("1px solid crimson")).toEqual(["crimson"]);
    expect(findColorLiteralsInValue("rgba(var(--accent-gold-rgb), 0.5)")).toEqual([]);
    expect(findColorLiteralsInValue("rgb(var(--accent-gold-rgb))")).toEqual([]);

    expect(isBranchInLockedScope(".note-zoom-close")).toBe(true);
    expect(isBranchInLockedScope(".note-zoom-toggle:focus-visible")).toBe(true);
    expect(isBranchInLockedScope(".viewer-screen + .outside")).toBe(false);
    expect(isBranchInLockedScope(".note-zoom ~ footer")).toBe(false);
    expect(allBranchesInLockedScope(".outside, .viewer-screen .nav-btn")).toBe(false);
    expect(anyBranchAffectsLockedScope(".outside, .viewer-screen .nav-btn")).toBe(true);
    expect(anyBranchAffectsLockedScope("::-webkit-scrollbar-thumb")).toBe(true);
    expect(anyBranchAffectsLockedScope("::-webkit-scrollbar-thumb:hover")).toBe(true);
  });
});
