import { describe, expect, it } from "vitest";
import { buildNotes, slugFromPath } from "./notes";

describe("notes 数据层", () => {
  it("slugFromPath 取文件名去扩展", () => {
    expect(slugFromPath("/content/notes/harness-cold-start.md")).toBe("harness-cold-start");
  });
  it("buildNotes 映射字段并按日期倒序", () => {
    const notes = buildNotes({
      "/content/notes/a.md": { title: "旧", date: "2026-07-01", summary: "s1", source: "LinuxDo", sourceUrl: "https://l.d/1" },
      "/content/notes/b.md": { title: "新", date: "2026-07-27", summary: "s2", source: "CSDN", sourceUrl: "https://c.n/2" },
    });
    expect(notes.map((n) => n.title)).toEqual(["新", "旧"]);
    expect(notes[0]).toEqual({ slug: "b", title: "新", date: "2026-07-27", summary: "s2", source: "CSDN", sourceUrl: "https://c.n/2" });
  });
  it("source/sourceUrl 缺省兜底为 站内/空串", () => {
    const [n] = buildNotes({ "/content/notes/x.md": { title: "t", date: "2026-01-01", summary: "s" } });
    expect(n).toEqual({ slug: "x", title: "t", date: "2026-01-01", summary: "s", source: "站内", sourceUrl: "" });
  });
});
