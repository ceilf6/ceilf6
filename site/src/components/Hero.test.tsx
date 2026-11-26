import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Hero } from "./Hero";
import heroCss from "./Hero.css?raw";

describe("Hero", () => {
  it("渲染姓名与 bio,@提及是外链", () => {
    render(<Hero />);
    expect(screen.getByRole("heading", { level: 1, name: "王景宏" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "@FrontAgent" });
    expect(link).toHaveAttribute("href", "https://github.com/ceilf6/FrontAgent");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("不渲染首屏滚动提示 DOM 节点或文字，且样式文件不含遗留选择器与关键帧", () => {
    const { container } = render(<Hero />);
    expect(container.querySelector(".hero-scroll-hint")).toBeNull();
    expect(screen.queryByText(/滚动认识我/)).toBeNull();
    expect(heroCss).not.toContain("hero-scroll-hint");
    expect(heroCss).not.toContain("hint-bob");
  });
});
