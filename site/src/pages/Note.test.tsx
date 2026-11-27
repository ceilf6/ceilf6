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
      <Nav to="/blog/a" />
      <Nav to="/blog/b" />
      <Routes>
        <Route path="/blog/:slug" element={<Note />} />
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
    at("/blog/a");
    expect(screen.getByRole("link", { name: "← 博客论坛" })).toHaveAttribute("href", "/blog");
    expect(document.title).toBe("王景宏 · 博客论坛 · 标题a");
    expect(screen.queryByRole("heading", { name: "评论" })).toBeNull();

    await settle(() => inflight.get("a")!.reject(new Error("x")));
    expect(screen.getByText(/加载失败/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "评论" })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("slug 切换后乱序返回:旧文迟到的正文不得覆盖新文,切换首帧不提前拉取新文评论", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    at("/blog/a");
    expect(screen.getByText(/加载中/)).toBeInTheDocument();
    const lateA = inflight.get("a")!;

    fireEvent.click(screen.getByText("nav:/blog/b"));
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
    fireEvent.click(screen.getByText("nav:/blog/a"));
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
    at("/blog/a");

    await settle(() => inflight.get("a")!.resolve("<p>独立可读的正文A</p>"));
    expect(screen.getByText("独立可读的正文A")).toBeInTheDocument();
    expect(
      await screen.findByText("评论暂时无法读取，请稍后重试。"),
    ).toBeInTheDocument();
    expect(screen.getByText("独立可读的正文A")).toBeInTheDocument();
  });
});

describe("Note 配图点击放大", () => {
  const ready = async () => {
    at("/blog/a");
    await settle(() =>
      inflight.get("a")!.resolve(
        '<figure class="note-gallery"><img alt="甲" src="/a.webp"><img alt="乙" src="/b.webp"></figure>'
          + '<p>正文 <a href="https://x.y"><img alt="链图" src="/l.webp"></a></p>',
      ),
    );
  };

  it("点击正文配图打开全屏查看,Esc 关闭", async () => {
    await ready();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByAltText("乙"));
    const dialog = screen.getByRole("dialog", { name: "乙" });
    expect(dialog.querySelector("img")).toHaveAttribute("src", "/b.webp");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("点击遮罩任意处关闭;点击正文文字或链接内的图片不打开", async () => {
    await ready();
    fireEvent.click(screen.getByText(/正文/));
    fireEvent.click(screen.getByAltText("链图"));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByAltText("甲"));
    fireEvent.click(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("键盘可达:配图可聚焦,Enter 打开后焦点进关闭按钮、背景 inert,关闭后焦点回到原图", async () => {
    await ready();
    const img = screen.getByAltText("甲");
    expect(img).toHaveAttribute("tabindex", "0");
    expect(screen.getByAltText("链图")).not.toHaveAttribute("tabindex");
    img.focus();
    fireEvent.keyDown(img, { key: "Enter" });
    const close = screen.getByRole("button", { name: "关闭" });
    expect(close).toHaveFocus();
    // 背景整体 inert:焦点无论如何(含点击图片后落到 body)都无法 Tab 回遮罩后方
    const dialog = screen.getByRole("dialog");
    const background = [...document.body.children].filter((el) => !el.contains(dialog));
    expect(background.length).toBeGreaterThan(0);
    background.forEach((el) => expect(el).toHaveAttribute("inert"));
    fireEvent.click(close);
    expect(screen.queryByRole("dialog")).toBeNull();
    background.forEach((el) => expect(el).not.toHaveAttribute("inert"));
    expect(img).toHaveFocus();
  });

  it("原尺寸切换是可聚焦按钮(鼠标点击与键盘均可),不关闭弹层", async () => {
    await ready();
    fireEvent.click(screen.getByAltText("甲"));
    const dialog = screen.getByRole("dialog", { name: "甲" });
    const toggle = screen.getByRole("button", { name: "原尺寸" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle.querySelector("img")).toHaveAttribute("src", "/a.webp");
    fireEvent.click(toggle);
    expect(dialog).toHaveClass("is-full");
    expect(screen.getByRole("button", { name: "原尺寸" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(toggle);
    expect(screen.getByRole("dialog")).not.toHaveClass("is-full");
  });
});
