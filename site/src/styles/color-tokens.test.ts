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

/** 局部锁定为午夜蓝的灯箱作用域前缀（只允许其中的中性白/黑字面量豁免） */
const LOCKED_SCOPE_PREFIXES = [".viewer-screen", ".note-zoom"] as const;

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
    const openIdx = css.indexOf("{", i);
    if (openIdx === -1) break;
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

    if (/^@(?:media|supports|layer|container)\b/i.test(prelude)) {
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
  const re = new RegExp(fnRegex.source, fnRegex.flags.includes("g") ? fnRegex.flags : `${fnRegex.flags}g`);
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

function findColorLiteralsInValue(rawValue: string): string[] {
  const unquoted = stripQuotedStrings(rawValue);
  const literals: string[] = [];

  for (const m of unquoted.matchAll(/#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])/g)) {
    literals.push(m[0]);
  }

  for (const call of extractFunctionCalls(unquoted, /\b(?:rgba?|hsla?|oklch|oklab|color)\s*\(/gi)) {
    const inner = call.slice(call.indexOf("(") + 1, -1).trimStart();
    if (!inner.startsWith("var(")) {
      literals.push(call);
    }
  }

  for (const m of unquoted.matchAll(/(?:^|[\s,(/:])(white|black)(?=$|[\s,!);\n])/gi)) {
    literals.push(m[1]);
  }

  return literals;
}

function isNeutralWhiteLiteral(literal: string): boolean {
  const norm = literal.trim().toLowerCase().replace(/\s+/g, "");
  if (norm === "#fff" || norm === "#ffffff" || norm === "white") return true;
  if (norm === "rgb(255,255,255)") return true;
  return /^rgba\(255,255,255,(?:0|1|0?\.\d+)\)$/.test(norm);
}

function isNeutralWhiteOrBlackLiteral(literal: string): boolean {
  if (isNeutralWhiteLiteral(literal)) return true;
  const norm = literal.trim().toLowerCase().replace(/\s+/g, "");
  if (norm === "#000" || norm === "#000000" || norm === "black") return true;
  if (norm === "rgb(0,0,0)") return true;
  return /^rgba\(0,0,0,(?:0|1|0?\.\d+)\)$/.test(norm);
}

function splitSelectorList(selector: string): string[] {
  const parts: string[] = [];
  let start = 0;
  let depth = 0;
  for (let i = 0; i < selector.length; i += 1) {
    const ch = selector[i];
    if (ch === "(" || ch === "[") depth += 1;
    else if ((ch === ")" || ch === "]") && depth > 0) depth -= 1;
    else if (ch === "," && depth === 0) {
      parts.push(selector.slice(start, i).trim());
      start = i + 1;
    }
  }
  parts.push(selector.slice(start).trim());
  return parts.filter(Boolean);
}

function isSelectorInLockedScope(selector: string): boolean {
  const branches = splitSelectorList(selector);
  if (branches.length === 0) return false;
  return branches.every((branch) =>
    LOCKED_SCOPE_PREFIXES.some((prefix) => {
      if (!branch.startsWith(prefix)) return false;
      const next = branch[prefix.length];
      return (
        next === undefined ||
        /[\s.:[>+~]/.test(next)
      );
    }),
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
        const inLockedScope = isSelectorInLockedScope(rule.selector);
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

  it("3) tokens.css 自身零十六进制、rgb/rgba 首参均为 var(--*-rgb)、且每个 --*-rgb 为 0–255 合法三元组", () => {
    const tokensEntry = parsedByFile.get(TOKENS_REL_PATH)!;
    const violations: string[] = [];

    for (const m of tokensEntry.clean.matchAll(/#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])/g)) {
      const line = lineNumberAt(tokensEntry.lineStarts, m.index ?? 0);
      violations.push(`${TOKENS_REL_PATH}:${line} 出现十六进制颜色字面量: ${m[0]}`);
    }

    let channelCount = 0;
    for (const rule of tokensEntry.rules) {
      for (const decl of rule.declarations) {
        for (const m of stripQuotedStrings(decl.value).matchAll(
          /(?:^|[\s,(/:])(white|black)(?=$|[\s,!);\n])/gi,
        )) {
          violations.push(
            `${decl.file}:${decl.line} (${decl.prop}) 出现关键字颜色字面量: ${m[1]}`,
          );
        }

        for (const call of extractFunctionCalls(decl.value, /\brgba?\s*\(/gi)) {
          if (!/^rgba?\(\s*var\(--[a-z0-9-]+-rgb\)\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/i.test(call)) {
            violations.push(
              `${decl.file}:${decl.line} (${decl.prop}) 的 rgb/rgba 调用首参不是 var(--*-rgb): ${call}`,
            );
          }
        }

        if (decl.prop.endsWith("-rgb")) {
          channelCount += 1;
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

    expect(channelCount).toBeGreaterThanOrEqual(26);
    expect(violations).toEqual([]);
  });

  it("4) 所有 CSS var(--name) 引用均有定义或登记于 RUNTIME_WRITTEN，且反向校验白名单在源码中真实写入", () => {
    const definedVars = new Set<string>();
    const varReferences: Array<{ file: string; line: number; name: string }> = [];

    for (const [, { rules }] of parsedByFile.entries()) {
      for (const rule of rules) {
        for (const decl of rule.declarations) {
          if (decl.prop.startsWith("--")) {
            definedVars.add(decl.prop);
          }
          for (const m of decl.value.matchAll(/var\(\s*(--[a-zA-Z0-9-]+)/g)) {
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
      .filter(({ name }) => !definedVars.has(name) && !(name in RUNTIME_WRITTEN))
      .map(({ file, line, name }) => `${file}:${line} 引用了未定义的变量 ${name}`);
    expect(missingRefs).toEqual([]);

    // 扫描三处写入源反向校验 RUNTIME_WRITTEN 白名单，防止死项残留
    const discoveredRuntimeWrites = new Map<string, Set<string>>();
    const recordWrite = (varName: string, relFile: string) => {
      if (!discoveredRuntimeWrites.has(varName)) {
        discoveredRuntimeWrites.set(varName, new Set());
      }
      discoveredRuntimeWrites.get(varName)!.add(relFile);
    };

    // (a) src/**/*.tsx 行内样式键 "--x":
    for (const fullPath of collectFiles(SRC_DIR, (n) => n.endsWith(".tsx"))) {
      const rel = toPosixRel(fullPath);
      const content = readFileSync(fullPath, "utf8");
      for (const m of content.matchAll(/["'](--[a-zA-Z0-9-]+)["']\s*:/g)) {
        recordWrite(m[1], rel);
      }
    }

    // (b) src/**/*.ts style.setProperty("--x", ...)
    for (const fullPath of collectFiles(SRC_DIR, (n) => n.endsWith(".ts") && !n.endsWith(".test.ts"))) {
      const rel = toPosixRel(fullPath);
      const content = readFileSync(fullPath, "utf8");
      for (const m of content.matchAll(/\.setProperty\(\s*["'](--[a-zA-Z0-9-]+)["']/g)) {
        recordWrite(m[1], rel);
      }
    }

    // (c) scripts/*.mjs 构建期拼入 style="--x:..."
    for (const fullPath of collectFiles(SCRIPTS_DIR, (n) => n.endsWith(".mjs") && !n.endsWith(".test.mjs"))) {
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

  it("6) 灯箱锁定块（.viewer-screen, .note-zoom）完整覆盖作用域内引用的通道变量与派生变量，且与 :root 午夜蓝基准一致", () => {
    const tokensEntry = parsedByFile.get(TOKENS_REL_PATH)!;
    const rootRule = tokensEntry.rules.find((r) => r.selector === ":root");
    expect(rootRule).toBeDefined();

    const rootMap = new Map<string, string>();
    for (const d of rootRule!.declarations) {
      if (d.prop.startsWith("--")) rootMap.set(d.prop, d.value);
    }

    const lockRule = tokensEntry.rules.find((r) => {
      const branches = splitSelectorList(r.selector);
      return (
        branches.length === LOCKED_SCOPE_PREFIXES.length &&
        LOCKED_SCOPE_PREFIXES.every((p) => branches.includes(p))
      );
    });
    expect(lockRule).toBeDefined();

    const lockMap = new Map<string, string>();
    for (const d of lockRule!.declarations) {
      if (d.prop.startsWith("--")) lockMap.set(d.prop, d.value);
    }

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

    // 锁定作用域（.viewer-screen* / .note-zoom*）及全局 ::selection 内出现的每个 tokens.css 变量（含派生变量）都必须在锁定块内重新声明
    for (const [, { rules }] of parsedByFile.entries()) {
      for (const rule of rules) {
        const affectsLockedScope =
          isSelectorInLockedScope(rule.selector) || rule.selector === "::selection";
        if (!affectsLockedScope) continue;

        for (const decl of rule.declarations) {
          for (const m of decl.value.matchAll(/var\(\s*(--[a-zA-Z0-9-]+)/g)) {
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

    expect(lockErrors).toEqual([]);
  });
});
