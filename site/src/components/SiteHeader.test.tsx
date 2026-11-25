import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { GITHUB_URL, readmeCards } from "../data/site";
import { SessionProvider } from "../session/SessionProvider";
import { SiteHeader } from "./SiteHeader";
import rawHeaderCss from "./SiteHeader.css?raw";
import rawGlobalCss from "../styles/global.css?raw";

const headerCss =
  rawHeaderCss ||
  readFileSync(resolve(process.cwd(), "src/components/SiteHeader.css"), "utf8");
const globalCss =
  rawGlobalCss ||
  readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");
const stageCss = readFileSync(
  resolve(process.cwd(), "src/components/PlatformStage.css"),
  "utf8",
);
const noteCss = readFileSync(
  resolve(process.cwd(), "src/pages/Note.css"),
  "utf8",
);
const awardsCss = readFileSync(
  resolve(process.cwd(), "src/pages/Awards.css"),
  "utf8",
);

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("SiteHeader 全站顶栏", () => {
  afterEach(() => {
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      writable: true,
      value: 0,
    });
    vi.restoreAllMocks();
  });

  it("导出 GITHUB_URL 并与 readmeCards 第一项共用，顶栏 GitHub 外链属性完整", () => {
    expect(GITHUB_URL).toBe("https://github.com/ceilf6");
    expect(readmeCards[0].href).toBe(GITHUB_URL);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <SiteHeader />
      </MemoryRouter>,
    );

    const ghLink = screen.getByRole("link", {
      name: "GitHub 主页（新窗口打开）",
    });
    expect(ghLink).toHaveAttribute("href", "https://github.com/ceilf6");
    expect(ghLink).toHaveAttribute("target", "_blank");
    expect(ghLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(ghLink.querySelector("svg")).not.toBeNull();
  });

  it("会话加载中渲染骨架占位；未登录或 /api/me/ 500/网络异常时渲染带编码 next 的原生登录链接", async () => {
    let resolveMe: ((res: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveMe = resolve;
        }),
    );

    const { container, unmount } = render(
      <MemoryRouter initialEntries={["/blog?tab=notes&q=1"]}>
        <SessionProvider>
          <SiteHeader />
        </SessionProvider>
      </MemoryRouter>,
    );

    // 加载态：存在 aria-hidden 占位，不显示登录链接或头像按钮
    const skeleton = container.querySelector(".site-header-account-skeleton");
    expect(skeleton).not.toBeNull();
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("link", { name: "登录" })).toBeNull();
    expect(screen.queryByRole("button", { name: /账号/ })).toBeNull();

    // 未登录返回：显示原生 <a href="/accounts/login/?next=...">
    resolveMe?.(
      jsonResponse({
        user: null,
        csrfToken: "csrf-guest",
        guestCommentsAllowed: true,
      }),
    );

    const loginLink = await screen.findByRole("link", { name: "登录" });
    expect(loginLink.tagName).toBe("A");
    expect(loginLink).toHaveAttribute(
      "href",
      `/accounts/login/?next=${encodeURIComponent("/blog?tab=notes&q=1")}`,
    );

    unmount();

    // /api/me/ 500 降级显示「登录」
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ code: "error" }, 500),
    );
    const view500 = render(
      <MemoryRouter initialEntries={["/awards"]}>
        <SessionProvider>
          <SiteHeader />
        </SessionProvider>
      </MemoryRouter>,
    );

    const fallbackLogin = await screen.findByRole("link", { name: "登录" });
    expect(fallbackLogin).toHaveAttribute(
      "href",
      `/accounts/login/?next=${encodeURIComponent("/awards")}`,
    );
    view500.unmount();

    // /api/me/ 网络异常（fetch reject）同样降级显示「登录」
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );
    render(
      <MemoryRouter initialEntries={["/vlog"]}>
        <SessionProvider>
          <SiteHeader />
        </SessionProvider>
      </MemoryRouter>,
    );
    const netFallbackLogin = await screen.findByRole("link", { name: "登录" });
    expect(netFallbackLogin).toHaveAttribute(
      "href",
      `/accounts/login/?next=${encodeURIComponent("/vlog")}`,
    );
  });

  it("主导航在 /blog、/blog/:slug、/vlog、/awards 准确高亮并设置 aria-current=page", () => {
    const cases: Array<{ path: string; activeName: string | null }> = [
      { path: "/", activeName: null },
      { path: "/blog", activeName: "博客论坛" },
      { path: "/blog/harness-cold-start", activeName: "博客论坛" },
      { path: "/vlog", activeName: "项目视频" },
      { path: "/awards", activeName: "证书画廊" },
    ];

    for (const { path, activeName } of cases) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[path]}>
          <SiteHeader />
        </MemoryRouter>,
      );

      const nav = screen.getByRole("navigation", { name: "主导航" });
      expect(nav).toBeInTheDocument();

      for (const label of ["博客论坛", "项目视频", "证书画廊"]) {
        const link = screen.getByRole("link", { name: label });
        if (label === activeName) {
          expect(link).toHaveAttribute("aria-current", "page");
        } else {
          expect(link).not.toHaveAttribute("aria-current");
        }
      }
      unmount();
    }
  });

  it("在 / 点击站名「王景宏」阻止默认跳转并滚回页顶（含 prefers-reduced-motion 分支），在其他页正常回主页", () => {
    const scrollSpy = vi.spyOn(window, "scrollTo");

    // 1) 默认动画开启：smooth 滚回顶部
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      onchange: null,
      dispatchEvent: () => false,
    }));

    const { unmount } = render(
      <MemoryRouter initialEntries={["/"]}>
        <SiteHeader />
      </MemoryRouter>,
    );

    const brandOnHome = screen.getByRole("link", { name: "王景宏" });
    fireEvent.click(brandOnHome);
    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });

    // Cmd/Ctrl+Click 或中键点击放行默认浏览器新标签行为，不拦截不滚顶
    scrollSpy.mockClear();
    fireEvent.click(brandOnHome, { metaKey: true });
    fireEvent.click(brandOnHome, { ctrlKey: true });
    fireEvent.click(brandOnHome, { button: 1 });
    expect(scrollSpy).not.toHaveBeenCalled();
    unmount();

    // 2) prefers-reduced-motion: reduce 为真：auto 滚回顶部
    scrollSpy.mockClear();
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      onchange: null,
      dispatchEvent: () => false,
    }));

    const view2 = render(
      <MemoryRouter initialEntries={["/"]}>
        <SiteHeader />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("link", { name: "王景宏" }));
    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: "auto" });
    view2.unmount();

    // 3) 在 /blog 点击「王景宏」：SPA 路由返回 /
    render(
      <MemoryRouter initialEntries={["/blog"]}>
        <SiteHeader />
        <Routes>
          <Route path="/" element={<div data-testid="at-home" />} />
          <Route path="/blog" element={<div data-testid="at-blog" />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("at-blog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "王景宏" }));
    expect(screen.getByTestId("at-home")).toBeInTheDocument();
  });

  it("主页 scrollY===0 时顶栏为透明态而面板仍具独立深色磨砂类名，scrollY>8 或非主页切换为磨砂态", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        user: { id: 1, displayName: "王景宏", isCommentAdmin: true },
        csrfToken: "csrf-home",
        guestCommentsAllowed: true,
      }),
    );

    Object.defineProperty(window, "scrollY", {
      configurable: true,
      writable: true,
      value: 0,
    });

    const { container, unmount } = render(
      <MemoryRouter initialEntries={["/"]}>
        <SessionProvider>
          <SiteHeader />
        </SessionProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /账号/ })).toBeInTheDocument();
    });

    const header = container.querySelector("header.site-header")!;
    const panel = container.querySelector("#account-panel")!;
    expect(header).toHaveClass("is-transparent");
    expect(header).not.toHaveClass("is-frosted");
    expect(panel).toHaveClass("account-panel", "account-panel-frosted");

    // 滚动超过 8px：切换为磨砂底类名
    window.scrollY = 24;
    fireEvent.scroll(window);
    expect(header).toHaveClass("is-frosted");
    expect(header).not.toHaveClass("is-transparent");

    // 滚回顶部 scrollY = 0：恢复透明态类名
    window.scrollY = 0;
    fireEvent.scroll(window);
    expect(header).toHaveClass("is-transparent");
    expect(header).not.toHaveClass("is-frosted");

    unmount();

    // 非主页即使 scrollY === 0 也直接为磨砂底类名
    window.scrollY = 0;
    const blogView = render(
      <MemoryRouter initialEntries={["/blog"]}>
        <SiteHeader />
      </MemoryRouter>,
    );
    expect(blogView.container.querySelector("header.site-header")).toHaveClass(
      "is-frosted",
    );
  });

  it("样式护栏：--site-header-h 桌面 56px / 560px 防挤压 / 480px 88px 精确闭合，且顶部留白归属各页面 CSS", () => {
    expect(headerCss).toMatch(/z-index:\s*100\b/);
    expect(headerCss).toMatch(/@media\s*\(max-width:\s*560px\)/);
    expect(headerCss).toMatch(
      /@media\s*\(max-width:\s*480px\)\s*\{[\s\S]*?padding:\s*6px\s+12px\s+7px;/,
    );
    expect(globalCss).toContain("--site-header-h: 56px;");
    expect(globalCss).toMatch(
      /@media\s*\(max-width:\s*480px\)\s*\{[\s\S]*?--site-header-h:\s*88px;/,
    );
    expect(globalCss).not.toMatch(
      /(?:^|\n)\s*(?:body|#root|\.route-shell|\.page-shell)\s*\{[^}]*padding-top:/,
    );
    expect(globalCss).not.toContain(".stage-viewport");
    expect(globalCss).not.toContain(".note");
    expect(stageCss).toContain("calc(var(--site-header-h) + 32px)");
    expect(noteCss).toContain("calc(var(--site-header-h) + 32px)");
    expect(awardsCss).toContain("calc(var(--site-header-h) + 32px)");
  });
});
