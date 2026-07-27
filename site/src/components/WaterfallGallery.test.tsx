import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { awards } from "../data/awards";
import { useFxQuality } from "../fx/quality";
import { initQuadProgram } from "../fx/webgl";
import type { QuadProgram } from "../fx/webgl";
import { WaterfallGallery } from "./WaterfallGallery";

// 默认透传真实实现，仅波纹用例内改返回值（同 AuroraCanvas.test 手法）
vi.mock(import("../fx/quality"), async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useFxQuality: vi.fn(actual.useFxQuality) };
});
// 默认返回 null = jsdom 真实行为（无 WebGL→惰性）；守卫/teardown 用例换 stub 程序
vi.mock(import("../fx/webgl"), () => ({
  initQuadProgram: vi.fn(() => null),
}));

/** 只覆盖 RippleOverlay 在监听挂载前会触碰的 GL 面；常量值无意义，仅防 undefined 访问 */
const progStub = (): QuadProgram => {
  const gl = {
    TEXTURE_2D: 0,
    TEXTURE_MIN_FILTER: 0,
    TEXTURE_MAG_FILTER: 0,
    TEXTURE_WRAP_S: 0,
    TEXTURE_WRAP_T: 0,
    LINEAR: 0,
    CLAMP_TO_EDGE: 0,
    RGBA: 0,
    UNSIGNED_BYTE: 0,
    createTexture: () => ({}) as WebGLTexture,
    bindTexture() {},
    texParameteri() {},
    deleteTexture() {},
    viewport() {},
    uniform1f() {},
    uniform2f() {},
    texImage2D() {},
  } as unknown as WebGLRenderingContext;
  return { gl, uniform: () => null, draw() {}, destroy() {} };
};

afterEach(() => {
  // restoreAllMocks 只管 spyOn；vi.fn 需 mockReset 才会还原为传入的默认实现
  vi.mocked(useFxQuality).mockReset();
  vi.mocked(initQuadProgram).mockReset();
  vi.restoreAllMocks();
});

function ViewerProbe() {
  const { search } = useLocation();
  return <div data-testid="viewer-probe">{search}</div>;
}

// 工厂而非 const：rerender 传同一元素引用会触发 React 相同元素 bailout，
// 子树整个跳过重渲，mock 返回值翻转对 React 不可见——必须每次造新元素树
const ui = () => (
  <MemoryRouter initialEntries={["/"]}>
    <Routes>
      <Route path="/" element={<WaterfallGallery />} />
      <Route path="/viewer" element={<ViewerProbe />} />
    </Routes>
  </MemoryRouter>
);

const setup = () => render(ui());

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

describe("乙·波纹覆盖层", () => {
  it("画廊挂载共享 ripple canvas,且 <img> 原件全部保留(可达性契约)", () => {
    const { container } = setup();
    expect(container.querySelector(".ripple-overlay")).not.toBeNull();
    // jsdom 无 WebGL:覆盖层必须保持惰性,不影响 15 张缩略图
    expect(container.querySelectorAll(".card img")).toHaveLength(15);
  });

  it("quality 翻 lite 触发 effect 重跑时,teardown 清掉 is-on(防冻结帧悬浮)", () => {
    vi.mocked(useFxQuality).mockReturnValue("full");
    const { container, rerender } = setup();
    const overlay = container.querySelector(".ripple-overlay")!;
    // jsdom 触发不了真实 hover 激活,手工置激活态模拟「降档瞬间正悬停」
    overlay.classList.add("is-on");
    vi.mocked(useFxQuality).mockReturnValue("lite");
    rerender(ui());
    expect(overlay.classList.contains("is-on")).toBe(false);
  });

  it("窗口 resize 时波纹失活(旧定位作废,下次 mouseover 重新定位)", () => {
    vi.mocked(initQuadProgram).mockReturnValue(progStub());
    const { container } = setup();
    const overlay = container.querySelector(".ripple-overlay")!;
    overlay.classList.add("is-on");
    fireEvent(window, new Event("resize"));
    expect(overlay.classList.contains("is-on")).toBe(false);
  });

  it("守卫矩阵:hover:none(触屏)下不在画廊挂 mouseover 监听", () => {
    // WebGL 可用也不行——守卫必须在 init 之前生效
    vi.mocked(initQuadProgram).mockReturnValue(progStub());
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: query === "(hover: none)",
          media: query,
          addEventListener() {},
          removeEventListener() {},
          addListener() {},
          removeListener() {},
          onchange: null,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    );
    // 先以 lite 挂载(effect 早退,零监听基线),再翻 full 触发 effect 重跑
    vi.mocked(useFxQuality).mockReturnValue("lite");
    const { container, rerender } = setup();
    const host = container.querySelector(".gallery") as HTMLElement;
    const spy = vi.spyOn(host, "addEventListener");
    vi.mocked(useFxQuality).mockReturnValue("full");
    rerender(ui());
    expect(spy.mock.calls.map(([type]) => type)).not.toContain("mouseover");
  });
});
