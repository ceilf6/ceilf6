import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import Home from "./Home";

const wrap = () =>
  render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  );

describe("Home 五幕结构", () => {
  it("Hero 与 README 区共存,四卡不变项仍在", () => {
    wrap();
    expect(screen.getByRole("heading", { level: 1, name: "王景宏" })).toBeInTheDocument();
    expect(screen.getByText(/你好，我是/)).toBeInTheDocument();
    // 四卡不变项(顺序含义由 ReadmeCards.test 深度守护,这里守存在性)
    expect(screen.getByAltText("Stats").closest("a")).toHaveAttribute("href", "https://github.com/ceilf6");
    expect(screen.getByAltText("Hugging Face").closest("a")).toHaveAttribute("href", "https://huggingface.co/ceilf6");
  });
  it("幕结构齐备且标题升级为个人主页", () => {
    const { container } = wrap();
    expect(container.querySelector(".act-hero")).not.toBeNull();
    expect(container.querySelector(".act-cards")).not.toBeNull();
    expect(container.querySelector(".act-gallery")).not.toBeNull();
    expect(document.title).toBe("王景宏 · 个人主页");
  });
});
