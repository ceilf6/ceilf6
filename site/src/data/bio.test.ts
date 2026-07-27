import { describe, expect, it } from "vitest";
import { BIO, bioSegments } from "./bio";

describe("bioSegments", () => {
  it("@提及切分为 mention 段并携带 GitHub 链接", () => {
    const segs = bioSegments();
    const mentions = segs.filter((s) => s.type === "mention");
    expect(mentions.map((m) => m.value)).toEqual(["FrontAgent", "bytedance", "meituan", "qiniu"]);
    expect(mentions[0].href).toBe("https://github.com/ceilf6/FrontAgent");
    expect(mentions[1].href).toBe("https://github.com/bytedance");
  });
  it("拼回原文一字不差(GitHub bio 原文承诺)", () => {
    const joined = bioSegments()
      .map((s) => (s.type === "mention" ? `@${s.value}` : s.value))
      .join("");
    expect(joined).toBe(BIO);
  });
  it("词表外的 @xxx 保持纯文本", () => {
    const segs = bioSegments("hi @nobody!");
    expect(segs.every((s) => s.type === "text")).toBe(true);
  });
});
