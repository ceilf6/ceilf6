import { afterEach, describe, expect, it, vi } from "vitest";
import { extractAvatarInitial, isValidAvatarColor } from "./avatar";

describe("extractAvatarInitial 首字母取字（顶栏与评论区共用）", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const standardCases: Array<[string, string]> = [
    ["王景宏", "王"],
    ["王", "王"],
    ["abc", "A"],
    ["🇨🇳", "🇨🇳"],
    ["🇨🇳旅行者", "🇨🇳"],
    ["👋🏽", "👋🏽"],
    ["👋🏽你好", "👋🏽"],
    ["👨‍👩‍👧", "👨‍👩‍👧"],
    ["e\u0301", "E\u0301"],
    ["किरण", "कि"],
    ["ß", "SS"],
    ["用户 #12", "用"],
  ];

  it.each(standardCases)("Intl.Segmenter 路径：%j -> %j", (input, expected) => {
    expect(extractAvatarInitial(input)).toBe(expected);
  });

  it("空串或纯空白防御返回 ?", () => {
    expect(extractAvatarInitial("")).toBe("?");
    expect(extractAvatarInitial("   ")).toBe("?");
  });

  it.each(standardCases)(
    "无 Intl.Segmenter 回退路径：%j -> %j",
    (input, expected) => {
      const originalSegmenter = Intl.Segmenter;
      Object.defineProperty(Intl, "Segmenter", {
        configurable: true,
        value: undefined,
      });
      try {
        expect(extractAvatarInitial(input)).toBe(expected);
      } finally {
        Object.defineProperty(Intl, "Segmenter", {
          configurable: true,
          value: originalSegmenter,
        });
      }
    },
  );
});

describe("isValidAvatarColor 共享十六进制色值校验", () => {
  it.each(["#4F46E5", "#0f766e", "#BE123C", "#a1B2c3"])(
    "接受合法 6 位十六进制颜色 %s",
    (hex) => {
      expect(isValidAvatarColor(hex)).toBe(true);
    },
  );

  it.each<unknown[]>([
    [undefined],
    [null],
    [""],
    ["#fff"],
    ["red"],
    ["#fff; background:url(x)"],
    ["url(javascript:alert(1))"],
    [42],
  ])("拒绝非法或样式注入值 %j", (bad) => {
    expect(isValidAvatarColor(bad)).toBe(false);
  });
});
