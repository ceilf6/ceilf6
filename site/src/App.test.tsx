import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router";
import { SPLASH_KEY } from "./components/SplashScreen";
import { awards } from "./data/awards";
import App, { AppRoutes } from "./App";

const at = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url === "/api/me/") {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            user: null,
            csrfToken: "test-csrf",
            guestCommentsAllowed: true,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    if (url.startsWith("/api/notes/")) {
      return Promise.resolve(
        new Response(JSON.stringify({ items: [], nextBefore: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url === "/harness/data.json") {
      return Promise.resolve(
        new Response(JSON.stringify({ threads: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.reject(new Error(`Unexpected test fetch: ${url}`));
  });
});

afterEach(async () => {
  await vi.dynamicImportSettled();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("routes", () => {
  it("/ 渲染主页", () => {
    at("/");
    expect(screen.getByTestId("page-home")).toBeInTheDocument();
  });
  it.each(["/blog", "/vlog", "/awards"])("%s 渲染对应页面", (p) => {
    at(p);
    expect(screen.getByTestId(`page-${p.slice(1)}`)).toBeInTheDocument();
  });
  it("/viewer 渲染查看器", () => {
    at("/viewer?img=1");
    expect(screen.getByTestId("page-viewer")).toBeInTheDocument();
  });
  it.each([
    ["/blog.html", "page-blog"],
    ["/vlog.html", "page-vlog"],
  ])("legacy %s 站内重定向", (p, tid) => {
    at(p);
    expect(screen.getByTestId(tid)).toBeInTheDocument();
  });
  it("legacy /viewer.html?img=2 保留 query 重定向", () => {
    at("/viewer.html?img=2");
    const viewer = screen.getByTestId("page-viewer");
    expect(viewer).toBeInTheDocument();
    expect(screen.getByAltText(awards[2].alt)).toBeInTheDocument();
  });
  it("未知路径回主页", () => {
    at("/nonsense");
    expect(screen.getByTestId("page-home")).toBeInTheDocument();
  });
});

describe("flex 链外壳", () => {
  it("路由外壳与页面外壳带类名（body→#root→.route-shell→.page-shell 的 flex 链靠它们延续）", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(container.querySelector(".route-shell")).not.toBeNull();
    expect(container.querySelector(".page-shell")).not.toBeNull();
  });
});

describe("札记路由", () => {
  it("/blog/不存在的slug 重定向到 /blog", async () => {
    at("/blog/no-such-note");
    expect(await screen.findByTestId("page-blog")).toBeInTheDocument();
  });
  it("旧路径 /notes/:slug 不做兼容保留，按未知路径回主页", () => {
    at("/notes/harness-cold-start");
    expect(screen.getByTestId("page-home")).toBeInTheDocument();
  });
  it("已落地文章可达:标题、正文、首发尾注与底部评论区", async () => {
    at("/blog/harness-cold-start");
    expect(await screen.findByTestId("page-note")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { level: 1, name: "关于 Harness 的讨论，附冷启动工具" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/harness-kit/)).toBeInTheDocument();
    expect(
      await screen.findByText("还没有评论，欢迎留下第一条讨论。"),
    ).toBeInTheDocument();
    expect(screen.getByText("LinuxDo").closest("a")).toHaveAttribute(
      "href",
      "https://linux.do/t/topic/2481591",
    );
    const backLink = screen.getByRole("link", { name: "← 博客论坛" });
    expect(backLink).toHaveAttribute("href", "/blog");
    expect(document.title).toBe("王景宏 · 博客论坛 · 关于 Harness 的讨论，附冷启动工具");
  });
});

describe("跨页滚动复位", () => {
  function NavControls() {
    const navigate = useNavigate();
    return (
      <div>
        <button onClick={() => navigate(-1)}>go-back</button>
        <button onClick={() => navigate("/blog#section")}>go-hash</button>
      </div>
    );
  }

  it("PUSH 跳转无 hash 时在退场动画完成后复位到顶部，POP 与带 #hash 跳转不复位", async () => {
    sessionStorage.setItem(SPLASH_KEY, "1");
    const scrollSpy = vi.spyOn(window, "scrollTo");

    render(
      <MemoryRouter initialEntries={["/"]}>
        <NavControls />
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("page-home")).toBeInTheDocument();
    scrollSpy.mockClear();

    // 1. 从主页点击「证书画廊」链接进入 /awards（PUSH）→ 退场结束后调用 scrollTo(0, 0)
    fireEvent.click(
      within(screen.getByTestId("page-home")).getByRole("link", { name: /证书画廊/ }),
    );
    await waitFor(() => {
      expect(screen.getByTestId("page-awards")).toBeInTheDocument();
      expect(scrollSpy).toHaveBeenCalledWith(0, 0);
    });

    // 2. 浏览器后退（POP）回主页 → 不调用 scrollTo
    scrollSpy.mockClear();
    fireEvent.click(screen.getByText("go-back"));
    await waitFor(() => {
      expect(screen.getByTestId("page-home")).toBeInTheDocument();
    });
    await new Promise((r) => setTimeout(r, 30));
    expect(scrollSpy).not.toHaveBeenCalled();

    // 3. 跳转到带 #hash 的目标（/blog#section）→ 不调用 scrollTo
    scrollSpy.mockClear();
    fireEvent.click(screen.getByText("go-hash"));
    await waitFor(() => {
      expect(screen.getByTestId("page-blog")).toBeInTheDocument();
    });
    await new Promise((r) => setTimeout(r, 30));
    expect(scrollSpy).not.toHaveBeenCalled();
  });
});

describe("全站顶栏挂载边界与会话同步", () => {
  it("/viewer、/viewer/ 与 /viewer.html 不渲染顶栏，其余路由固定渲染顶栏", () => {
    sessionStorage.setItem(SPLASH_KEY, "1");

    for (const viewerPath of ["/viewer?img=1", "/viewer/?img=1", "/viewer.html?img=1"]) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[viewerPath]}>
          <App />
        </MemoryRouter>,
      );
      expect(screen.getByTestId("page-viewer")).toBeInTheDocument();
      expect(screen.queryByRole("navigation", { name: "主导航" })).toBeNull();
      unmount();
    }

    for (const normalPath of ["/", "/blog", "/vlog", "/awards"]) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[normalPath]}>
          <App />
        </MemoryRouter>,
      );
      expect(screen.getByRole("navigation", { name: "主导航" })).toBeInTheDocument();
      unmount();
    }
  });

  it("直接打开 /blog/harness-cold-start 请求 /api/me/ 2 次；从 /blog SPA 进入札记及在札记间切换每次只增 1 次", async () => {
    sessionStorage.setItem(SPLASH_KEY, "1");
    let meCount = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCount += 1;
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user: null,
              csrfToken: "test-csrf",
              guestCommentsAllowed: true,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.startsWith("/api/notes/")) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [], nextBefore: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url === "/harness/data.json") {
        return Promise.resolve(
          new Response(JSON.stringify({ threads: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected test fetch: ${url}`));
    });

    // 1. 直接打开札记页：SessionProvider 1 次 + NoteComments 1 次 = 2 次
    const direct = render(
      <MemoryRouter initialEntries={["/blog/harness-cold-start"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("还没有评论，欢迎留下第一条讨论。"),
    ).toBeInTheDocument();
    expect(meCount).toBe(2);
    direct.unmount();

    // 2. 从 /blog 经 SPA 导航进入札记，再切换到另一篇札记：每次仅增加 1 次请求
    meCount = 0;
    function NoteJumper() {
      const navigate = useNavigate();
      return (
        <div>
          <button type="button" onClick={() => navigate("/blog/harness-cold-start")}>
            to-note-1
          </button>
          <button type="button" onClick={() => navigate("/blog/node-event-loop")}>
            to-note-2
          </button>
        </div>
      );
    }

    render(
      <MemoryRouter initialEntries={["/blog"]}>
        <NoteJumper />
        <App />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(meCount).toBe(1);
    });

    fireEvent.click(screen.getByRole("button", { name: "to-note-1" }));
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "关于 Harness 的讨论，附冷启动工具",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("还没有评论，欢迎留下第一条讨论。"),
    ).toBeInTheDocument();
    expect(meCount).toBe(2);

    fireEvent.click(screen.getByRole("button", { name: "to-note-2" }));
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(meCount).toBe(3);
    });
  });

  it("NoteComments 挂载、点击「重试连接」与 409 冲突刷新后均同步更新顶栏身份，且 syncSession 不额外请求", async () => {
    sessionStorage.setItem(SPLASH_KEY, "1");
    let meCalls = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        // 第 1 次（Provider 初次）：未登录
        if (meCalls === 1) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                user: null,
                csrfToken: "csrf-1",
                guestCommentsAllowed: true,
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        // 第 2 次（切入札记 A 时 NoteComments 挂载）：返回「挂载同步用户」，顶栏立即同步
        if (meCalls === 2) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                user: { id: 3, displayName: "挂载同步用户", isCommentAdmin: false },
                csrfToken: "csrf-2",
                guestCommentsAllowed: true,
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        // 第 3 次（切入札记 B 时 NoteComments 初次）：模拟失败以测「重试连接」
        if (meCalls === 3) {
          return Promise.reject(new Error("temporary me failure"));
        }
        // 第 4 次（点击「重试连接」）：返回已登录「读者甲」，应同步给顶栏
        if (meCalls === 4) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                user: { id: 5, displayName: "读者甲", isCommentAdmin: false },
                csrfToken: "csrf-4",
                guestCommentsAllowed: true,
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        // 第 5 次（409 冲突刷新）：更新为站主「王景宏」，应同步给顶栏
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user: { id: 1, displayName: "王景宏", isCommentAdmin: true },
              csrfToken: "csrf-5",
              guestCommentsAllowed: true,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (
        url === "/api/notes/node-event-loop/comments/" &&
        init?.method === "POST"
      ) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              code: "author_state_changed",
              actualAuthorKind: "member",
              message: "当前登录状态已变化，请确认后再提交评论。",
            }),
            { status: 409, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.startsWith("/api/notes/")) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [], nextBefore: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url === "/harness/data.json") {
        return Promise.resolve(
          new Response(JSON.stringify({ threads: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected test fetch: ${url}`));
    });

    function SyncNav() {
      const navigate = useNavigate();
      return (
        <div>
          <button type="button" onClick={() => navigate("/blog/harness-cold-start")}>
            open-note-a
          </button>
          <button type="button" onClick={() => navigate("/blog/node-event-loop")}>
            open-note-b
          </button>
        </div>
      );
    }

    const { container } = render(
      <MemoryRouter initialEntries={["/blog"]}>
        <SyncNav />
        <App />
      </MemoryRouter>,
    );

    const header = () => container.querySelector<HTMLElement>("header.site-header")!;

    // 1) 在 /blog 初始 Provider 未登录 -> 顶栏显示「登录」
    expect(
      await within(header()).findByRole("link", { name: "登录" }),
    ).toBeInTheDocument();
    expect(meCalls).toBe(1);

    // 2) 进入札记 A：NoteComments 挂载拉取成功 -> 顶栏同步变为「账号：挂载同步用户」（仅发第 2 次请求）
    fireEvent.click(screen.getByRole("button", { name: "open-note-a" }));
    expect(
      await within(header()).findByRole("button", { name: "账号：挂载同步用户" }),
    ).toBeInTheDocument();
    expect(meCalls).toBe(2);

    // 3) 进入札记 B：第 3 次请求失败 -> 评论区显示「重试连接」；点击「重试连接」发第 4 次请求，顶栏同步变为「账号：读者甲」
    fireEvent.click(screen.getByRole("button", { name: "open-note-b" }));
    expect(
      await screen.findByRole("button", { name: "重试连接" }),
    ).toBeInTheDocument();
    expect(meCalls).toBe(3);

    fireEvent.click(screen.getByRole("button", { name: "重试连接" }));
    expect(
      await within(header()).findByRole("button", { name: "账号：读者甲" }),
    ).toBeInTheDocument();
    expect(meCalls).toBe(4);

    // 4) 提交评论触发 409 冲突刷新：仅发 1 次 /api/me/（第 5 次），顶栏同步变为「账号：王景宏」
    fireEvent.change(screen.getByLabelText("评论内容"), {
      target: { value: "触发冲突同步" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));

    expect(
      await within(header()).findByRole("button", { name: "账号：王景宏" }),
    ).toBeInTheDocument();
    expect(meCalls).toBe(5);
  });

  it("停留在 /blog/:slug 时触发跨标签页 visibilitychange 刷新：顶栏与评论区双向同步登录与登出", async () => {
    sessionStorage.setItem(SPLASH_KEY, "1");
    let now = 2_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);

    let meCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        // 第 1、2 次（Provider 与 NoteComments 初始挂载）：均为未登录
        if (meCalls <= 2) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                user: null,
                csrfToken: "csrf-init",
                guestCommentsAllowed: true,
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        // 第 3 次（超过 10s 切回标签页）：跨标签页已登录为「跨页同步同学」
        if (meCalls === 3) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                user: { id: 18, displayName: "跨页同步同学", isCommentAdmin: false },
                csrfToken: "csrf-login",
                guestCommentsAllowed: true,
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        // 第 4 次（再超过 10s 切回标签页）：跨标签页退出登录回到访客
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user: null,
              csrfToken: "csrf-logout",
              guestCommentsAllowed: true,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.startsWith("/api/notes/")) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [], nextBefore: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected test fetch: ${url}`));
    });

    const { container } = render(
      <MemoryRouter initialEntries={["/blog/node-event-loop"]}>
        <App />
      </MemoryRouter>,
    );

    const header = () => container.querySelector<HTMLElement>("header.site-header")!;
    const commentsSection = () =>
      container.querySelector<HTMLElement>("section.note-comments")!;

    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
    expect(within(header()).getByRole("link", { name: "登录" })).toBeInTheDocument();
    expect(meCalls).toBe(2);

    // 1) 超过 10 秒后切回前台：Provider 刷新为「跨页同步同学」，顶栏与评论区同步更新
    now += 11_000;
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));

    expect(
      await within(header()).findByRole("button", { name: "账号：跨页同步同学" }),
    ).toBeInTheDocument();
    expect(
      await within(commentsSection()).findByText("跨页同步同学"),
    ).toBeInTheDocument();
    expect(meCalls).toBe(3);

    // 2) 再次超过 10 秒后切回前台：Provider 刷新回未登录，顶栏与评论区均同步回访客态
    now += 11_000;
    document.dispatchEvent(new Event("visibilitychange"));

    expect(
      await within(header()).findByRole("link", { name: "登录" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
    expect(meCalls).toBe(4);
  });
});
