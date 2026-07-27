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
  it("画廊卡片有 stagger 编排、hero 背景有视差", () => {
    const root = document.createElement("div");
    root.innerHTML = `
      <section class="act-hero"><div class="hero-bg"></div></section>
      <section class="act-gallery"><div class="gallery"><div class="card"></div></div></section>`;
    initScrollActs(root, { force: true });
    const fromCalls = gsapMock.from.mock.calls;
    expect(fromCalls.some(([, cfg]) => cfg.stagger !== undefined)).toBe(true);
    expect(gsapMock.to).toHaveBeenCalled();
  });
  it("返回 cleanup,调用即 revert", () => {
    const root = document.createElement("div");
    const cleanup = initScrollActs(root, { force: true });
    cleanup();
    expect(gsapMock.context.mock.results[0].value.revert).toHaveBeenCalled();
  });
});
