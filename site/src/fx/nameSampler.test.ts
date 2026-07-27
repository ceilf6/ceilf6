import { describe, expect, it } from "vitest";
import { samplePoints } from "./nameSampler";

// 结构化类型入参，测试不依赖 jsdom 的 ImageData 构造器
function makeImage(w: number, h: number, opaque: Array<[number, number]>) {
  const data = new Uint8ClampedArray(w * h * 4);
  for (const [x, y] of opaque) data[(y * w + x) * 4 + 3] = 255;
  return { data, width: w, height: h };
}

describe("samplePoints", () => {
  it("按步长采样 alpha 超阈值的像素为目标点", () => {
    const img = makeImage(6, 6, [
      [0, 0],
      [3, 3],
      [4, 4],
    ]);
    expect(samplePoints(img, 3)).toEqual([
      { tx: 0, ty: 0 },
      { tx: 3, ty: 3 },
    ]); // (4,4) 不在 3 步长网格上
  });
  it("全透明返回空数组", () => {
    expect(samplePoints(makeImage(4, 4, []), 2)).toEqual([]);
  });
});
