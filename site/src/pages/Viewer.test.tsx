import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { awards } from "../data/awards";
import Viewer from "./Viewer";

const at = (search: string) =>
  render(
    <MemoryRouter initialEntries={[`/viewer${search}`]}>
      <Routes>
        <Route path="/viewer" element={<Viewer />} />
        <Route path="/" element={<div data-testid="home-probe" />} />
      </Routes>
    </MemoryRouter>,
  );

describe("Viewer", () => {
  it("加载完成后提供指向原件的直达链接", () => {
    at("?img=1");
    fireEvent.load(screen.getByAltText(awards[1].alt));
    const link = screen.getByText("查看原件").closest("a");
    expect(link).toHaveAttribute("href", awards[1].src);
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("按 img 参数显示对应大图", () => {
    at("?img=1");
    expect(screen.getByAltText(awards[1].alt)).toHaveAttribute(
      "src",
      awards[1].display,
    );
  });

  it("img 越界或非法显示错误态", () => {
    at("?img=99");
    expect(screen.getByText("图片未找到")).toBeInTheDocument();
    at("?img=abc");
    expect(screen.getAllByText("图片未找到").length).toBeGreaterThan(0);
  });

  it("prev 从 0 环绕到末张，next 从末张环绕到 0", () => {
    at("?img=0");
    fireEvent.click(screen.getByTitle("上一张 (←)"));
    expect(screen.getByAltText(awards[awards.length - 1].alt)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("下一张 (→)"));
    expect(screen.getByAltText(awards[0].alt)).toBeInTheDocument();
  });

  it("方向键切换、Escape 回主页", () => {
    at("?img=2");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByAltText(awards[3].alt)).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByTestId("home-probe")).toBeInTheDocument();
  });

  it("触摸左滑超阈值切下一张，小位移不动", () => {
    at("?img=0");
    // dx = -120（|dx|>50 且水平主导）→ 下一张
    fireEvent.touchStart(document, { touches: [{ clientX: 300, clientY: 100 }] });
    fireEvent.touchEnd(document, { changedTouches: [{ clientX: 180, clientY: 110 }] });
    expect(screen.getByAltText(awards[1].alt)).toBeInTheDocument();
    // dx = -30（|dx|<50）→ 不动
    fireEvent.touchStart(document, { touches: [{ clientX: 300, clientY: 100 }] });
    fireEvent.touchEnd(document, { changedTouches: [{ clientX: 270, clientY: 100 }] });
    expect(screen.getByAltText(awards[1].alt)).toBeInTheDocument();
  });

  it("点击大图回主页", () => {
    at("?img=4");
    fireEvent.click(screen.getByAltText(awards[4].alt));
    expect(screen.getByTestId("home-probe")).toBeInTheDocument();
  });
});
