import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
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

function findClosingBrace(css: string, openBraceIdx: number): number {
  let depth = 1;
  let j = openBraceIdx + 1;
  while (j < css.length && depth > 0) {
    if (css[j] === "{") depth += 1;
    else if (css[j] === "}") depth -= 1;
    j += 1;
  }
  return depth === 0 ? j - 1 : -1;
}

function stripMediaBlocks(css: string): string {
  let out = "";
  let i = 0;
  while (i < css.length) {
    const mediaIdx = css.indexOf("@media", i);
    if (mediaIdx === -1) {
      out += css.slice(i);
      break;
    }
    out += css.slice(i, mediaIdx);
    const openBrace = css.indexOf("{", mediaIdx);
    if (openBrace === -1) break;
    const closeBrace = findClosingBrace(css, openBrace);
    if (closeBrace === -1) break;
    i = closeBrace + 1;
  }
  return out;
}

function extractMediaBlock(css: string, headerRegex: RegExp): string | null {
  const match = headerRegex.exec(css);
  if (!match) return null;
  const openBrace = css.indexOf("{", match.index);
  if (openBrace === -1) return null;
  const closeBrace = findClosingBrace(css, openBrace);
  return closeBrace === -1 ? null : css.slice(openBrace + 1, closeBrace);
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("SiteHeader 全站单行顶栏", () => {
  afterEach(() => {
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      writable: true,
      value: 0,
    });
    vi.restoreAllMocks();
  });

  it("移除「王景宏」站名，主导航按顺序渲染「首页 · 博客论坛 · 项目视频 · 证书画廊」四项链接且保留 GitHub 外链", () => {
    expect(GITHUB_URL).toBe("https://github.com/ceilf6");
    expect(readmeCards[0].href).toBe(GITHUB_URL);

    const { container } = render(
      <MemoryRouter initialEntries={["/"]}>
        <SiteHeader />
      </MemoryRouter>,
    );

    expect(container.querySelector(".site-header-brand")).toBeNull();
    expect(screen.queryByText("王景宏")).toBeNull();

    const nav = screen.getByRole("navigation", { name: "主导航" });
    const navLinks = within(nav).getAllByRole("link");
    expect(navLinks.map((el) => el.textContent)).toEqual([
      "首页",
      "博客论坛",
      "项目视频",
      "证书画廊",
    ]);
    expect(navLinks.map((el) => el.getAttribute("href"))).toEqual([
      "/",
      "/blog",
      "/vlog",
      "/awards",
    ]);
    for (const link of navLinks) {
      expect(link).toHaveClass("site-header-nav-link");
    }

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

    const skeleton = container.querySelector(".site-header-account-skeleton");
    expect(skeleton).not.toBeNull();
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("link", { name: "登录" })).toBeNull();
    expect(screen.queryByRole("button", { name: /账号/ })).toBeNull();

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

  it("各路径下主导航仅对应的一项带 aria-current=page", () => {
    const cases: Array<{ path: string; activeName: string }> = [
      { path: "/", activeName: "首页" },
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
      for (const label of ["首页", "博客论坛", "项目视频", "证书画廊"]) {
        const link = within(nav).getByRole("link", { name: label });
        if (label === activeName) {
          expect(link).toHaveAttribute("aria-current", "page");
          expect(link).toHaveClass("is-active");
        } else {
          expect(link).not.toHaveAttribute("aria-current");
          expect(link).not.toHaveClass("is-active");
        }
      }
      unmount();
    }
  });

  it("在 / 点击「首页」平滑滚回页顶且不触发路由跳转（含 prefers-reduced-motion 与修饰键放行），在 /blog 点击跳回 /", () => {
    const scrollSpy = vi.spyOn(window, "scrollTo");

    function LocationKeyProbe() {
      const loc = useLocation();
      return <span data-testid="loc-key">{loc.key}</span>;
    }

    // 1) 默认动画开启：smooth 滚回顶部，且路由 key 不变（未触发跳转）
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
        <LocationKeyProbe />
      </MemoryRouter>,
    );

    const initialKey = screen.getByTestId("loc-key").textContent;
    const homeOnHome = screen.getByRole("link", { name: "首页" });
    fireEvent.click(homeOnHome);
    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
    expect(screen.getByTestId("loc-key").textContent).toBe(initialKey);

    // 修饰键（metaKey / ctrlKey / shiftKey / altKey）或中键点击放行，不拦截
    scrollSpy.mockClear();
    fireEvent.click(homeOnHome, { metaKey: true });
    fireEvent.click(homeOnHome, { ctrlKey: true });
    fireEvent.click(homeOnHome, { shiftKey: true });
    fireEvent.click(homeOnHome, { altKey: true });
    fireEvent.click(homeOnHome, { button: 1 });
    expect(scrollSpy).not.toHaveBeenCalled();
    unmount();

    // 2) prefers-reduced-motion: reduce 下 behavior 为 auto
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
    fireEvent.click(screen.getByRole("link", { name: "首页" }));
    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: "auto" });
    view2.unmount();

    // 3) 在 /blog 点击「首页」：SPA 路由跳到 /
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
    fireEvent.click(screen.getByRole("link", { name: "首页" }));
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

    window.scrollY = 24;
    fireEvent.scroll(window);
    expect(header).toHaveClass("is-frosted");
    expect(header).not.toHaveClass("is-transparent");

    window.scrollY = 0;
    fireEvent.scroll(window);
    expect(header).toHaveClass("is-transparent");
    expect(header).not.toHaveClass("is-frosted");

    unmount();

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

  it("样式护栏：单行 56px、左对齐导航与 margin-left:auto、基础规则 min-height:32px、359px 隐藏 GitHub、html text-size-adjust", () => {
    expect(headerCss).toMatch(/z-index:\s*100\b/);

    // 1) SiteHeader.css 与 global.css 均不再含 88px、grid-template-rows、.site-header-brand
    for (const css of [headerCss, globalCss]) {
      expect(css).not.toContain("88px");
      expect(css).not.toContain("grid-template-rows");
      expect(css).not.toContain(".site-header-brand");
    }

    // 2) --site-header-h 仅有一个定义且值为 56px
    const headerVarDefs = [...globalCss.matchAll(/--site-header-h\s*:\s*([^;]+);/g)];
    expect(headerVarDefs).toHaveLength(1);
    expect(headerVarDefs[0][1].trim()).toBe("56px");

    // 3) 基础规则检查（剥离所有 @media 块之后）
    const baseHeaderCss = stripMediaBlocks(headerCss);
    expect(baseHeaderCss).toMatch(
      /\.site-header-actions\s*\{[^}]*margin-left:\s*auto\b/s,
    );
    expect(baseHeaderCss).not.toMatch(
      /\.site-header-inner\s*\{[^}]*justify-content:\s*space-between/s,
    );
    expect(baseHeaderCss).toMatch(
      /\.site-header-nav-link\s*\{[^}]*min-height:\s*32px\b/s,
    );
    expect(baseHeaderCss).toMatch(
      /\.site-header-nav-link\s*\{[^}]*display:\s*inline-flex\b/s,
    );

    // 4) <= 560px 压缩规则与 <= 359px 隐藏 GitHub 规则
    const media560 = extractMediaBlock(headerCss, /@media\s*\(\s*max-width:\s*560px\s*\)/);
    expect(media560).not.toBeNull();
    expect(media560!).toMatch(/\.site-header-github\s*\{[^}]*width:\s*28px/s);
    expect(media560!).toMatch(/\.site-header-github\s*\{[^}]*height:\s*32px/s);

    const media359 = extractMediaBlock(headerCss, /@media\s*\(\s*max-width:\s*359px\s*\)/);
    expect(media359).not.toBeNull();
    expect(media359!).toMatch(/\.site-header-github\s*\{[^}]*display:\s*none\b/s);

    // 5) global.css html 带 text-size-adjust: 100%
    expect(globalCss).toMatch(
      /(?:^|\n)html\s*\{[^}]*-webkit-text-size-adjust:\s*100%/s,
    );
    expect(globalCss).toMatch(
      /(?:^|\n)html\s*\{[^}]*(?<![-\w])text-size-adjust:\s*100%/s,
    );

    // 6) 顶部留白仍归属各页面 CSS，global.css 不对根容器设全局 padding-top
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
