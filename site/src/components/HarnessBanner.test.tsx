import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { HarnessBanner } from "./HarnessBanner";

const setup = () => render(<HarnessBanner />);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HarnessBanner", () => {
  it("指向 /harness/ 的原生整页链接（看板不在 SPA 路由内）", () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    setup();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/harness/");
    expect(link).not.toHaveAttribute("target");
  });

  it("流程文案常驻，含 SDD/TDD 工程化阶段词", () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    setup();
    expect(
      screen.getByText(/SDD 计划门 · TDD 红绿纪律 · 对抗式机审 CR/),
    ).toBeInTheDocument();
  });

  it("取到 data.json 后追加实时胶囊：线程数不含归档、机审轮次含全量，流程文案不被顶掉", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            threads: [
              { archived: false, cr_rounds: 30 },
              { archived: true, cr_rounds: 6 },
              { archived: false },
            ],
          }),
      }),
    );
    setup();
    expect(await screen.findByText("2 条线程 · 机审 36 轮")).toBeInTheDocument();
    expect(
      screen.getByText(/SDD 计划门 · TDD 红绿纪律 · 对抗式机审 CR/),
    ).toBeInTheDocument();
  });

  it("响应非 ok 或形状不对时不出实时胶囊", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }),
    );
    setup();
    expect(
      await screen.findByText(/飞书机器人接需求/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/条线程 · 机审/)).toBeNull();
  });
});
