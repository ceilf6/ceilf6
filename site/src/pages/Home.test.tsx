import { afterEach, describe, expect, it, vi } from "vitest";
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
  // Home 的 useEffect 动态 import scrollActs(gsap chunk);必须等它落定再放行 teardown,
  // 否则 CI 慢盘下 gsap 在环境销毁后才到达 → EnvironmentTeardownError(2026-07-28 CI 实翻)
  afterEach(() => vi.dynamicImportSettled());
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
  it("hero 之后的内容包进 .acts-curtain 窗帘层(sticky hero 上滑过的不透明幕布)", () => {
    const { container } = wrap();
    const curtain = container.querySelector(".acts-curtain");
    expect(curtain).not.toBeNull();
    expect(curtain!.querySelector(".act-cards")).not.toBeNull();
    expect(curtain!.querySelector(".act-gallery")).not.toBeNull();
    // hero 必须在窗帘层外,否则钉住/覆盖关系不成立
    expect(curtain!.querySelector(".act-hero")).toBeNull();
  });
  it("两节标题均为 h2 内可跳转链接,指向 /awards 与 /blog,且三处 data-act-reveal 不变", () => {
    const { container } = wrap();
    const galleryHeading = screen.getByRole("heading", { level: 2, name: /证书画廊/ });
    const galleryLink = galleryHeading.querySelector("a");
    expect(galleryLink).not.toBeNull();
    expect(galleryLink).toHaveAttribute("href", "/awards");
    expect(galleryLink).toHaveTextContent(/证书画廊\s*→/);

    const notesHeading = screen.getByRole("heading", { level: 2, name: /博客论坛/ });
    const notesLink = notesHeading.querySelector("a");
    expect(notesLink).not.toBeNull();
    expect(notesLink).toHaveAttribute("href", "/blog");
    expect(notesLink).toHaveTextContent(/博客论坛\s*→/);

    const reveals = container.querySelectorAll("[data-act-reveal]");
    expect(reveals).toHaveLength(3);
    expect(reveals[0]).toHaveClass("act-cards");
    expect(reveals[1]).toHaveClass("act-gallery");
    expect(reveals[2]).toHaveClass("act-notes");
    expect(document.title).toBe("王景宏 · 个人主页");
  });
});
