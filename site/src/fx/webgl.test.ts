import { describe, expect, it } from "vitest";
import { initQuadProgram } from "./webgl";

describe("initQuadProgram", () => {
  it("无 WebGL 环境(jsdom)返回 null 而非抛错", () => {
    const cv = document.createElement("canvas");
    expect(initQuadProgram(cv, "void main(){}")).toBeNull();
  });
  // GPU 黑名单、隐私模式等环境下 getContext 是「抛」而不是「返回 null」，
  // 契约要求这条路径同样收敛成 null，否则降级失效、整页跟着崩。
  it("getContext 抛异常时兜底返回 null", () => {
    const cv = document.createElement("canvas");
    cv.getContext = () => {
      throw new Error("blocked");
    };
    expect(initQuadProgram(cv, "void main(){}")).toBeNull();
  });
});
