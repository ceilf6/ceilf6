import { beforeEach, describe, expect, it, vi } from "vitest";

const gsapMock = vi.hoisted(() => ({
  registerPlugin: vi.fn(),
  context: vi.fn((fn: () => void) => {
    fn();
    return { revert: vi.fn() };
  }),
  from: vi.fn(),
  to: vi.fn(),
}));
vi.mock("gsap", () => ({ default: gsapMock }));
vi.mock("gsap/ScrollTrigger", () => ({ ScrollTrigger: {} }));

import { initScrollActs } from "./scrollActs";

describe("initScrollActs", () => {
  beforeEach(() => vi.clearAllMocks());

  it("为每个 [data-act-reveal] 建立入场触发", () => {
    const root = document.createElement("div");
    root.innerHTML = `<section data-act-reveal></section><section data-act-reveal></section>`;
    initScrollActs(root, { force: true });
    expect(gsapMock.registerPlugin).toHaveBeenCalled();
    expect(gsapMock.from).toHaveBeenCalledTimes(2);
  });
  it("画廊卡片有 stagger 编排;hero 视差已随窗帘结构删除(sticky hero 不动,gsap.to 零调用)", () => {
    const root = document.createElement("div");
    root.innerHTML = `
      <section class="act-hero"><div class="hero-bg"></div></section>
      <section class="act-gallery"><div class="gallery"><div class="card"></div></div></section>`;
    initScrollActs(root, { force: true });
    const fromCalls = gsapMock.from.mock.calls;
    expect(fromCalls.some(([, cfg]) => cfg.stagger !== undefined)).toBe(true);
    expect(gsapMock.to).not.toHaveBeenCalled();
  });
  it("返回 cleanup,调用即 revert", () => {
    const root = document.createElement("div");
    const cleanup = initScrollActs(root, { force: true });
    cleanup();
    expect(gsapMock.context.mock.results[0].value.revert).toHaveBeenCalled();
  });
  it("所有 from 入场都带 clearProps,完成后释放 inline transform(否则压死画廊 hover lift)", () => {
    const root = document.createElement("div");
    root.innerHTML = `
      <section data-act-reveal></section>
      <section class="act-gallery"><div class="gallery"><div class="card"></div></div></section>`;
    initScrollActs(root, { force: true });
    expect(gsapMock.from).toHaveBeenCalled();
    for (const [, cfg] of gsapMock.from.mock.calls) {
      expect(cfg.clearProps).toBe("transform,opacity");
    }
  });
  it("init 时画廊已在视口内 → 跳过 stagger 入场(防已见内容被压回重闪)", () => {
    const root = document.createElement("div");
    root.innerHTML = `<section class="act-gallery"><div class="gallery"><div class="card"></div></div></section>`;
    const act = root.querySelector(".act-gallery") as HTMLElement;
    vi.spyOn(act, "getBoundingClientRect").mockReturnValue({
      top: 120,
      bottom: 640,
    } as DOMRect);
    initScrollActs(root, { force: true });
    expect(gsapMock.from.mock.calls.some(([, cfg]) => cfg.stagger !== undefined)).toBe(false);
  });
  it("VITEST 环境不传 force → gsap 零调用(jsdom 无布局守卫)", () => {
    const root = document.createElement("div");
    root.innerHTML = `<section data-act-reveal></section>`;
    const cleanup = initScrollActs(root);
    expect(gsapMock.registerPlugin).not.toHaveBeenCalled();
    expect(gsapMock.context).not.toHaveBeenCalled();
    expect(gsapMock.from).not.toHaveBeenCalled();
    expect(cleanup).not.toThrow();
  });
});
