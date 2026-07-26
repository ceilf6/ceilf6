import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReadmeCards } from "./ReadmeCards";

const setup = () =>
  render(
    <MemoryRouter>
      <ReadmeCards />
    </MemoryRouter>,
  );

describe("ReadmeCards", () => {
  it("渲染 4 张卡，外链卡新开页、站内卡走路由", () => {
    setup();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(4);
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[1]).toHaveAttribute("href", "/blog");
    expect(links[1]).not.toHaveAttribute("target");
  });

  it("图片加载完成前显示加载态，onLoad 后消失", () => {
    setup();
    expect(screen.getAllByText("加载中")).toHaveLength(4);
    fireEvent.load(screen.getByAltText("Stats"));
    expect(screen.getAllByText("加载中")).toHaveLength(3);
  });

  it("图片加载失败显示失败态", () => {
    setup();
    fireEvent.error(screen.getByAltText("Blog"));
    expect(screen.getByText("加载失败")).toBeInTheDocument();
  });
});
