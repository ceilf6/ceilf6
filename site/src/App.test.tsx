import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
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

afterEach(() => {
  vi.restoreAllMocks();
});

describe("routes", () => {
  it("/ 渲染主页", () => {
    at("/");
    expect(screen.getByTestId("page-home")).toBeInTheDocument();
  });
  it.each(["/blog", "/vlog"])("%s 渲染对应页面", (p) => {
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
  it("/notes/不存在的slug 重定向到 /blog", async () => {
    at("/notes/no-such-note");
    expect(await screen.findByTestId("page-blog")).toBeInTheDocument();
  });
  it("已落地文章可达:标题、正文、首发尾注与底部评论区", async () => {
    at("/notes/harness-cold-start");
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
  });
});
