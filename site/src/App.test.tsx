import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AppRoutes } from "./App";

const at = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );

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
    expect(screen.getByTestId("viewer-search")).toHaveTextContent("?img=2");
  });
  it("未知路径回主页", () => {
    at("/nonsense");
    expect(screen.getByTestId("page-home")).toBeInTheDocument();
  });
});
