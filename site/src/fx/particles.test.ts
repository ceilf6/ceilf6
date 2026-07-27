import { describe, expect, it } from "vitest";
import { createField, linkPairs, rescaleField, stepField } from "./particles";

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
    const ps = [{ x: 99.9, y: 0.1, vx: 1, vy: -1, bvx: 1, bvy: -1, r: 1, gold: false }];
    stepField(ps, 100, 50, { x: -1e4, y: -1e4 }, 16.7);
    expect(ps[0].x).toBeLessThanOrEqual(100);
    expect(ps[0].y).toBeGreaterThanOrEqual(0);
  });
  it("stepField 长跑不冻结:基速漂移使场均速不衰减到停滞", () => {
    let seed = 0.42;
    const rand = () => (seed = (seed * 9301 + 0.2113) % 1);
    const ps = createField(30, 200, 100, rand);
    const meanSpeed = (arr: typeof ps) => arr.reduce((s, p) => s + Math.hypot(p.vx, p.vy), 0) / arr.length;
    const v0 = meanSpeed(ps);
    for (let t = 0; t < 5000; t++) stepField(ps, 200, 100, { x: -1e4, y: -1e4 }, 16.7);
    expect(meanSpeed(ps)).toBeGreaterThanOrEqual(v0 / 2);
  });
  it("stepField 鼠标扰动衰减回基速", () => {
    const ps = [{ x: 50, y: 25, vx: 0.1, vy: -0.1, bvx: 0.1, bvy: -0.1, r: 1, gold: false }];
    stepField(ps, 1e4, 1e4, { x: 60, y: 25 }, 16.7);
    expect(ps[0].vx).toBeGreaterThan(0.1); // 近距鼠标产生吸引扰动
    for (let t = 0; t < 2000; t++) stepField(ps, 1e4, 1e4, { x: -1e4, y: -1e4 }, 16.7);
    expect(ps[0].vx).toBeCloseTo(0.1, 3); // 扰动指数归位,不吃掉基速
    expect(ps[0].vy).toBeCloseTo(-0.1, 3);
  });
  it("rescaleField 按比例重分布,非法尺寸 no-op", () => {
    const ps = [{ x: 50, y: 25, vx: 0, vy: 0, bvx: 0, bvy: 0, r: 1, gold: false }];
    rescaleField(ps, 100, 50, 200, 50);
    expect(ps[0].x).toBeCloseTo(100, 5);
    expect(ps[0].y).toBeCloseTo(25, 5);
    rescaleField(ps, 0, 50, 100, 50);
    expect(ps[0].x).toBeCloseTo(100, 5);
    expect(ps[0].y).toBeCloseTo(25, 5);
  });
  it("linkPairs 只连阈内点并给出线性衰减 alpha", () => {
    const ps = [
      { x: 0, y: 0, vx: 0, vy: 0, bvx: 0, bvy: 0, r: 1, gold: false },
      { x: 45, y: 0, vx: 0, vy: 0, bvx: 0, bvy: 0, r: 1, gold: false },
      { x: 500, y: 0, vx: 0, vy: 0, bvx: 0, bvy: 0, r: 1, gold: false },
    ];
    const pairs = linkPairs(ps, 90);
    expect(pairs).toHaveLength(1);
    const [i, j, a] = pairs[0];
    expect([i, j]).toEqual([0, 1]);
    expect(a).toBeCloseTo(0.5, 5);
  });
});
