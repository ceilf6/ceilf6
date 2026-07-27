import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import Note from "./Note";

/** 每次 loadNoteHtml 调用都暴露 resolve/reject 句柄,由测试手控返回时序
    (模拟原子部署后 chunk 404、慢网下新旧请求乱序返回)。 */
const { inflight } = vi.hoisted(() => ({
  inflight: new Map<string, { resolve: (html: string) => void; reject: (e: unknown) => void }>(),
}));

vi.mock("../data/notes", () => {
  const meta = (slug: string) => ({
    slug,
    title: `标题${slug}`,
    date: "2026-07-01",
    summary: "摘要",
    source: "站内",
    sourceUrl: "",
  });
  return {
    notes: [meta("a"), meta("b")],
    loadNoteHtml: (slug: string) =>
      new Promise<string>((resolve, reject) => {
        inflight.set(slug, { resolve, reject });
      }),
  };
});

function Nav({ to }: { to: string }) {
  const navigate = useNavigate();
  return <button onClick={() => navigate(to)}>nav:{to}</button>;
}

const at = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Nav to="/notes/a" />
      <Nav to="/notes/b" />
      <Routes>
        <Route path="/notes/:slug" element={<Note />} />
      </Routes>
    </MemoryRouter>,
  );

/** 手控句柄触发 → 微任务排空 → React 提交,全程包在 act 内 */
const settle = (fn: () => void) =>
  act(async () => {
    fn();
    await Promise.resolve();
  });

afterEach(() => {
  inflight.clear();
});

describe("Note 正文加载", () => {
  it("chunk 加载失败渲染错误态,不永久停留「加载中」", async () => {
    at("/notes/a");
    await settle(() => inflight.get("a")!.reject(new Error("x")));
    expect(screen.getByText(/加载失败/)).toBeInTheDocument();
  });

  it("slug 切换后乱序返回:旧文迟到的正文不得覆盖新文,切换即回加载态", async () => {
    at("/notes/a");
    expect(screen.getByText(/加载中/)).toBeInTheDocument();
    const lateA = inflight.get("a")!;

    fireEvent.click(screen.getByText("nav:/notes/b"));
    expect(screen.getByText(/加载中/)).toBeInTheDocument();

    await settle(() => inflight.get("b")!.resolve("<p>正文B</p>"));
    expect(screen.getByText("正文B")).toBeInTheDocument();

    // a 的旧请求此刻才回来:alive 守卫必须吞掉它(React 19 已无 unmounted 告警,守卫真正防的是这个)
    await settle(() => lateA.resolve("<p>正文A</p>"));
    expect(screen.getByText("正文B")).toBeInTheDocument();
    expect(screen.queryByText("正文A")).toBeNull();

    // 切回 a 开新一轮加载:effect 顶部的 setBody("loading") 必须清掉 B 的正文
    fireEvent.click(screen.getByText("nav:/notes/a"));
    expect(screen.getByText(/加载中/)).toBeInTheDocument();
    expect(screen.queryByText("正文B")).toBeNull();
  });
});
