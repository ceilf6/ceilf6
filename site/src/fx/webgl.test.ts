import { describe, expect, it } from "vitest";
import { initQuadProgram } from "./webgl";

describe("initQuadProgram", () => {
  it("无 WebGL 环境(jsdom)返回 null 而非抛错", () => {
    const cv = document.createElement("canvas");
    expect(initQuadProgram(cv, "void main(){}")).toBeNull();
  });
});
