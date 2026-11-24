import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

function defaultApiResponse(url: string): Response {
  if (url === "/api/me/") {
    return new Response(
      JSON.stringify({
        user: null,
        csrfToken: "test-csrf",
        guestCommentsAllowed: true,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }
  return new Response(JSON.stringify({ items: [], nextBefore: null }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

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

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
    Promise.resolve(defaultApiResponse(String(input))),
  );
});

afterEach(() => {
  inflight.clear();
  vi.restoreAllMocks();
});

describe("Note 正文加载与评论区挂载边界", () => {
  it("chunk 加载失败渲染错误态,不永久停留「加载中」,且不挂载评论区", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    at("/notes/a");
    expect(screen.queryByRole("heading", { name: "评论" })).toBeNull();

    await settle(() => inflight.get("a")!.reject(new Error("x")));
    expect(screen.getByText(/加载失败/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "评论" })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("slug 切换后乱序返回:旧文迟到的正文不得覆盖新文,切换首帧不提前拉取新文评论", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    at("/notes/a");
    expect(screen.getByText(/加载中/)).toBeInTheDocument();
    const lateA = inflight.get("a")!;

    fireEvent.click(screen.getByText("nav:/notes/b"));
    expect(screen.getByText(/加载中/)).toBeInTheDocument();

    await settle(() => inflight.get("b")!.resolve("<p>正文B</p>"));
    expect(screen.getByText("正文B")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "评论" })).toBeInTheDocument();
    expect(
      await screen.findByText("还没有评论，欢迎留下第一条讨论。"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/notes/b/comments/",
      expect.objectContaining({ method: "GET" }),
    );

    // a 的旧请求此刻才回来:alive 守卫必须吞掉它
    await settle(() => lateA.resolve("<p>正文A</p>"));
    expect(screen.getByText("正文B")).toBeInTheDocument();
    expect(screen.queryByText("正文A")).toBeNull();

    // 切回 a 开新一轮加载:首帧同步回到 loading,正文 a 尚未完成前不拉取 /api/notes/a/comments/
    fireEvent.click(screen.getByText("nav:/notes/a"));
    expect(screen.getByText(/加载中/)).toBeInTheDocument();
    expect(screen.queryByText("正文B")).toBeNull();
    expect(screen.queryByRole("heading", { name: "评论" })).toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("评论接口失败时仅评论区降级提示,札记正文仍正常阅读", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(defaultApiResponse(url));
      }
      return Promise.reject(new Error("api 502"));
    });
    at("/notes/a");

    await settle(() => inflight.get("a")!.resolve("<p>独立可读的正文A</p>"));
    expect(screen.getByText("独立可读的正文A")).toBeInTheDocument();
    expect(
      await screen.findByText("评论暂时无法读取，请稍后重试。"),
    ).toBeInTheDocument();
    expect(screen.getByText("独立可读的正文A")).toBeInTheDocument();
  });
});
