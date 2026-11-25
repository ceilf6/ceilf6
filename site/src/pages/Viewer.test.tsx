import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BrowserRouter, MemoryRouter, Route, Routes, useLocation } from "react-router";
import { awards } from "../data/awards";
import { WaterfallGallery } from "../components/WaterfallGallery";
import Viewer from "./Viewer";

const at = (search: string, state?: unknown) =>
  render(
    <MemoryRouter initialEntries={[{ pathname: "/viewer", search, state }]}>
      <Routes>
        <Route path="/viewer" element={<Viewer />} />
        <Route path="/awards" element={<div data-testid="awards-probe" />} />
        <Route path="/" element={<div data-testid="home-probe" />} />
      </Routes>
    </MemoryRouter>,
  );

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

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

  it("浏览器标题统一为 王景宏 · 证书画廊 · <证书名>，无效序号回退为 王景宏 · 证书画廊", () => {
    document.title = "王景宏 · 个人主页";
    const { unmount } = at("?img=1");
    expect(document.title).toBe(`王景宏 · 证书画廊 · ${awards[1].alt}`);
    unmount();

    document.title = "王景宏 · 个人主页";
    at("?img=99");
    expect(document.title).toBe("王景宏 · 证书画廊");
  });

  it("从 /awards 点击卡片进入后，翻页再关闭回到 /awards，且 history.state 保留 from", () => {
    function StateProbe() {
      const location = useLocation();
      const from =
        typeof location.state === "object" && location.state !== null && "from" in location.state
          ? String((location.state as { from?: unknown }).from)
          : "";
      return <output data-testid="loc-from">{from}</output>;
    }

    window.history.replaceState(null, "", "/awards");
    render(
      <BrowserRouter>
        <StateProbe />
        <Routes>
          <Route path="/awards" element={<WaterfallGallery />} />
          <Route path="/viewer" element={<Viewer />} />
          <Route path="/" element={<div data-testid="home-probe" />} />
        </Routes>
      </BrowserRouter>,
    );

    fireEvent.click(screen.getByAltText(awards[0].alt));
    expect(screen.getByTestId("page-viewer")).toBeInTheDocument();
    expect(screen.getByTestId("loc-from")).toHaveTextContent("/awards");

    // 先点下一张，再按 ArrowLeft，验证 replace 翻页不丢失 location.state 与 window.history.state.usr
    fireEvent.click(screen.getByTitle("下一张 (→)"));
    expect(screen.getByAltText(awards[1].alt)).toBeInTheDocument();
    expect(screen.getByTestId("loc-from")).toHaveTextContent("/awards");
    expect(window.history.state?.usr).toEqual({ from: "/awards" });

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(screen.getByAltText(awards[0].alt)).toBeInTheDocument();
    expect(screen.getByTestId("loc-from")).toHaveTextContent("/awards");
    expect(window.history.state?.usr).toEqual({ from: "/awards" });

    // 触屏左滑翻页同样保留 history.state.usr
    fireEvent.touchStart(document, { touches: [{ clientX: 300, clientY: 100 }] });
    fireEvent.touchEnd(document, { changedTouches: [{ clientX: 180, clientY: 105 }] });
    expect(screen.getByAltText(awards[1].alt)).toBeInTheDocument();
    expect(window.history.state?.usr).toEqual({ from: "/awards" });

    // Escape 关闭回到 /awards，再次点击卡片进入并点击大图关闭同样回到 /awards
    fireEvent.keyDown(document, { key: "Escape" });
    expect(window.location.pathname).toBe("/awards");

    fireEvent.click(screen.getByAltText(awards[2].alt));
    expect(screen.getByTestId("page-viewer")).toBeInTheDocument();
    fireEvent.click(screen.getByAltText(awards[2].alt));
    expect(window.location.pathname).toBe("/awards");
  });

  it.each([
    [{ from: "https://evil.example" }],
    [{ from: "//evil.example" }],
    [{ from: "/unknown" }],
    [undefined],
  ])("非白名单或缺失来源 %o 一律关闭回 /", (badState) => {
    const { unmount } = at("?img=0", badState);
    fireEvent.click(screen.getByAltText(awards[0].alt));
    expect(screen.getByTestId("home-probe")).toBeInTheDocument();
    unmount();
  });
});
