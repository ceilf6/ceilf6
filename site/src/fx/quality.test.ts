import { describe, expect, it } from "vitest";
import { createFpsMeter } from "./quality";

describe("createFpsMeter", () => {
  it("60fps 采样窗口结束判 full", () => {
    const m = createFpsMeter({ sampleMs: 1000, threshold: 40 });
    let verdict: string | null = null;
    for (let t = 0; t <= 1100 && verdict === null; t += 16.7) verdict = m.frame(t);
    expect(verdict).toBe("full");
  });
  it("20fps 判 lite", () => {
    const m = createFpsMeter({ sampleMs: 1000, threshold: 40 });
    let verdict: string | null = null;
    for (let t = 0; t <= 1100 && verdict === null; t += 50) verdict = m.frame(t);
    expect(verdict).toBe("lite");
  });
  it("采样窗口未满返回 null", () => {
    const m = createFpsMeter({ sampleMs: 1000, threshold: 40 });
    expect(m.frame(0)).toBeNull();
    expect(m.frame(500)).toBeNull();
  });
  it("采样中途标签页挂起不误判 lite", () => {
    const m = createFpsMeter({ sampleMs: 1000, threshold: 40 });
    let verdict: string | null = m.frame(0);
    let t = 0;
    for (let i = 0; i < 20 && verdict === null; i++) verdict = m.frame((t += 16.7));
    verdict = m.frame((t += 5000)); // 挂起 5s
    for (let i = 0; i < 200 && verdict === null; i++) verdict = m.frame((t += 16.7));
    expect(verdict).toBe("full");
  });
});
