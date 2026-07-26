import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { awards } from "../data/awards";
import { WaterfallGallery } from "./WaterfallGallery";

function ViewerProbe() {
  const { search } = useLocation();
  return <div data-testid="viewer-probe">{search}</div>;
}

const setup = () =>
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<WaterfallGallery />} />
        <Route path="/viewer" element={<ViewerProbe />} />
      </Routes>
    </MemoryRouter>,
  );

describe("WaterfallGallery", () => {
  it("为每条获奖记录渲染一张缩略卡", () => {
    setup();
    expect(screen.getAllByRole("img")).toHaveLength(awards.length);
    expect(screen.getByAltText(awards[0].alt)).toHaveAttribute(
      "src",
      awards[0].thumb,
    );
  });

  it("键盘 Enter 激活卡片进入 viewer（可达性）", () => {
    setup();
    const card = screen.getByLabelText(`查看证书：${awards[5].alt}`);
    expect(card).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(card, { key: "Enter" });
    expect(screen.getByTestId("viewer-probe")).toBeInTheDocument();
  });

  it("点击第 N 张卡进入 /viewer?img=N", () => {
    setup();
    fireEvent.click(screen.getByAltText(awards[3].alt));
    const probe = screen.getByTestId("viewer-probe");
    expect(probe).toBeInTheDocument();
    expect(probe).toHaveTextContent("?img=3");
  });
});
