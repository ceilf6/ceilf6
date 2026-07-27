import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import Note from "./Note";

// 模拟「原子部署后旧 index.html 拉新 hash chunk 404」:正文加载必然失败
vi.mock("../data/notes", () => ({
  notes: [
    {
      slug: "demo",
      title: "示例文章",
      date: "2026-07-01",
      summary: "摘要",
      source: "站内",
      sourceUrl: "",
    },
  ],
  loadNoteHtml: () => Promise.reject(new Error("x")),
}));

const at = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/notes/:slug" element={<Note />} />
      </Routes>
    </MemoryRouter>,
  );

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Note 正文加载", () => {
  it("chunk 加载失败渲染错误态,不永久停留「加载中」", async () => {
    at("/notes/demo");
    expect(await screen.findByText(/加载失败/)).toBeInTheDocument();
  });

  it("卸载时 in-flight load 不产生 console.error 告警", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = at("/notes/demo");
    unmount();
    // 让 in-flight promise 的回调排空微任务队列后再断言
    await Promise.resolve();
    await Promise.resolve();
    expect(errSpy).not.toHaveBeenCalled();
  });
});
