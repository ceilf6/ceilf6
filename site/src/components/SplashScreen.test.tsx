import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitForElementToBeRemoved } from "@testing-library/react";
import { SPLASH_KEY, SplashScreen } from "./SplashScreen";

describe("SplashScreen", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useRealTimers();
  });

  it("首次进站渲染开屏并写入 session 标记", () => {
    render(<SplashScreen />);
    expect(screen.getByTestId("splash")).toBeInTheDocument();
    expect(sessionStorage.getItem(SPLASH_KEY)).toBe("1");
  });

  it("同一会话第二次渲染不再出现", () => {
    sessionStorage.setItem(SPLASH_KEY, "1");
    render(<SplashScreen />);
    expect(screen.queryByTestId("splash")).not.toBeInTheDocument();
  });

  // 走真实计时器：framer-motion 的帧循环在模块加载时就捕获了真实 requestAnimationFrame
  // （motion-dom/frameloop/frame.mjs），vi 的假时钟推不动它，AnimatePresence 的退场
  // 因此永远不会完成。假时钟只能让 1400ms 定时器提前触发，元素仍卡在退场动画里。
  it("到时自动退场", async () => {
    render(<SplashScreen />);
    expect(screen.getByTestId("splash")).toBeInTheDocument();
    await waitForElementToBeRemoved(() => screen.queryByTestId("splash"), {
      timeout: 5000,
    });
  }, 9000);
});
