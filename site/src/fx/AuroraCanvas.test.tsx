import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { AuroraCanvas } from "./AuroraCanvas";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AuroraCanvas", () => {
  it("无 WebGL(jsdom)渲染静态渐变兜底 div", () => {
    const { container } = render(<AuroraCanvas className="hero-aurora" />);
    // effect 里同步判定失败并切换
    expect(container.querySelector(".aurora-fallback")).not.toBeNull();
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("兜底 div 保留传入 className 且对读屏隐藏", () => {
    const { container } = render(<AuroraCanvas className="hero-aurora" />);
    const fallback = container.querySelector(".aurora-fallback");
    expect(fallback).toHaveClass("hero-aurora");
    expect(fallback).toHaveAttribute("aria-hidden", "true");
  });

  it("prefers-reduced-motion: reduce 直接走兜底，不触碰 WebGL", () => {
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: query.includes("prefers-reduced-motion"),
          media: query,
          addEventListener() {},
          removeEventListener() {},
          addListener() {},
          removeListener() {},
          onchange: null,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    );
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    const { container } = render(<AuroraCanvas className="hero-aurora" />);
    expect(container.querySelector(".aurora-fallback")).not.toBeNull();
    expect(getContext).not.toHaveBeenCalled();
  });
});
