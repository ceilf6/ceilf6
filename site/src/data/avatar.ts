const AVATAR_COLOR_HEX_RE = /^#[0-9a-f]{6}$/i;
const COMBINING_MARK_RE = /^[\p{Mn}\p{Me}\p{Mc}]$/u;

export function isValidAvatarColor(value: unknown): value is string {
  return typeof value === "string" && AVATAR_COLOR_HEX_RE.test(value);
}

function isRegionalIndicator(char: string): boolean {
  const cp = char.codePointAt(0);
  return cp !== undefined && cp >= 0x1f1e6 && cp <= 0x1f1ff;
}

function isGraphemeExtender(char: string): boolean {
  const cp = char.codePointAt(0);
  if (cp === undefined) return false;
  if (cp === 0xfe0e || cp === 0xfe0f) return true;
  if (cp >= 0x1f3fb && cp <= 0x1f3ff) return true;
  return COMBINING_MARK_RE.test(char);
}

/**
 * 提取用户昵称的首个字素簇并转为大写，支持中文、组合音标、肤色修饰、国旗及 ZWJ 家庭 Emoji。
 */
export function extractAvatarInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";

  if (typeof Intl !== "undefined" && typeof Intl.Segmenter === "function") {
    const segmenter = new Intl.Segmenter("zh", { granularity: "grapheme" });
    const first = segmenter.segment(trimmed)[Symbol.iterator]().next();
    if (first.done || !first.value.segment) return "?";
    return first.value.segment.toUpperCase();
  }

  const chars = Array.from(trimmed);
  if (chars.length === 0) return "?";

  let cluster = chars[0];
  let i = 1;

  if (
    isRegionalIndicator(chars[0]) &&
    i < chars.length &&
    isRegionalIndicator(chars[i])
  ) {
    cluster += chars[i];
    i += 1;
  }

  while (i < chars.length) {
    const ch = chars[i];
    if (ch === "\u200D") {
      cluster += ch;
      i += 1;
      if (i < chars.length) {
        cluster += chars[i];
        i += 1;
      }
      continue;
    }
    if (isGraphemeExtender(ch)) {
      cluster += ch;
      i += 1;
      continue;
    }
    break;
  }

  return cluster.toUpperCase();
}
