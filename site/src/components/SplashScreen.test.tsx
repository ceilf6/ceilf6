import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitForElementToBeRemoved } from "@testing-library/react";
import { SPLASH_KEY, SplashScreen } from "./SplashScreen";

describe("SplashScreen", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useRealTimers();
  });

  afterEach(() => {
    window.history.pushState({}, "", "/");
    vi.restoreAllMocks();
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

  it("开屏期间锁住文档滚动，退场后恢复", async () => {
    render(<SplashScreen />);
    expect(document.documentElement.style.overflow).toBe("hidden");
    await waitForElementToBeRemoved(() => screen.queryByTestId("splash"), {
      timeout: 5000,
    });
    expect(document.documentElement.style.overflow).toBe("");
  }, 9000);

  it("jsdom 无 canvas 2D 时走 chars 兜底路径（字符逐个渲染）", async () => {
    sessionStorage.clear();
    render(<SplashScreen />);
    expect(await screen.findByText("王")).toBeInTheDocument();
    expect(screen.getByText("宏")).toBeInTheDocument();
  });

  it("深链路由同样尝试粒子路径（全路由粒子开屏，2026-07-28 用户拍板）", async () => {
    window.history.pushState({}, "", "/viewer?img=1");
    // 观察粒子路径是否被尝试：NameParticles 挂载即会请求 getContext("2d")
    //（AuroraCanvas 只请求 webgl，不干扰观察）。jsdom 下拿到 null，
    // onUnsupported 自然落回 chars，逐字仍应出现。
    const getCtx = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    render(<SplashScreen />);
    expect(getCtx.mock.calls.some(([kind]) => kind === "2d")).toBe(true);
    expect(await screen.findByText("王")).toBeInTheDocument();
  });
});
