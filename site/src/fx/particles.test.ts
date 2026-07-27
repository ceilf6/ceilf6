import { describe, expect, it } from "vitest";
import { createField, linkPairs, stepField } from "./particles";

describe("粒子纯函数", () => {
  it("createField 数量与注入随机源可复现", () => {
    let seed = 0.1;
    const rand = () => (seed = (seed * 9301 + 0.2113) % 1);
    const ps = createField(5, 100, 50, rand);
    expect(ps).toHaveLength(5);
    for (const p of ps) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(100);
      expect(p.r).toBeGreaterThan(0);
    }
  });
  it("stepField 越界环绕", () => {
    const ps = [{ x: 99.9, y: 0.1, vx: 1, vy: -1, r: 1, gold: false }];
    stepField(ps, 100, 50, { x: -1e4, y: -1e4 }, 16.7);
    expect(ps[0].x).toBeLessThanOrEqual(100);
    expect(ps[0].y).toBeGreaterThanOrEqual(0);
  });
  it("linkPairs 只连阈内点并给出线性衰减 alpha", () => {
    const ps = [
      { x: 0, y: 0, vx: 0, vy: 0, r: 1, gold: false },
      { x: 45, y: 0, vx: 0, vy: 0, r: 1, gold: false },
      { x: 500, y: 0, vx: 0, vy: 0, r: 1, gold: false },
    ];
    const pairs = linkPairs(ps, 90);
    expect(pairs).toHaveLength(1);
    const [i, j, a] = pairs[0];
    expect([i, j]).toEqual([0, 1]);
    expect(a).toBeCloseTo(0.5, 5);
  });
});
